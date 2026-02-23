"""Bidirectional LLM sync — file-as-interface pattern.

Send local chat content to cloud LLM APIs (Claude, ChatGPT, Gemini, Ollama)
and write responses back to the same Markdown file.

WARNING: Cloud API access (Claude, ChatGPT) requires SEPARATE paid API keys.
Web subscriptions (Claude Pro $20/mo, ChatGPT Plus $20/mo) do NOT provide API access.
Gemini has a generous free tier (15 RPM, 1M tokens/day).
Ollama is completely free (local inference).
"""
