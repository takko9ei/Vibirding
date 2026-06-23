"""Project-wide configuration: paths and runtime constants.

Kept intentionally minimal for S1 — only the filesystem paths the trace writer
and the smoke-test script need. Model/API settings are left as comments and get
filled in at S2 when GeminiClient is wired up.
"""

from __future__ import annotations

from pathlib import Path

# vibirding/ package dir, then the repo root (the folder named "Vibirding").
PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent

# data/ is gitignored: holds the append-only log and the JSONL traces.
DATA_DIR = ROOT_DIR / "data"
TRACES_DIR = DATA_DIR / "traces"

# --- S2 (GeminiClient) will use these; not needed offline in S1 ---
# MODEL_NAME = "gemini-3.5-flash"
# GEMINI_API_KEY is read from the environment variable of the same name.
