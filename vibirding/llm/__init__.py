"""LLM clients — provider-neutral model adapters.

The runtime client is DeepSeekClient (openai SDK, OpenAI-compatible,
deepseek-v4-flash, manual function calling) in deepseek_client.py. GeminiClient
(client.py) is kept as an alternative provider, and MockClient is the offline
scripted stand-in. All return the exact same ModelResponse shape, so the loop
never notices which client it is talking to.
"""
