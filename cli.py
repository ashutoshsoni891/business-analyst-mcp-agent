#!/usr/bin/env python3
"""
BA Research Agent CLI.

Usage:
  # Single query
  python cli.py "What was the issue with Acme Corp's API integration?"

  # Interactive REPL
  python cli.py

  # Debug (prints raw MCP tool calls to stderr)
  python cli.py --debug "..."

  # Incremental testing flags
  python cli.py --validate-config
  python cli.py --phase1-only "rate limit issue for Acme"
  python cli.py --phase2-only --jira-context '{"ticket_id":"PROJ-1","customer_name":"Acme","date":"2024-11-15","topic":"rate limit","jira_url":"","summary":""}'
"""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.status import Status
from rich.markdown import Markdown
from rich.rule import Rule

console = Console()
err_console = Console(stderr=True, style="dim")


# ---------------------------------------------------------------------------
# Config validation helper
# ---------------------------------------------------------------------------

def _validate_config_cmd() -> None:
    from ba_agent.config import load_config
    try:
        cfg = load_config()
        console.print("[green]Config OK[/green] — all required environment variables are set.")
        for key in cfg:
            if "token" in key or "key" in key:
                masked = cfg[key][:8] + "..." if len(cfg[key]) > 8 else "***"
                console.print(f"  {key}: {masked}")
            else:
                console.print(f"  {key}: {cfg[key]}")
    except EnvironmentError as e:
        console.print(f"[red]Config error:[/red] {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Phase 1 only (smoke test)
# ---------------------------------------------------------------------------

def _phase1_only_cmd(query: str, debug: bool) -> None:
    from ba_agent.config import load_config, build_mcp_configs
    from ba_agent.steps import run_phase1_jira
    import anthropic

    cfg = load_config()
    mcp_configs = build_mcp_configs(cfg)
    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"])

    with Status("[cyan]Searching Jira...[/cyan]", console=console):
        result = run_phase1_jira(client, mcp_configs, query, debug=debug)

    if result.ticket_id:
        console.print(Panel(
            f"[bold]Ticket:[/bold] {result.ticket_id}\n"
            f"[bold]Customer:[/bold] {result.customer_name}\n"
            f"[bold]Date:[/bold] {result.date}\n"
            f"[bold]Topic:[/bold] {result.topic}\n"
            f"[bold]URL:[/bold] {result.jira_url}\n"
            f"[bold]Summary:[/bold] {result.summary}",
            title="Phase 1 — Jira Result",
            border_style="green",
        ))
    else:
        console.print("[yellow]No Jira ticket found.[/yellow]")


# ---------------------------------------------------------------------------
# Phase 2 only (smoke test)
# ---------------------------------------------------------------------------

def _phase2_only_cmd(jira_context_json: str, query: str, debug: bool) -> None:
    from ba_agent.config import load_config, build_mcp_configs
    from ba_agent.steps import run_phase2_fanout, Phase1Result
    import anthropic

    try:
        data = json.loads(jira_context_json)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid --jira-context JSON:[/red] {e}")
        sys.exit(1)

    jira = Phase1Result(
        ticket_id=data.get("ticket_id", "UNKNOWN"),
        customer_name=data.get("customer_name", ""),
        date=data.get("date", ""),
        topic=data.get("topic", ""),
        jira_url=data.get("jira_url", ""),
        summary=data.get("summary", ""),
    )

    cfg = load_config()
    mcp_configs = build_mcp_configs(cfg)
    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"])

    with Status("[cyan]Fanning out to Drive / Confluence / Salesforce / HubSpot...[/cyan]", console=console):
        result = run_phase2_fanout(client, mcp_configs, query or "Research this ticket.", jira, debug=debug)

    console.print(Panel(
        result.final_text or "(No text findings)",
        title="Phase 2 — Fan-out Findings",
        border_style="blue",
    ))


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def _run_full(query: str, debug: bool) -> None:
    from ba_agent.orchestrator import run, RunOptions

    status_obj: Status | None = None
    current_status = {"text": ""}

    def on_phase(msg: str) -> None:
        nonlocal status_obj
        current_status["text"] = msg
        if status_obj is not None:
            status_obj.update(f"[cyan]{msg}[/cyan]")

    opts = RunOptions(debug=debug, on_phase=on_phase)

    console.print(Rule("[bold]BA Research Agent[/bold]"))
    console.print(f"[dim]Query:[/dim] {query}\n")

    with Status("[cyan]Starting...[/cyan]", console=console) as s:
        status_obj = s
        try:
            answer = run(query, options=opts)
        except EnvironmentError as e:
            console.print(f"\n[red]Configuration error:[/red] {e}")
            sys.exit(1)
        except Exception as e:
            console.print(f"\n[red]Agent error:[/red] {e}")
            if debug:
                import traceback
                traceback.print_exc()
            sys.exit(1)

    console.print(Rule())
    console.print(Markdown(answer))
    console.print(Rule())


# ---------------------------------------------------------------------------
# Interactive REPL
# ---------------------------------------------------------------------------

def _run_repl(debug: bool) -> None:
    console.print(Panel(
        "Type your question and press Enter.\n"
        "Type [bold]exit[/bold] or [bold]quit[/bold] to stop.",
        title="BA Research Agent — Interactive Mode",
        border_style="cyan",
    ))

    while True:
        try:
            query = console.input("\n[bold cyan]Query>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not query:
            continue
        if query.lower() in ("exit", "quit", "q"):
            console.print("[dim]Goodbye.[/dim]")
            break

        _run_full(query, debug=debug)


# ---------------------------------------------------------------------------
# Click entry point
# ---------------------------------------------------------------------------

@click.command()
@click.argument("query", required=False)
@click.option("--debug", is_flag=True, help="Print raw MCP tool calls and results to stderr.")
@click.option("--validate-config", "validate_config", is_flag=True, help="Check all env vars and exit.")
@click.option("--phase1-only", "phase1_only", is_flag=True, help="Run only the Jira anchor phase.")
@click.option("--phase2-only", "phase2_only", is_flag=True, help="Run only the fan-out phase.")
@click.option(
    "--jira-context",
    "jira_context",
    default=None,
    help='JSON string for --phase2-only. E.g. \'{"ticket_id":"PROJ-1","customer_name":"Acme",...}\'',
)
def main(
    query: str | None,
    debug: bool,
    validate_config: bool,
    phase1_only: bool,
    phase2_only: bool,
    jira_context: str | None,
) -> None:
    """BA Research Agent — query across Jira, Drive, Confluence, Salesforce, and HubSpot."""

    if validate_config:
        _validate_config_cmd()
        return

    if phase1_only:
        if not query:
            console.print("[red]--phase1-only requires a QUERY argument.[/red]")
            sys.exit(1)
        _phase1_only_cmd(query, debug=debug)
        return

    if phase2_only:
        if not jira_context:
            console.print("[red]--phase2-only requires --jira-context JSON.[/red]")
            sys.exit(1)
        _phase2_only_cmd(jira_context, query or "", debug=debug)
        return

    if query:
        _run_full(query, debug=debug)
    else:
        _run_repl(debug=debug)


if __name__ == "__main__":
    main()
