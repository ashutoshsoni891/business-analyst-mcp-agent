# BA Research Agent

A multi-phase AI agent that answers business analyst queries by searching across **Jira, Google Drive, Confluence, Salesforce, and HubSpot** — then synthesizing the findings into a single cited answer.

Built on the [Anthropic Claude API](https://docs.anthropic.com/) with MCP (Model Context Protocol) server integrations.

---

## How It Works

The agent runs a three-phase pipeline:

```
User Query
    │
    ▼
Phase 1 — Jira Anchor
    Find the single most relevant Jira ticket (customer, date, topic)
    │
    ▼
Phase 2 — Fan-out Search
    Simultaneously search Google Drive · Confluence · Salesforce · HubSpot
    using the Jira ticket as context
    │
    ▼
    Context compression (if findings exceed token threshold)
    │
    ▼
Phase 3 — Synthesis
    Produce a structured, cited answer across all sources
```

**Models used:**
- `claude-sonnet-4-20250514` — Phases 1, 2, and 3 (main reasoning)
- `claude-haiku-4-5` — Context compressor (when findings are large)

---

## Requirements

- Python 3.10+
- An Anthropic API key
- OAuth tokens for each connected system (Atlassian, Google Drive, Salesforce, HubSpot)

---

## Installation

```bash
# Clone the repo
git clone <repo-url>
cd dynpro

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## Configuration

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Anthropic API
ANTHROPIC_API_KEY=sk-ant-...

# Atlassian MCP (covers both Jira and Confluence)
ATLASSIAN_OAUTH_TOKEN=...
ATLASSIAN_MCP_URL=https://mcp.atlassian.com/v1

# Google Drive MCP
GOOGLE_DRIVE_OAUTH_TOKEN=...
GOOGLE_DRIVE_MCP_URL=https://mcp.googleapis.com/drive/v1

# Salesforce MCP
SALESFORCE_OAUTH_TOKEN=...
SALESFORCE_MCP_URL=https://your-instance.salesforce.com/mcp/v1

# HubSpot MCP
HUBSPOT_OAUTH_TOKEN=...
HUBSPOT_MCP_URL=https://api.hubspot.com/mcp/v1
```

Verify your configuration before running:

```bash
python cli.py --validate-config
```

---

## Usage

### Single query

```bash
python cli.py "What was the issue with Acme Corp's API integration?"
```

### Interactive REPL

```bash
python cli.py
```

Type your questions at the `Query>` prompt. Enter `exit` or `quit` to stop.

### Debug mode

Prints raw MCP tool calls and responses to stderr:

```bash
python cli.py --debug "Rate limit issue for Acme Corp"
```

---

## Incremental Testing

Run individual phases in isolation to test or debug specific integrations.

### Phase 1 only (Jira search)

```bash
python cli.py --phase1-only "rate limit issue for Acme"
```

### Phase 2 only (fan-out search)

Requires a JSON context blob from a previous Phase 1 run:

```bash
python cli.py --phase2-only \
  --jira-context '{"ticket_id":"PROJ-1","customer_name":"Acme","date":"2024-11-15","topic":"rate limit","jira_url":"","summary":""}'
```

---

## Project Structure

```
dynpro/
├── cli.py                  # Click CLI entry point and REPL
├── requirements.txt
├── .env.example
└── ba_agent/
    ├── config.py           # Env var loading and MCP server config
    ├── orchestrator.py     # Pipeline wiring (Phase 1 → 2 → compress → 3)
    ├── steps.py            # Per-phase agentic loop logic
    ├── compressor.py       # Token budget management and compression
    └── citations.py        # Citation extraction and answer annotation
```

---

## CLI Reference

```
Usage: python cli.py [OPTIONS] [QUERY]

Options:
  --debug                   Print raw MCP tool calls to stderr
  --validate-config         Check all env vars and exit
  --phase1-only             Run only the Jira anchor phase
  --phase2-only             Run only the fan-out phase
  --jira-context TEXT       JSON context blob required by --phase2-only
  --help                    Show this message and exit
```

---

## Output Format

The synthesized answer is rendered as Markdown with the following sections:

- **Summary** — High-level answer to the query
- **Key Findings** — Bullet points with inline `[SOURCE: identifier]` citations
- **Timeline** — Chronological events (when date information is available)
- **Recommendations** — Suggested next steps (when applicable)
- **Sources** — Full list of every cited record with type, identifier, and URL
