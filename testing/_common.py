"""
Shared setup for all test scripts.
Loads .env, builds the Kalshi client, and provides helpers.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────

def _load_dotenv(env_path: Path | None = None):
    """Minimal .env loader — no external dependency needed."""
    if env_path is None:
        env_path = Path(__file__).parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:  # don't override existing env
            os.environ[key] = value

_load_dotenv()


# ── Client factory ────────────────────────────────────────────────────────

DEFAULT_HOST = "https://api.elections.kalshi.com/trade-api/v2"


def make_client():
    """Build and return a configured KalshiClient, or exit with a clear error."""
    try:
        import kalshi_python
    except ImportError:
        print("ERROR: kalshi-python not installed.")
        print("  pip install kalshi-python")
        sys.exit(1)

    api_key_id = os.environ.get("KALSHI_API_KEY_ID", "")
    private_key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
    host = os.environ.get("KALSHI_HOST", DEFAULT_HOST)

    if not api_key_id or api_key_id == "your-api-key-id-here":
        print("ERROR: KALSHI_API_KEY_ID not set.  Edit testing/.env")
        sys.exit(1)
    if not private_key_path or private_key_path.startswith("/path/to"):
        print("ERROR: KALSHI_PRIVATE_KEY_PATH not set.  Edit testing/.env")
        sys.exit(1)

    key_file = Path(private_key_path).expanduser()
    if not key_file.is_file():
        print(f"ERROR: Private key file not found: {key_file}")
        sys.exit(1)

    config = kalshi_python.Configuration(host=host)
    config.api_key_id = api_key_id
    config.private_key_pem = key_file.read_text()

    client = kalshi_python.KalshiClient(config)
    print(f"  Connected to: {host}")
    print(f"  API key:      {api_key_id[:8]}...{api_key_id[-4:]}")
    return client


# ── Pretty helpers ────────────────────────────────────────────────────────

def pp(obj, label: str = ""):
    """Pretty-print any SDK object or dict, handling datetimes."""
    if label:
        print(f"\n{'─'*60}")
        print(f"  {label}")
        print(f"{'─'*60}")

    def _default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)

    if hasattr(obj, "to_dict"):
        data = obj.to_dict()
    elif hasattr(obj, "__dict__"):
        data = obj.__dict__
    else:
        data = obj

    try:
        print(json.dumps(data, indent=2, default=_default))
    except (TypeError, ValueError):
        from pprint import pprint
        pprint(data)


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")
