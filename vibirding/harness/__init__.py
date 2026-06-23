"""Harness: cross-cutting concerns around the agent loop.

S1 ships thin versions of three pieces — trace (observability), budget
(max_steps stop-guard) and permissions (read->allow). Full write-approval is
S4; token budget and tool error-tolerance are S5.
"""
