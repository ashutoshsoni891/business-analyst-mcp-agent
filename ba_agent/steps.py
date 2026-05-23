"""
Per-phase API call logic. Each phase runs its own agentic loop against
the Anthropic MCP client beta, with only the relevant MCP servers attached.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic

from .config import MODEL

MCP_BETA = "mcp-client-2025-04-04"

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_PHASE1_SYSTEM = """\
You are a Jira search specialist. Given a business analyst's query, search \
Jira to find the single most relevant ticket.

After searching, return your findings as a JSON code block (```json) with \
exactly these keys:
{
  "ticket_id": "PROJ-1234",
  "customer_name": "Company name from the ticket",
  "date": "ISO date of the ticket (created or issue date)",
  "topic": "One-line topic summary",
  "jira_url": "Full URL to the ticket",
  "summary": "2-3 sentence description of the ticket content"
}

If no relevant ticket is found, return:
{"ticket_id": null}

Only return information present in actual search results. Do not fabricate IDs."""

_PHASE3_SYSTEM = """\
You are a business analyst research assistant synthesizing findings from \
multiple enterprise systems.

Rules:
1. Every factual claim MUST be followed by a citation in the format \
   [SOURCE: identifier] where identifier is a Jira ticket ID, document title, \
   file name, or CRM record ID.
2. Do not introduce any fact not present in the provided research.
3. If sources contradict each other, note the contradiction explicitly.
4. Structure your response with these sections:
   ## Summary
   ## Key Findings
   ## Timeline (omit if no date information available)
   ## Recommendations (omit if not applicable)
   ## Sources

In the Sources section, list every cited record on its own line as:
[N] Type — Identifier — URL (if available)"""

_COMPRESSOR_SYSTEM = """\
Summarize the following retrieval results for a research brief.

Rules:
1. Preserve ALL identifiers exactly: file IDs, document titles, record IDs, \
   URLs, ticket numbers, customer names, dates. These are needed for citations.
2. Compress prose content to essential facts only.
3. Use bullet points, one per key finding, with identifiers inline.
4. Maximum output: 600 tokens."""


def _build_phase2_system(user_query: str, jira: "Phase1Result", available_servers: list[str]) -> str:
    system_list = []
    n = 1
    if "drive" in available_servers:
        system_list.append(
            f'{n}. Google Drive — search for Meet transcripts, call notes, or documents '
            f'related to "{jira.customer_name}" and "{jira.topic}".'
        )
        n += 1
    if "confluence" in available_servers:
        system_list.append(
            f'{n}. Confluence — search for documentation, runbooks, or post-mortems '
            f'related to this customer or topic.'
        )
        n += 1
    if "salesforce" in available_servers:
        system_list.append(
            f'{n}. Salesforce — find the customer account, any cases or opportunities '
            f'related to "{jira.customer_name}".'
        )
        n += 1
    if "hubspot" in available_servers:
        system_list.append(
            f'{n}. HubSpot — find contacts and deals associated with "{jira.customer_name}".'
        )

    systems_text = "\n".join(system_list)
    system_count = "all" if len(system_list) > 1 else "the"

    return f"""\
You are a cross-system research agent. A business analyst needs information \
about the following Jira ticket:

Ticket ID: {jira.ticket_id}
Customer: {jira.customer_name}
Date: {jira.date}
Topic: {jira.topic}

The analyst's original question: "{user_query}"

Your task — search {system_count} of the following systems using the ticket context \
above as search terms. Execute searches across all systems; do not wait for \
one before starting another.

{systems_text}

For each result, record the source system, document/record title or ID, \
and all relevant content. Preserve all identifiers (file names, IDs, URLs). \
Return the raw findings — do not summarize at this stage."""


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Phase1Result:
    ticket_id: str | None
    customer_name: str = ""
    date: str = ""
    topic: str = ""
    jira_url: str = ""
    summary: str = ""
    raw_messages: list[dict] = field(default_factory=list)


@dataclass
class Phase2Result:
    message_history: list[dict] = field(default_factory=list)
    final_text: str = ""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _content_to_api(content: list) -> list[dict]:
    """Convert SDK content blocks to plain dicts for the next API call."""
    result = []
    for block in content:
        if hasattr(block, "model_dump"):
            result.append(block.model_dump())
        elif isinstance(block, dict):
            result.append(block)
        else:
            result.append({"type": "text", "text": str(block)})
    return result


def _extract_text(content: list) -> str:
    """Pull plain text from response content blocks."""
    parts = []
    for block in content:
        if hasattr(block, "type") and block.type == "text":
            parts.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _dump_debug(label: str, obj: Any) -> None:
    """Print debug info to stderr when debug mode is active."""
    import sys
    print(f"\n[DEBUG] {label}", file=sys.stderr)
    if hasattr(obj, "__dict__"):
        print(json.dumps(obj.__dict__, default=str, indent=2), file=sys.stderr)
    else:
        print(repr(obj), file=sys.stderr)


# ---------------------------------------------------------------------------
# Phase 1 — Jira anchor
# ---------------------------------------------------------------------------

def run_phase1_jira(
    client: anthropic.Anthropic,
    mcp_configs: dict,
    user_query: str,
    debug: bool = False,
) -> Phase1Result:
    """Search Jira and extract structured ticket context."""
    messages: list[dict] = [{"role": "user", "content": user_query}]
    jira_server = mcp_configs["jira"]

    while True:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=_PHASE1_SYSTEM,
            messages=messages,
            mcp_servers=[jira_server],
            betas=[MCP_BETA],
        )

        if debug:
            _dump_debug("Phase 1 response", response)

        messages.append({"role": "assistant", "content": _content_to_api(response.content)})

        if response.stop_reason == "end_turn":
            break

    final_text = _extract_text(response.content)
    return _parse_phase1_result(final_text, messages)


def _parse_phase1_result(text: str, messages: list[dict]) -> Phase1Result:
    """Extract the JSON block from Claude's phase 1 response."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        # Try bare JSON object
        match = re.search(r"\{[^{}]*\"ticket_id\"[^{}]*\}", text, re.DOTALL)
    if not match:
        return Phase1Result(ticket_id=None, raw_messages=messages)

    try:
        data = json.loads(match.group(1) if "```" in text else match.group(0))
    except json.JSONDecodeError:
        return Phase1Result(ticket_id=None, raw_messages=messages)

    return Phase1Result(
        ticket_id=data.get("ticket_id"),
        customer_name=data.get("customer_name", ""),
        date=data.get("date", ""),
        topic=data.get("topic", ""),
        jira_url=data.get("jira_url", ""),
        summary=data.get("summary", ""),
        raw_messages=messages,
    )


# ---------------------------------------------------------------------------
# Phase 2 — Parallel fan-out
# ---------------------------------------------------------------------------

def run_phase2_fanout(
    client: anthropic.Anthropic,
    mcp_configs: dict,
    user_query: str,
    jira: Phase1Result,
    debug: bool = False,
) -> Phase2Result:
    """Search Drive, Confluence, and optionally Salesforce/HubSpot using Jira context."""
    available = [k for k in ("drive", "confluence", "salesforce", "hubspot") if k in mcp_configs]
    system = _build_phase2_system(user_query, jira, available)
    system_names = ", ".join(available)
    messages: list[dict] = [
        {"role": "user", "content": f"Please research the following systems now: {system_names}."}
    ]
    servers = [mcp_configs[k] for k in available]

    while True:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=system,
            messages=messages,
            mcp_servers=servers,
            betas=[MCP_BETA],
        )

        if debug:
            _dump_debug("Phase 2 response", response)

        messages.append({"role": "assistant", "content": _content_to_api(response.content)})

        if response.stop_reason == "end_turn":
            break

    return Phase2Result(
        message_history=messages,
        final_text=_extract_text(response.content),
    )


