"""Permissions — the write gate that sits inside the execution path.

S1 ships a THIN version: read is auto-allowed, and everything else fails closed
(deny), because no approval mechanism exists yet. S1 registers only read tools,
so this gate is never actually exercised — but it locks the contract and keeps a
safe default.

S4 fills in the real behavior: a write-approval callback (CLI y/n, auto-policy
for eval/mock) plus "remember allow for the rest of this turn". The check()
signature below does not change.

Contract (architecture section 6):
    permissions.check(tool_name, risk, input) -> "allow" | "deny"
"""

from __future__ import annotations


class Permissions:
    """Decides whether a tool call may execute, based on its risk level."""

    def check(self, tool_name: str, risk: str, input: dict) -> str:
        # Read-only tools never mutate anything -> always allowed.
        if risk == "read":
            return "allow"
        # Write (or any unknown risk): fail closed. There is no approval path in
        # S1; S4 replaces this branch with a real y/n / auto-policy approval.
        return "deny"
