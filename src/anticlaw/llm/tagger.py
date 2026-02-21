"""Auto-tagging and categorization via local Ollama LLM."""

from __future__ import annotations

import logging
import re

from anticlaw.core.models import Chat
from anticlaw.llm.ollama_client import OllamaClient, OllamaNotAvailable

log = logging.getLogger(__name__)

_TAG_PROMPT = """\
Analyze the following LLM conversation and suggest 3-7 relevant tags.
Tags should be lowercase, single words or hyphenated terms (e.g. "auth", "jwt", "error-handling").
Output ONLY the tags as a comma-separated list, nothing else.

Title: {title}

{messages}

Tags:"""

_CATEGORIZE_PROMPT = """\
You are classifying LLM chat conversations into project categories.
Given the chat content below, suggest the most appropriate project name.
The project name should be a short, descriptive, lowercase-hyphenated identifier
(e.g. "api-development", "auth-system", "database-design").
Output ONLY the project name, nothing else.

Available projects: {projects}

Title: {title}

{messages}

Suggested project:"""


def _chat_to_text(chat: Chat, max_chars: int = 4000) -> str:
    """Convert chat messages to a text block, truncated to max_chars."""
    parts = []
    for msg in chat.messages:
        role = msg.role.capitalize()
        parts.append(f"{role}: {msg.content}")
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[... truncated]"
    return text


def _parse_tags(raw: str) -> list[str]:
    """Parse LLM output into a clean tag list."""
    # Strip any quotes, brackets, or bullet points
    raw = raw.strip().strip("[]").strip()
    # Split on commas, newlines, or whitespace-separated items
    parts = re.split(r"[,\n]+", raw)
    tags = []
    for part in parts:
        tag = part.strip().strip("-•*").strip().lower()
        # Remove quotes
        tag = tag.strip("'\"")
        # Only keep valid tag-like strings
        if tag and re.match(r"^[a-z0-9][a-z0-9_-]*$", tag) and len(tag) <= 30:
            tags.append(tag)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique[:10]  # cap at 10


def auto_tag(
    chat: Chat,
    client: OllamaClient | None = None,
    config: dict | None = None,
) -> list[str]:
    """Suggest tags for a chat based on its content.

    Args:
        chat: Chat with messages loaded.
        client: OllamaClient instance (created from config if not provided).
        config: LLM config dict (used only if client is None).

    Returns:
        List of suggested tag strings, or empty list if Ollama unavailable.
    """
    if client is None:
        client = OllamaClient(config)

    if not chat.messages:
        return []

    messages_text = _chat_to_text(chat)
    prompt = _TAG_PROMPT.format(title=chat.title or "Untitled", messages=messages_text)

    try:
        raw = client.generate(prompt)
        return _parse_tags(raw)
    except OllamaNotAvailable:
        log.warning("Ollama not available — cannot auto-tag chat '%s'", chat.title)
        return []


def auto_categorize(
    chat: Chat,
    existing_projects: list[str] | None = None,
    client: OllamaClient | None = None,
    config: dict | None = None,
) -> str:
    """Suggest a project name for an unclassified chat.

    Args:
        chat: Chat with messages loaded.
        existing_projects: List of existing project names to prefer.
        client: OllamaClient instance (created from config if not provided).
        config: LLM config dict (used only if client is None).

    Returns:
        Suggested project name, or empty string if Ollama unavailable.
    """
    if client is None:
        client = OllamaClient(config)

    if not chat.messages:
        return ""

    projects_str = ", ".join(existing_projects) if existing_projects else "(none yet)"
    messages_text = _chat_to_text(chat)
    prompt = _CATEGORIZE_PROMPT.format(
        title=chat.title or "Untitled",
        messages=messages_text,
        projects=projects_str,
    )

    try:
        raw = client.generate(prompt)
        # Clean up the response — take just the first line, lowercase, strip
        suggestion = raw.strip().split("\n")[0].strip().lower()
        # Remove quotes and extra punctuation
        suggestion = suggestion.strip("'\".")
        return suggestion
    except OllamaNotAvailable:
        log.warning("Ollama not available — cannot categorize chat '%s'", chat.title)
        return ""
