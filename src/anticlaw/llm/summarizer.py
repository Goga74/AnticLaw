"""Summarization via local Ollama LLM."""

from __future__ import annotations

import logging

from anticlaw.core.models import Chat
from anticlaw.llm.ollama_client import OllamaClient, OllamaNotAvailableError

log = logging.getLogger(__name__)

_CHAT_PROMPT = """\
Summarize the following LLM conversation in 2-3 concise sentences.
Focus on key decisions, conclusions, and actionable outcomes.
Do NOT include any preamble like "Here is a summary" — just output the summary.

Title: {title}

{messages}

Summary:"""

_PROJECT_PROMPT = """\
Summarize this project based on the chat summaries below.
Write 2-4 sentences covering the project's main goals, key decisions, and current state.
Do NOT include any preamble — just output the summary.

Project: {name}
Description: {description}

Chat summaries:
{chat_summaries}

Project summary:"""


def _chat_to_text(chat: Chat, max_chars: int = 6000) -> str:
    """Convert chat messages to a text block, truncated to max_chars."""
    parts = []
    for msg in chat.messages:
        role = msg.role.capitalize()
        parts.append(f"{role}: {msg.content}")
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[... truncated]"
    return text


def summarize_chat(
    chat: Chat,
    client: OllamaClient | None = None,
    config: dict | None = None,
) -> str:
    """Generate a 2-3 sentence summary of a chat conversation.

    Args:
        chat: Chat with messages loaded.
        client: OllamaClient instance (created from config if not provided).
        config: LLM config dict (used only if client is None).

    Returns:
        Summary string, or empty string if Ollama is unavailable.
    """
    if client is None:
        client = OllamaClient(config)

    if not chat.messages:
        return ""

    messages_text = _chat_to_text(chat)
    prompt = _CHAT_PROMPT.format(title=chat.title or "Untitled", messages=messages_text)

    try:
        return client.generate(prompt)
    except OllamaNotAvailableError:
        log.warning("Ollama not available — cannot summarize chat '%s'", chat.title)
        return ""


def summarize_project(
    name: str,
    description: str,
    chats: list[Chat],
    client: OllamaClient | None = None,
    config: dict | None = None,
) -> str:
    """Generate a project-level summary from its chat summaries.

    Args:
        name: Project name.
        description: Project description.
        chats: List of chats (only .summary used, messages not required).
        client: OllamaClient instance (created from config if not provided).
        config: LLM config dict (used only if client is None).

    Returns:
        Summary string, or empty string if Ollama is unavailable.
    """
    if client is None:
        client = OllamaClient(config)

    summaries = []
    for chat in chats:
        if chat.summary:
            summaries.append(f"- {chat.title}: {chat.summary}")
        elif chat.title:
            summaries.append(f"- {chat.title}")

    if not summaries:
        return ""

    chat_summaries = "\n".join(summaries[:30])  # cap at 30 chats
    prompt = _PROJECT_PROMPT.format(
        name=name,
        description=description or "(no description)",
        chat_summaries=chat_summaries,
    )

    try:
        return client.generate(prompt)
    except OllamaNotAvailableError:
        log.warning("Ollama not available — cannot summarize project '%s'", name)
        return ""
