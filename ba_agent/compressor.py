"""
Context window management. Counts tokens in the phase 2 message history
and, when above the threshold, compresses each source's findings to a
concise bullet-point summary using claude-haiku-4-5.
Citation identifiers are always preserved through compression.
"""

from __future__ import annotations

import re
from typing import Any

import anthropic

from .config import MODEL, TOKEN_COMPRESSION_THRESHOLD
from .steps import Phase2Result, compress_text


# Map MCP server name prefixes to human-readable source labels
_SERVER_LABELS: dict[str, str] = {
    "google_drive": "Google Drive",
    "atlassian_confluence": "Confluence",
    "salesforce": "Salesforce",
    "hubspot": "HubSpot",
}


def count_tokens(client: anthropic.Anthropic, messages: list[dict]) -> int:
    """Estimate token count for a message list using the Anthropic token counter."""
    try:
        result = client.messages.count_tokens(
            model=MODEL,
            messages=messages,
        )
        return result.input_tokens
    except Exception:
        # Fallback: rough character-based estimate
        total_chars = sum(
            len(str(msg)) for msg in messages
        )
        return total_chars // 4


def _block_type(block: Any) -> str:
    if isinstance(block, dict):
        return block.get("type", "")
    return getattr(block, "type", "")


def _server_name_from_block(block: Any) -> str:
    """Extract the MCP server name from a tool_use or tool_result block."""
    if isinstance(block, dict):
        # mcp_tool_use blocks carry server_name
        return block.get("server_name", block.get("server_label", ""))
    return getattr(block, "server_name", "") or getattr(block, "server_label", "")


def _get_text_content(block: Any) -> str:
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
            return " ".join(getattr(item, "text", str(item)) for item in c)
        return str(c)
    return getattr(block, "text", str(block))


def _group_by_source(messages: list[dict]) -> dict[str, str]:
    """
    Walk message history and group all tool_result text content by server name.
    Returns {server_name: combined_text}.
    """
    groups: dict[str, list[str]] = {}

    for msg in messages:
        content = msg.get("content", []) if isinstance(msg, dict) else []
        for block in content:
            btype = _block_type(block)
            if "tool_result" not in btype and "mcp_tool_result" not in btype:
                continue
            server = _server_name_from_block(block)
            if not server:
                # Infer from tool name patterns in adjacent tool_use blocks
                server = "unknown"
            text = _get_text_content(block)
            if text:
                groups.setdefault(server, []).append(text)

    return {k: "\n\n".join(v) for k, v in groups.items()}


def _rebuild_history_with_summaries(
    messages: list[dict],
    summaries: dict[str, str],
) -> list[dict]:
    """
    Replace raw tool_result blocks with compressed summary blocks.
    Non-tool_result blocks (text, tool_use) are preserved unchanged.
    Each server's results are collapsed into a single synthetic text block.
    """
    new_messages: list[dict] = []
    injected: set[str] = set()

    for msg in messages:
        role = msg.get("role", "") if isinstance(msg, dict) else ""
        content = msg.get("content", []) if isinstance(msg, dict) else []

        new_content: list[dict] = []
        for block in content:
            btype = _block_type(block)
            if "tool_result" in btype or "mcp_tool_result" in btype:
                server = _server_name_from_block(block)
                if server in summaries and server not in injected:
                    label = _SERVER_LABELS.get(server, server)
                    new_content.append({
                        "type": "text",
                        "text": f"[Compressed findings from {label}]\n{summaries[server]}",
                    })
                    injected.add(server)
                # Drop the raw tool_result (replaced by summary above, or no summary available)
            else:
                # Preserve text and tool_use blocks
                if isinstance(block, dict):
                    new_content.append(block)
                elif hasattr(block, "model_dump"):
                    new_content.append(block.model_dump())
                else:
                    new_content.append({"type": "text", "text": str(block)})

        if new_content:
            new_messages.append({"role": role, "content": new_content})

    return new_messages


def compress_if_needed(
    client: anthropic.Anthropic,
    phase2_result: Phase2Result,
    debug: bool = False,
) -> list[dict]:
    """
    Check token count of the phase 2 message history.
    If above TOKEN_COMPRESSION_THRESHOLD, compress each source's findings
    and return a rebuilt history. Otherwise return the original history.
    """
    messages = phase2_result.message_history
    total = count_tokens(client, messages)

    if debug:
        import sys
        print(f"\n[DEBUG] Phase 2 token count: {total}", file=sys.stderr)

    if total <= TOKEN_COMPRESSION_THRESHOLD:
        return messages

    source_texts = _group_by_source(messages)

    if debug:
        import sys
        print(
            f"[DEBUG] Compressing {len(source_texts)} sources "
            f"(total {total} tokens > {TOKEN_COMPRESSION_THRESHOLD})",
            file=sys.stderr,
        )

    summaries: dict[str, str] = {}
    for server_name, combined_text in source_texts.items():
        label = _SERVER_LABELS.get(server_name, server_name)
        summaries[server_name] = compress_text(
            client, label, combined_text, debug=debug
        )

    return _rebuild_history_with_summaries(messages, summaries)


def format_for_synthesis(phase1_result: Any, compressed_history: list[dict]) -> str:
    """
    Extract all text content from the compressed (or raw) phase 2 history
    and format it as a readable research context block for Phase 3 synthesis.
    """
    sections: list[str] = []

    for msg in compressed_history:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", [])
        for block in content:
            btype = _block_type(block)
            # Only include text blocks (tool_use blocks are not useful for synthesis)
            if btype == "text":
                text = _get_text_content(block)
                if text.strip():
                    sections.append(text.strip())

    return "\n\n---\n\n".join(sections) if sections else "(No research findings retrieved)"
