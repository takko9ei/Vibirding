"""Log — the append-only JSONL observation log (the agent's memory).

This is principle 4 from docs/architecture.md: memory is an append-only file. The
observation log is just a JSONL where every line is one Observation; history is
never rewritten or deleted. Personal-scale data, so query() is a plain sequential
scan — no database (architecture section 11: "SQLite 替代 JSONL — 数据量大了再说").

Contract (architecture section 6):
    log.append(obs: Observation) -> None
    log.query(place=None, species=None, date_range=None) -> list[Observation]

The log path is injectable via the constructor (default = config.OBSERVATIONS_PATH)
so tools/scripts use the real file while tests point at a throwaway temp file —
no monkeypatching of config required.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import config
from ..schemas import Observation


class Log:
    """An append-only JSONL log of Observations, backed by a single file."""

    def __init__(self, path: Path | None = None) -> None:
        # Default to the project log; callers (tests) may inject a temp path.
        self.path = path or config.OBSERVATIONS_PATH

    def append(self, obs: Observation) -> None:
        """Append ONE Observation as a single JSON line. Strictly append-only.

        Always opens in "a" mode (never "w"), never touches existing lines. The
        parent dir is created on demand so a fresh checkout / temp path just works.
        ensure_ascii=False keeps Chinese names readable in the file.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(obs.model_dump(), ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def query(
        self,
        place: str | None = None,
        species: str | None = None,
        date_range: str | None = None,
    ) -> list[Observation]:
        """Read-only sequential scan, returning the Observations that match.

        A missing file is a legitimate "empty log" -> []. Each non-blank line is
        parsed back into an Observation and kept only if it passes every supplied
        filter (unsupplied filters are ignored).
        """
        if not self.path.exists():
            return []
        results: list[Observation] = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue  # tolerate blank lines
                obs = Observation.model_validate(json.loads(line))
                if _matches(obs, place, species, date_range):
                    results.append(obs)
        return results


def _matches(
    obs: Observation,
    place: str | None,
    species: str | None,
    date_range: str | None,
) -> bool:
    """Pure predicate: does this Observation satisfy all the given filters?

    place / species use substring containment (same behavior as the old fake
    read_log). If a filter is set but the field is None, it cannot match -> False.
    """
    if place is not None and (obs.place is None or place not in obs.place):
        return False
    if species is not None and (obs.species is None or species not in obs.species):
        return False
    return _in_date_range(obs.obs_date, date_range)


def _in_date_range(obs_date: str | None, date_range: str | None) -> bool:
    """Minimal "start..end" range check over ISO date strings.

    ISO dates (YYYY-MM-DD) compare correctly as plain strings, so we just do
    lexicographic comparison. No "..", or no filter at all, means "don't filter".
    A row with no obs_date is excluded only when a real date filter is active.
    """
    if date_range is None or ".." not in date_range:
        return True  # no / unsupported filter -> do not exclude
    start, _, end = date_range.partition("..")
    start, end = start.strip(), end.strip()
    if obs_date is None:
        return False  # filtering by date but this row has none
    if start and obs_date < start:
        return False
    if end and obs_date > end:
        return False
    return True
