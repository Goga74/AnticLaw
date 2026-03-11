"""Telegram bot handlers — one per command + natural language fallback."""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# Max Telegram message length
MAX_MSG_LEN = 4000


def detect_intent(text: str) -> tuple[str, str]:
    """Auto-detect intent from natural language text.

    Returns:
        Tuple of (command, argument) where command is one of:
        "search", "code", "ask".
    """
    lower = text.lower().strip()

    # Russian + English search keywords
    search_patterns = [
        r"\bнайди\b", r"\bпоиск\b", r"\bищи\b",
        r"\bfind\b", r"\bsearch\b", r"\blookup\b",
    ]
    for pat in search_patterns:
        if re.search(pat, lower):
            return "search", text

    # Code/implement keywords
    code_patterns = [
        r"\bнапиши\b", r"\bреализуй\b", r"\bисправь\b", r"\bимплементируй\b",
        r"\bimplement\b", r"\bfix\b", r"\bwrite\b", r"\bcode\b", r"\brefactor\b",
    ]
    for pat in code_patterns:
        if re.search(pat, lower):
            return "code", text

    # Default: treat as question
    return "ask", text


def truncate_response(text: str, max_len: int = MAX_MSG_LEN) -> str:
    """Truncate text to fit Telegram message limits."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 20] + "\n\n... (truncated)"


def check_user_allowed(user_id: int, allowed_ids: list[int]) -> bool:
    """Check if user is in the whitelist. Empty list = allow all."""
    if not allowed_ids:
        return True
    return user_id in allowed_ids


def handle_search(query: str, home: Path) -> str:
    """Handle /search command."""
    if not query:
        return "Usage: /search <query>"

    from anticlaw.bot.runner import run_aw_command

    output = run_aw_command(["search", query], home)
    return truncate_response(output)


def handle_ask(question: str, home: Path) -> str:
    """Handle /ask command."""
    if not question:
        return "Usage: /ask <question>"

    from anticlaw.bot.runner import run_aw_command

    output = run_aw_command(["ask", question], home)
    return truncate_response(output)


def handle_note(text: str, home: Path) -> str:
    """Handle /note command — save insight to KB."""
    if not text:
        return "Usage: /note <text>"

    from anticlaw.bot.runner import run_aw_remember

    output = run_aw_remember(text, home)
    return output


def handle_code(task: str, home: Path, claude_path: str = "claude") -> str:
    """Handle /code command — run claude CLI in ACL_HOME context."""
    if not task:
        return "Usage: /code <task>"

    from anticlaw.bot.runner import is_claude_available, run_claude_command

    if not is_claude_available(claude_path):
        return f"Error: Claude CLI ('{claude_path}') not found. /code is disabled."

    output = run_claude_command(task, home, claude_path)
    return truncate_response(output)


def handle_cc(prompt: str, claude_path: str = "claude") -> str:
    """Handle /cc command — run Claude Code in PowerShell cwd."""
    if not prompt:
        return "Usage: /cc <prompt>"

    from anticlaw.bot.runner import is_claude_available, run_claude_raw

    if not is_claude_available(claude_path):
        return f"Error: Claude CLI ('{claude_path}') not found."

    output = run_claude_raw(prompt, claude_path)
    return truncate_response(output)


def handle_status(home: Path) -> str:
    """Handle /status command — health + daemon status."""
    from anticlaw.bot.runner import run_aw_command

    health = run_aw_command(["health"], home)
    daemon = run_aw_command(["daemon", "status"], home)
    return truncate_response(f"Health:\n{health}\n\nDaemon:\n{daemon}")


def handle_help() -> str:
    """Handle /help command."""
    return (
        "AnticLaw Bot Commands:\n\n"
        "/search <query> — search knowledge base\n"
        "/ask <question> — ask a question (LLM answer)\n"
        "/note <text> — save an insight/note\n"
        "/code <task> — Claude Code in KB context\n"
        "/cc <prompt> — Claude Code direct (PowerShell)\n"
        "/status — health + daemon status\n"
        "/help — show this message\n\n"
        "Or just type naturally — the bot will detect intent."
    )


def route_message(
    text: str,
    home: Path,
    claude_path: str = "claude",
) -> str:
    """Route a text message to the appropriate handler.

    Handles both /command and natural language input.
    """
    stripped = text.strip()

    # Command routing
    if stripped.startswith("/"):
        parts = stripped.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        # Strip @botname suffix from commands (e.g. /search@mybot)
        cmd = cmd.split("@")[0]

        match cmd:
            case "/search":
                return handle_search(arg, home)
            case "/ask":
                return handle_ask(arg, home)
            case "/note":
                return handle_note(arg, home)
            case "/code":
                return handle_code(arg, home, claude_path)
            case "/cc":
                return handle_cc(arg, claude_path)
            case "/status":
                return handle_status(home)
            case "/help" | "/start":
                return handle_help()
            case _:
                return f"Unknown command: {cmd}\nType /help for available commands."

    # Natural language fallback
    intent, arg = detect_intent(stripped)
    match intent:
        case "search":
            return handle_search(arg, home)
        case "code":
            return handle_code(arg, home, claude_path)
        case _:
            return handle_ask(arg, home)
