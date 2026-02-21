"""Q&A over knowledge base via local Ollama LLM."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from anticlaw.core.meta_db import MetaDB, SearchResult
from anticlaw.core.search import search
from anticlaw.llm.ollama_client import OllamaClient, OllamaNotAvailable

log = logging.getLogger(__name__)

_QA_PROMPT = """\
Answer the following question based ONLY on the provided context from a knowledge base.
If the context doesn't contain enough information, say so honestly.
Include references to specific chats when relevant (use their titles).

Question: {question}

Context:
{context}

Answer:"""


@dataclass
class QAResult:
    """Result of a Q&A query."""

    answer: str
    sources: list[SearchResult] = field(default_factory=list)
    error: str = ""


def ask(
    question: str,
    home: Path,
    client: OllamaClient | None = None,
    config: dict | None = None,
    max_context_chats: int = 5,
    max_context_chars: int = 6000,
) -> QAResult:
    """Answer a question by searching the knowledge base and sending context to LLM.

    Args:
        question: The user's question.
        home: ACL_HOME path.
        client: OllamaClient instance (created from config if not provided).
        config: LLM config dict (used only if client is None).
        max_context_chats: Maximum number of chats to include as context.
        max_context_chars: Maximum total characters in context.

    Returns:
        QAResult with answer text and source references.
    """
    if client is None:
        client = OllamaClient(config)

    # Search for relevant chats
    db_path = home / ".acl" / "meta.db"
    if not db_path.exists():
        return QAResult(answer="", error="No metadata database found. Run 'aw reindex' first.")

    db = MetaDB(db_path)
    try:
        results = search(db, question, max_results=max_context_chats)
    finally:
        db.close()

    if not results:
        return QAResult(answer="No relevant chats found for your question.", sources=[])

    # Build context from search results
    context_parts = []
    total_chars = 0
    used_results = []

    for i, r in enumerate(results):
        entry = f"[Chat: {r.title}]\n{r.snippet}"
        if i > 0 and total_chars + len(entry) > max_context_chars:
            break  # always include at least the first result
        context_parts.append(entry)
        total_chars += len(entry)
        used_results.append(r)

    context = "\n\n---\n\n".join(context_parts)
    prompt = _QA_PROMPT.format(question=question, context=context)

    try:
        answer = client.generate(prompt)
        return QAResult(answer=answer, sources=used_results)
    except OllamaNotAvailable:
        log.warning("Ollama not available — cannot answer question")
        return QAResult(
            answer="",
            sources=used_results,
            error="Ollama is not running. Start it with 'ollama serve'.",
        )
