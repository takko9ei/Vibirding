"""Project-wide configuration: paths, runtime model settings, and the API key.

S1 only needed the filesystem paths. S2 adds the Gemini runtime model name,
temperature, and a helper to read GEMINI_API_KEY from the project-root .env.
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

# --- Gemini runtime model (S2) ---
# gemini-flash-latest is a stable alias to the current flash model. We use it
# instead of the newest gemini-3.5-flash, which was returning persistent 503
# (server overload) and blocking verification.
MODEL_NAME = "gemini-flash-latest"  # runtime model used by GeminiClient
TEMPERATURE = 0  # deterministic output — we want stable structured extraction


def load_api_key() -> str | None:
    """Return GEMINI_API_KEY, loading the project-root .env first.

    We pass an explicit .env path instead of relying on python-dotenv's
    find_dotenv() (which walks the call stack and breaks when launched from
    stdin/REPL). load_dotenv does not override an already-set env var, so a real
    environment variable still takes precedence. Returns None if the key is
    absent; deciding what to do about that is the client's job.
    """
    load_dotenv(ROOT_DIR / ".env")
    return os.environ.get("GEMINI_API_KEY")
