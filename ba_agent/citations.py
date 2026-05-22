"""
Citation extraction from MCP tool_result blocks and final answer annotation.
Typed dataclasses preserve source metadata; annotate_answer appends a Sources
section to the synthesized text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Citation dataclasses
# ---------------------------------------------------------------------------

@dataclass
class JiraCitation:
    ticket_id: str
    summary: str = ""
    url: str = ""

    def label(self) -> str:
        return f"Jira — {self.ticket_id}"

    def detail(self) -> str:
        parts = [f"Jira ticket {self.ticket_id}"]
        if self.summary:
            parts.append(self.summary)
        if self.url:
            parts.append(self.url)
        return " — ".join(parts)


@dataclass
class DriveCitation:
    file_name: str
    file_id: str = ""
    url: str = ""

    def label(self) -> str:
        return f"Google Drive — {self.file_name}"

    def detail(self) -> str:
        parts = [f"Google Drive: {self.file_name}"]
        if self.file_id:
            parts.append(f"ID: {self.file_id}")
        if self.url:
            parts.append(self.url)
        return " — ".join(parts)


@dataclass
class ConfluenceCitation:
    page_title: str
    space_key: str = ""
    url: str = ""

    def label(self) -> str:
        return f"Confluence — {self.page_title}"

    def detail(self) -> str:
        parts = [f"Confluence: {self.page_title}"]
        if self.space_key:
            parts.append(f"Space: {self.space_key}")
        if self.url:
            parts.append(self.url)
        return " — ".join(parts)


@dataclass
class SalesforceCitation:
    record_id: str
    object_type: str = ""
    url: str = ""

    def label(self) -> str:
        return f"Salesforce — {self.record_id}"

    def detail(self) -> str:
        parts = [f"Salesforce {self.object_type}: {self.record_id}".strip()]
        if self.url:
            parts.append(self.url)
        return " — ".join(parts)


@dataclass
class HubSpotCitation:
    record_id: str
    record_type: str = ""
    url: str = ""

    def label(self) -> str:
        return f"HubSpot — {self.record_id}"

    def detail(self) -> str:
        parts = [f"HubSpot {self.record_type}: {self.record_id}".strip()]
        if self.url:
            parts.append(self.url)
        return " — ".join(parts)


Citation = JiraCitation | DriveCitation | ConfluenceCitation | SalesforceCitation | HubSpotCitation


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _get_text_from_block(block: Any) -> str:
    """Pull text content from a tool_result or text block."""
    if isinstance(block, dict):
        content = block.get("content", block.get("text", ""))
        if isinstance(content, list):
            return " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        return str(content)
    if hasattr(block, "content"):
        c = block.content
        if isinstance(c, list):
            return " ".join(
                getattr(item, "text", str(item)) for item in c
            )
        return str(c)
    if hasattr(block, "text"):
        return block.text
    return str(block)


def _tool_name(block: Any) -> str:
    if isinstance(block, dict):
        return block.get("name", block.get("tool_name", ""))
    return getattr(block, "name", "") or getattr(block, "tool_name", "")


def _block_type(block: Any) -> str:
    if isinstance(block, dict):
        return block.get("type", "")
    return getattr(block, "type", "")


def _is_tool_result(block: Any) -> bool:
    t = _block_type(block)
    return "tool_result" in t or "mcp_tool_result" in t


def _is_tool_use(block: Any) -> bool:
    t = _block_type(block)
    return "tool_use" in t or "mcp_tool_use" in t


# ---------------------------------------------------------------------------
# Per-source extractors
# ---------------------------------------------------------------------------

def _extract_jira_citation(phase1_result: Any) -> JiraCitation | None:
    """Build a Jira citation from the Phase1Result dataclass."""
    if not phase1_result.ticket_id:
        return None
    return JiraCitation(
        ticket_id=phase1_result.ticket_id,
        summary=phase1_result.summary,
        url=phase1_result.jira_url,
    )


def _extract_drive_citations(messages: list[dict]) -> list[DriveCitation]:
    citations: list[DriveCitation] = []
    seen: set[str] = set()

    for msg in messages:
        content = msg.get("content", []) if isinstance(msg, dict) else []
        for block in content:
            if not _is_tool_result(block):
                continue
            text = _get_text_from_block(block)
            # Look for file names and IDs in Drive results
            for name_match in re.finditer(
                r'"(?:name|title|fileName)"\s*:\s*"([^"]+)"', text
            ):
                file_name = name_match.group(1)
                if file_name in seen:
                    continue
                seen.add(file_name)
                file_id = ""
                id_match = re.search(r'"(?:id|fileId)"\s*:\s*"([^"]+)"', text)
                if id_match:
                    file_id = id_match.group(1)
                url = ""
                url_match = re.search(
                    r'"(?:webViewLink|url|link)"\s*:\s*"([^"]+)"', text
                )
                if url_match:
                    url = url_match.group(1)
                citations.append(
                    DriveCitation(file_name=file_name, file_id=file_id, url=url)
                )
    return citations


def _extract_confluence_citations(messages: list[dict]) -> list[ConfluenceCitation]:
    citations: list[ConfluenceCitation] = []
    seen: set[str] = set()

    for msg in messages:
        content = msg.get("content", []) if isinstance(msg, dict) else []
        for block in content:
            if not _is_tool_result(block):
                continue
            text = _get_text_from_block(block)
            for title_match in re.finditer(
                r'"title"\s*:\s*"([^"]+)"', text
            ):
                title = title_match.group(1)
                if title in seen:
                    continue
                seen.add(title)
                space = ""
                space_match = re.search(r'"key"\s*:\s*"([^"]+)"', text)
                if space_match:
                    space = space_match.group(1)
                url = ""
                url_match = re.search(r'"(?:_links|webui|url).*?"(?:webui|self)"\s*:\s*"([^"]+)"', text)
                if url_match:
                    url = url_match.group(1)
                citations.append(
                    ConfluenceCitation(page_title=title, space_key=space, url=url)
                )
    return citations


def _extract_salesforce_citations(messages: list[dict]) -> list[SalesforceCitation]:
    citations: list[SalesforceCitation] = []
    seen: set[str] = set()

    for msg in messages:
        content = msg.get("content", []) if isinstance(msg, dict) else []
        for block in content:
            if not _is_tool_result(block):
                continue
            text = _get_text_from_block(block)
            # Salesforce record IDs are 15 or 18 char alphanumeric
            for id_match in re.finditer(r'\b([A-Za-z0-9]{15}|[A-Za-z0-9]{18})\b', text):
                record_id = id_match.group(1)
                if record_id in seen:
                    continue
                seen.add(record_id)
                obj_type = ""
                type_match = re.search(r'"(?:type|sobjectType|objectApiName)"\s*:\s*"([^"]+)"', text)
                if type_match:
                    obj_type = type_match.group(1)
                citations.append(
                    SalesforceCitation(record_id=record_id, object_type=obj_type)
                )
                if len(citations) >= 5:  # cap per-query
                    break
    return citations


def _extract_hubspot_citations(messages: list[dict]) -> list[HubSpotCitation]:
    citations: list[HubSpotCitation] = []
    seen: set[str] = set()

    for msg in messages:
        content = msg.get("content", []) if isinstance(msg, dict) else []
        for block in content:
            if not _is_tool_result(block):
                continue
            text = _get_text_from_block(block)
            for id_match in re.finditer(r'"(?:id|objectId|hs_object_id)"\s*:\s*"?(\d+)"?', text):
                record_id = id_match.group(1)
                if record_id in seen:
                    continue
                seen.add(record_id)
                rec_type = ""
                type_match = re.search(
                    r'"(?:objectTypeId|type)"\s*:\s*"([^"]+)"', text
                )
                if type_match:
                    rec_type = type_match.group(1)
                citations.append(
                    HubSpotCitation(record_id=record_id, record_type=rec_type)
                )
                if len(citations) >= 5:
                    break
    return citations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_all_citations(phase1_result: Any, phase2_result: Any) -> list[Citation]:
    """Extract typed citations from both phase results."""
    citations: list[Citation] = []

    jira_cit = _extract_jira_citation(phase1_result)
    if jira_cit:
        citations.append(jira_cit)

    messages = phase2_result.message_history
    citations.extend(_extract_drive_citations(messages))
    citations.extend(_extract_confluence_citations(messages))
    citations.extend(_extract_salesforce_citations(messages))
    citations.extend(_extract_hubspot_citations(messages))

    return citations


def annotate_answer(answer_text: str, citations: list[Citation]) -> str:
    """Append a numbered Sources section to the synthesized answer."""
    if not citations:
        return answer_text

    # Remove any Sources section already written by Phase 3 (we'll rebuild it)
    answer_text = re.sub(
        r"\n#+\s*Sources\b.*$", "", answer_text, flags=re.DOTALL | re.IGNORECASE
    ).rstrip()

    lines = ["\n\n## Sources\n"]
    for i, cit in enumerate(citations, 1):
        lines.append(f"[{i}] {cit.detail()}")

    return answer_text + "\n".join(lines)