# ---------------------------------------------------------------------------
# Phase 3 — Synthesis
# ---------------------------------------------------------------------------

def run_phase3_synthesis(
    client: anthropic.Anthropic,
    user_query: str,
    jira: Phase1Result,
    research_context: str,
    debug: bool = False,
) -> str:
    """Synthesize all retrieved information into a cited final answer."""
    user_content = (
        f"Analyst query: {user_query}\n\n"
        f"Jira anchor — Ticket {jira.ticket_id} ({jira.customer_name}, "
        f"{jira.date}): {jira.summary}\n\n"
        f"Research findings from all systems:\n{research_context}"
    )
    messages: list[dict] = [{"role": "user", "content": user_content}]

    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=_PHASE3_SYSTEM,
        messages=messages,
        betas=[MCP_BETA],
    )

    if debug:
        _dump_debug("Phase 3 response", response)

    return _extract_text(response.content)


# ---------------------------------------------------------------------------
# Compressor sub-call
# ---------------------------------------------------------------------------

def compress_text(
    client: anthropic.Anthropic,
    source_name: str,
    content: str,
    debug: bool = False,
) -> str:
    """Summarize a single source's raw findings, preserving all identifiers."""
    from .config import COMPRESSOR_MODEL

    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"Source: {source_name}\n\n"
                f"Raw findings:\n{content}"
            ),
        }
    ]
    response = client.messages.create(
        model=COMPRESSOR_MODEL,
        max_tokens=1024,
        system=_COMPRESSOR_SYSTEM,
        messages=messages,
    )

    if debug:
        _dump_debug(f"Compressor ({source_name})", response)

    return _extract_text(response.content)
