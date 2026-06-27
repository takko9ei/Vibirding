"""Permissions — the write gate that sits inside the execution path.

read is always allowed; write triggers an approval callback. The callback is
INJECTABLE so it can be a CLI y/n/a prompt in scripts, or an automatic policy in
evals/self-checks — input() is never hard-wired into the execution path. The gate
also supports "remember allow for the rest of this turn" (architecture sec 6).

If no approver is wired in, writes fail closed (deny) — the same safe default the
S1 thin version had, so existing callers that do `Permissions()` are unaffected.

Contract (architecture section 6, signature locked from S1):
    permissions.check(tool_name, risk, input) -> "allow" | "deny"

The injected approver is richer than check()'s public return — it returns one of
"allow" | "deny" | "always" (always = allow this and every later write this turn).
"""

from __future__ import annotations

from typing import Callable

# An approver decides one write request: given (tool_name, risk, input) it returns
# "allow" (this one), "deny" (this one), or "always" (this one + all later writes).
Approver = Callable[[str, str, dict], str]


class Permissions:
    """Decides whether a tool call may execute, based on its risk level."""

    def __init__(self, approver: Approver | None = None) -> None:
        # No approver -> writes fail closed (deny). Scripts inject a y/n/a prompt;
        # evals/self-checks inject an automatic allow/deny/always policy.
        self._approver = approver
        # Set once the user answers "always": skip prompting for the rest of the turn.
        self._allow_all_writes = False

    def check(self, tool_name: str, risk: str, input: dict) -> str:
        # Read-only tools never mutate anything -> always allowed.
        if risk == "read":
            return "allow"

        # From here on it's a write (or any non-read risk -> treated as write).
        # "remember allow for the rest of this turn" short-circuits the prompt.
        if self._allow_all_writes:
            return "allow"

        # No approval mechanism -> fail closed (matches the S1 default).
        if self._approver is None:
            return "deny"

        # Ask the injected approver and map its richer answer to allow/deny.
        decision = self._approver(tool_name, risk, input)
        if decision == "always":
            self._allow_all_writes = True  # don't ask again this turn
            return "allow"
        if decision == "allow":
            return "allow"
        return "deny"  # "deny" or anything unexpected -> fail closed
