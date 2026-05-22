import os
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-20250514"
COMPRESSOR_MODEL = "claude-haiku-4-5"
TOKEN_COMPRESSION_THRESHOLD = 80_000


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            "Copy .env.example to .env and fill in your credentials."
        )
    return value


def load_config() -> dict:
    """Load and validate all required env vars. Returns config dict."""
    return {
        "anthropic_api_key": _require_env("ANTHROPIC_API_KEY"),
        "atlassian_token": _require_env("ATLASSIAN_OAUTH_TOKEN"),
        "atlassian_url": _require_env("ATLASSIAN_MCP_URL"),
        "drive_token": _require_env("GOOGLE_DRIVE_OAUTH_TOKEN"),
        "drive_url": _require_env("GOOGLE_DRIVE_MCP_URL"),
        "salesforce_token": _require_env("SALESFORCE_OAUTH_TOKEN"),
        "salesforce_url": _require_env("SALESFORCE_MCP_URL"),
        "hubspot_token": _require_env("HUBSPOT_OAUTH_TOKEN"),
        "hubspot_url": _require_env("HUBSPOT_MCP_URL"),
    }


def build_mcp_configs(cfg: dict) -> dict:
    """Build per-server MCP config dicts from loaded config."""
    return {
        "jira": {
            "type": "url",
            "url": cfg["atlassian_url"],
            "name": "atlassian_jira",
            "authorization_token": cfg["atlassian_token"],
        },
        "confluence": {
            "type": "url",
            "url": cfg["atlassian_url"],
            "name": "atlassian_confluence",
            "authorization_token": cfg["atlassian_token"],
        },
        "drive": {
            "type": "url",
            "url": cfg["drive_url"],
            "name": "google_drive",
            "authorization_token": cfg["drive_token"],
        },
        "salesforce": {
            "type": "url",
            "url": cfg["salesforce_url"],
            "name": "salesforce",
            "authorization_token": cfg["salesforce_token"],
        },
        "hubspot": {
            "type": "url",
            "url": cfg["hubspot_url"],
            "name": "hubspot",
            "authorization_token": cfg["hubspot_token"],
        },
    }
