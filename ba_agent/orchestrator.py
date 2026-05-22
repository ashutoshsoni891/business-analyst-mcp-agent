"""
Top-level agent runner. Wires Phase 1 → Phase 2 → compression → Phase 3
and assembles the final cited answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import anthropic

from .citations import annotate_answer, extract_all_citations
from .compressor import compress_if_needed, format_for_synthesis
from .config import load_config, build_mcp_configs
from .steps import run_phase1_jira, run_phase2_fanout, run_phase3_synthesis


@dataclass
class RunOptions:
    debug: bool = False
    # Callbacks for progress reporting (called with a status string)
    on_phase: Callable[[str], None] = lambda _: None


def run(user_query: str, options: RunOptions | None = None) -> str:
    """
    Execute the full BA research pipeline for a natural-language query.
    Returns the synthesized answer with source citations.
    """
    opts = options or RunOptions()

    cfg = load_config()
    mcp_configs = build_mcp_configs(cfg)
    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"])

    # ------------------------------------------------------------------
    # Phase 1 — Jira anchor
    # ------------------------------------------------------------------
    opts.on_phase("Searching Jira...")
    phase1 = run_phase1_jira(client, mcp_configs, user_query, debug=opts.debug)

    if not phase1.ticket_id:
        return (
            "No relevant Jira ticket found for your query. "
            "Cannot anchor the cross-system search without a ticket. "
            "Try rephrasing with a customer name, ticket keyword, or date range."
        )

    # ------------------------------------------------------------------
    # Phase 2 — Parallel fan-out to Drive, Confluence, Salesforce, HubSpot
    # ------------------------------------------------------------------
    opts.on_phase(
        f"Found {phase1.ticket_id} ({phase1.customer_name}). "
        "Fanning out to Drive / Confluence / Salesforce / HubSpot..."
    )
    phase2 = run_phase2_fanout(
        client, mcp_configs, user_query, phase1, debug=opts.debug
    )

    # ------------------------------------------------------------------
    # Context compression (if total tokens exceed threshold)
    # ------------------------------------------------------------------
    opts.on_phase("Checking context size...")
    compressed_history = compress_if_needed(client, phase2, debug=opts.debug)

    # ------------------------------------------------------------------
    # Phase 3 — Synthesis
    # ------------------------------------------------------------------
    opts.on_phase("Synthesizing answer...")
    research_context = format_for_synthesis(phase1, compressed_history)
    answer = run_phase3_synthesis(
        client, user_query, phase1, research_context, debug=opts.debug
    )

    # ------------------------------------------------------------------
    # Citation extraction and annotation
    # ------------------------------------------------------------------
    citations = extract_all_citations(phase1, phase2)
    return annotate_answer(answer, citations)
