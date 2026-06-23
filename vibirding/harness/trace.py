"""TraceWriter — structured, append-only observability for the loop.

Every loop step produces one TraceEvent. The writer does two things with it:
  1. prints a one-line human-readable summary to the console, and
  2. appends the event as one JSON line to data/traces/<run_id>.jsonl.

This satisfies both "one trace line per step" (architecture section 4/5) and the
S1 acceptance criterion "trace prints every step".
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..config import TRACES_DIR
from ..schemas import TraceEvent


def _new_run_id() -> str:
    """A run id unique to the second + microseconds, e.g. run_20260621_080000_123456."""
    return "run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")


class TraceWriter:
    """Writes TraceEvents to console and to a per-run JSONL file."""

    def __init__(
        self,
        run_id: str | None = None,
        traces_dir: Path = TRACES_DIR,
        to_console: bool = True,
    ) -> None:
        self.run_id = run_id or _new_run_id()
        self.to_console = to_console
        # Ensure the output dir exists here (config only declares paths).
        traces_dir.mkdir(parents=True, exist_ok=True)
        self.path = traces_dir / f"{self.run_id}.jsonl"

    def emit(self, event: TraceEvent) -> None:
        """Record one step: print a human line, then append one JSON line."""
        if self.to_console:
            print(f"step {event.step:>2} | {event.kind:<12} | {event.summary}")
        # ensure_ascii=False keeps Chinese readable inside the JSONL file.
        line = json.dumps(event.model_dump(), ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
