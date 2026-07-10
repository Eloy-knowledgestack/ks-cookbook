"""
Shared module: environment config loading + KS API client.

Every step script gets an authenticated client via `from ksclient import client`.

Config loading priority (highest to lowest):
  1. System environment variables (export)
  2. .env file in the same directory
  3. Parent directory .env file
"""

import os
from pathlib import Path

import ksapi

# ── .env parser (zero dependencies) ──────────────────────────────────────


def _load_dotenv(path: Path) -> None:
    """Parse a .env file and inject into os.environ (existing vars are not overwritten)."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()


# Try loading .env files in priority order
_MODULE_DIR = Path(__file__).resolve().parent
for _candidate in (
    _MODULE_DIR / ".env",
    _MODULE_DIR.parent / ".env",
):
    _load_dotenv(_candidate)


# ── API Client ───────────────────────────────────────────────────────────


def build_client() -> ksapi.ApiClient:
    """Build a KS API client from environment variables."""
    base_url = os.environ.get("KS_BASE_URL", "https://api.knowledgestack.cn")
    api_key = os.environ["KS_API_KEY"]

    config = ksapi.Configuration(host=base_url)
    client = ksapi.ApiClient(config)
    client.set_default_header("Authorization", f"Bearer {api_key}")
    return client


client = build_client()
