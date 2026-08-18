"""Package entry point so `python -m vibirding ...` runs the CLI.

Keeps the actual logic in cli.py; this module just forwards to it.
"""

from __future__ import annotations

from vibirding.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
