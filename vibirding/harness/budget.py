"""Budget — the loop's stop-guard.

S1 ships a THIN version: only a max_steps cap, just enough to keep the
model->tool->model loop from running forever. Token budgeting and richer stop
reasons are S5; the contract (tick / stop_reason) is locked now and only gains
depth later — it does not change shape.

Contract (architecture section 6):
    budget.tick() -> bool          # may the loop run one more step?
    budget.stop_reason() -> str    # "max_steps" | "max_tokens" | None
"""

from __future__ import annotations


class Budget:
    """Counts loop steps and stops the loop once max_steps is reached."""

    def __init__(self, max_steps: int) -> None:
        self.max_steps = max_steps
        self.steps_used = 0
        self._stop_reason: str | None = None

    def tick(self) -> bool:
        """Consume one step. Return False (and record why) once the cap is hit."""
        if self.steps_used >= self.max_steps:
            self._stop_reason = "max_steps"
            return False
        self.steps_used += 1
        return True

    def stop_reason(self) -> str | None:
        """Why the loop stopped on budget, or None if it never hit the cap."""
        return self._stop_reason
