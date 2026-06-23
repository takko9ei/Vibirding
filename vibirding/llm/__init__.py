"""LLM clients — provider-neutral model adapters.

S1 ships only MockClient (offline, scripted). The real GeminiClient
(google-genai, gemini-3.5-flash, manual function calling) arrives in S2 as
client.py and returns the exact same ModelResponse shape, so the loop never
notices which client it is talking to.
"""
