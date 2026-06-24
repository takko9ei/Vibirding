"""MockClient — a scripted, offline stand-in for the real model.

It returns a preset list of ModelResponse objects, one per complete() call, in
order. It never touches the network and never imports any provider SDK. Because
its return shape is identical to the real DeepSeekClient, the loop can swap clients without
noticing — which is exactly what lets us debug the whole loop for free.

Contract (architecture section 6):
    complete(messages, tools=None) -> ModelResponse
"""

from __future__ import annotations

from ..schemas import ModelResponse


class MockClient:
    """Replays a fixed script of ModelResponses, one per complete() call."""

    def __init__(self, script: list[ModelResponse]) -> None:
        # Copy so the caller can't mutate our script mid-run.
        self._script = list(script)
        self._i = 0  # how many responses we've handed out so far

    def complete(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> ModelResponse:
        # messages/tools are accepted (to match the LLMClient contract) but
        # ignored — the responses are scripted in advance.
        if self._i >= len(self._script):
            # Fail loud: a too-short script (or a loop that won't terminate) is a
            # bug we want to see immediately, not paper over.
            raise RuntimeError(
                f"MockClient script exhausted after {self._i} call(s); "
                "the script is too short or the loop did not stop on end_turn."
            )
        resp = self._script[self._i]
        self._i += 1
        return resp
