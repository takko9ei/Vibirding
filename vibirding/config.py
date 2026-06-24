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


def load_deepseek_api_key() -> str | None:
    """Return DEEPSEEK_API_KEY, loading the project-root .env first.

    We pass an explicit .env path instead of python-dotenv's find_dotenv() (which
    walks the call stack and breaks when launched from stdin/REPL). load_dotenv
    does not override an already-set env var, so a real environment variable still
    wins. Returns None if absent; the client decides what to do about that.
    """
    load_dotenv(ROOT_DIR / ".env")
    return os.environ.get("DEEPSEEK_API_KEY")


def load_api_key() -> str | None:
    """Return GEMINI_API_KEY — legacy; GeminiClient is kept as an alt provider."""
    load_dotenv(ROOT_DIR / ".env")
    return os.environ.get("GEMINI_API_KEY")
