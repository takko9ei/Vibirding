"""Budget — the loop's stop-guard.

S1 shipped a THIN version (max_steps only). S6 grows it into the full version:
besides the step cap it now tracks a token budget, fed one model call at a time
via observe(), and reports a richer stop reason. The locked contract
(tick / stop_reason) does NOT change shape — observe() is a new method that only
adds depth.

Contract (architecture section 6):
    budget.tick() -> bool              # may the loop run one more step?
    budget.stop_reason() -> str        # "max_steps" | "max_tokens" | None
    budget.observe(usage) -> None      # S6: loop feeds each model call's usage here

Graceful shutdown is the loop's job using these methods only: when tick() returns
False the loop emits a budget_stop trace line and returns cleanly — it never cuts
off a model response mid-flight, because tick() is checked BEFORE the next call.
"""

from __future__ import annotations


class Budget:
    """Counts loop steps AND accumulated tokens; stops the loop when either caps."""

    def __init__(self, max_steps: int, max_tokens: int | None = None) -> None:
        self.max_steps = max_steps
        self.max_tokens = max_tokens  # None => no token cap (back-compatible default)
        self.steps_used = 0
        self.tokens_used = 0
        self._stop_reason: str | None = None

    def observe(self, usage: dict | None) -> None:
        """Accumulate one model call's tokens from its normalized usage.

        usage is the internal normalized shape {input_tokens, output_tokens}
        (DeepSeekClient maps OpenAI's prompt/completion tokens into it; MockClient
        fills it directly). We sum input+output; across turns the re-sent context
        gets counted again — a deliberate, conservative over-estimate that is fine
        for a stop-guard. A missing/empty usage simply adds nothing.
        """
        if not usage:
            return
        self.tokens_used += (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)

    def tick(self) -> bool:
        """May the loop make one more model call? Record why once a cap is hit.

        Checked BEFORE the next call, so we stop on the *cumulative* total so far
        and never interrupt an in-flight response.
        """
        if self.max_tokens is not None and self.tokens_used >= self.max_tokens:
            self._stop_reason = "max_tokens"
            return False
        if self.steps_used >= self.max_steps:
            self._stop_reason = "max_steps"
            return False
        self.steps_used += 1
        return True

    def stop_reason(self) -> str | None:
        """Why the loop stopped on budget, or None if it never hit a cap."""
        return self._stop_reason
