"""System prompt for the agent.

S1 ships a MINIMAL placeholder: the MockClient ignores it entirely, so its only
job here is to make the message list realistic (a system turn followed by the
user's note). S2 fleshes it out for the real Gemini model — detailed tool-use
guidance, the Observation output format, when to call bird_id / read_log /
append_log, etc.
"""

from __future__ import annotations

# TODO(S2): expand with concrete tool-use rules and the Observation schema once
# GeminiClient actually reads this.
SYSTEM_PROMPT = (
    "你是一个观鸟速记助手。用户会丢给你一段随手记的、乱糟糟的观鸟笔记"
    "（有时附一张照片 URL）。你的任务是把它整理成一条结构化的观测记录，"
    "需要时调用工具（如查历史的 read_log）来核验地点/季节是否合理，"
    "最后给用户一段简短的总结。"
)
