"""Project-wide configuration: paths, runtime model settings, and API keys.

The runtime model is DeepSeek, reached through its OpenAI-compatible endpoint via
the `openai` SDK. GeminiClient is retained as an alternative provider
implementation (architecture section 11); its key loader is kept below.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# vibirding/ package dir, then the repo root (the folder named "Vibirding").
PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent

# data/ is gitignored: holds the append-only log and the JSONL traces.
DATA_DIR = ROOT_DIR / "data"
TRACES_DIR = DATA_DIR / "traces"

# --- DeepSeek runtime model (OpenAI-compatible endpoint) ---
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-v4-flash"  # runtime model used by DeepSeekClient
TEMPERATURE = 0  # deterministic output — we want stable structured extraction

# --- eBird API (used by the range_check tool) ---
# A separate service from the runtime model: authoritative season/distribution
# data, queried over plain HTTP. See tools/range_check.py.
EBIRD_BASE_URL = "https://api.ebird.org/v2"
EBIRD_DIST_KM = 25  # search radius around the point, km (eBird max 50)
EBIRD_BACK_DAYS = 14  # look-back window, days (eBird range 1..30)
# Sent as the obs endpoint's `sppLocale` param (NOT `locale`, which obs endpoints
# ignore). "zh_SIM" -> Simplified Chinese common names; "zh" -> Traditional.
EBIRD_SPP_LOCALE = "zh_SIM"

# --- 懂鸟/hholove visual bird-ID API (used by the bird_id tool) ---
# Async two-step + polling; all requests POST to {BASE_URL}{PATH} as multipart
# (upload) / urlencoded form (poll). Auth via the `api_key` header. See
# tools/bird_id.py.
HHO_BASE_URL = "https://ai.open.hhodata.com/api/v2"
HHO_PATH = "/dongniao"
HHO_DID = "vibirding01"  # device id, 1..32 alphanumeric (a fixed value is fine)
HHO_CLASS = "B"  # recognition class: "B" = birds only
HHO_MAX_IMAGE_BYTES = 2 * 1024 * 1024  # API limit: <= 2 MB jpg
# Upload needs a long write/read timeout — overseas uploads exceed httpx's ~5s
# default and would raise WriteTimeout. Passed to httpx.Timeout(**...).
HHO_UPLOAD_TIMEOUT = {"connect": 10, "read": 60, "write": 60, "pool": 10}
HHO_RESULT_TIMEOUT_S = 30  # the poll request is small
HHO_POLL_MAX = 5  # max poll attempts before giving up (code 1001 = not ready)
HHO_POLL_INTERVAL_S = 2  # wait between polls


def load_deepseek_api_key() -> str | None:
    """Return DEEPSEEK_API_KEY, loading the project-root .env first.

    We pass an explicit .env path instead of python-dotenv's find_dotenv() (which
    walks the call stack and breaks when launched from stdin/REPL). load_dotenv
    does not override an already-set env var, so a real environment variable still
    wins. Returns None if absent; the client decides what to do about that.
    """
    load_dotenv(ROOT_DIR / ".env")
    return os.environ.get("DEEPSEEK_API_KEY")


def load_ebird_api_key() -> str | None:
    """Return EBIRD_API_KEY, loading the project-root .env first.

    Same loading discipline as load_deepseek_api_key (explicit .env path; a real
    environment variable still wins). Returns None if absent; the range_check tool
    decides what to do about that (it reports a clean failure).
    """
    load_dotenv(ROOT_DIR / ".env")
    return os.environ.get("EBIRD_API_KEY")


def load_hho_api_key() -> str | None:
    """Return HHO_API_KEY (懂鸟 visual bird-ID), loading the project-root .env first.

    Same loading discipline as the others (explicit .env path; a real environment
    variable still wins). Returns None if absent; the bird_id tool reports a clean
    failure rather than crashing.
    """
    load_dotenv(ROOT_DIR / ".env")
    return os.environ.get("HHO_API_KEY")


def load_api_key() -> str | None:
    """Return GEMINI_API_KEY — legacy; GeminiClient is kept as an alt provider."""
    load_dotenv(ROOT_DIR / ".env")
    return os.environ.get("GEMINI_API_KEY")
