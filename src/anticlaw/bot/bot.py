"""Main Telegram bot loop using python-telegram-bot (long polling)."""

from __future__ import annotations

import logging
from pathlib import Path

from anticlaw.bot.handlers import check_user_allowed, route_message

log = logging.getLogger(__name__)


async def _handle_message(update, context) -> None:
    """Handle incoming text messages."""
    bot_config = context.bot_data.get("bot_config", {})
    home = Path(bot_config.get("home", "~/anticlaw")).expanduser().resolve()
    allowed_ids = bot_config.get("allowed_user_ids", [])
    claude_path = bot_config.get("claude_code_path", "claude")

    user = update.effective_user
    if not user or not check_user_allowed(user.id, allowed_ids):
        uname = user.username if user else "?"
        uid = user.id if user else "?"
        log.warning("Unauthorized user: %s (id=%s)", uname, uid)
        await update.message.reply_text("Access denied. Your user ID is not in the whitelist.")
        return

    text = update.message.text
    if not text:
        return

    log.info("Message from %s: %s", user.username or user.id, text[:80])

    # Send "typing" indicator
    await update.message.chat.send_action("typing")

    response = route_message(text, home, claude_path)
    await update.message.reply_text(response)


def start_bot(
    token: str,
    home: Path,
    allowed_user_ids: list[int] | None = None,
    claude_code_path: str = "claude",
) -> None:
    """Start the Telegram bot with long polling (blocking).

    Args:
        token: Telegram Bot API token.
        home: ACL_HOME path.
        allowed_user_ids: Whitelist of Telegram user IDs. Empty/None = allow all.
        claude_code_path: Path to claude CLI executable.
    """
    try:
        from telegram import Update
        from telegram.ext import ApplicationBuilder, MessageHandler, filters
    except ImportError as e:
        raise RuntimeError(
            "python-telegram-bot is not installed. "
            "Install with: pip install 'anticlaw[bot]'"
        ) from e

    bot_config = {
        "home": str(home),
        "allowed_user_ids": allowed_user_ids or [],
        "claude_code_path": claude_code_path,
    }

    app = ApplicationBuilder().token(token).build()
    app.bot_data["bot_config"] = bot_config

    # Handle all text messages (commands + natural language)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))

    # Handle commands explicitly
    from telegram.ext import CommandHandler

    async def _cmd_handler(update, context):
        """Re-route commands through the unified handler."""
        await _handle_message(update, context)

    for cmd_name in ["search", "ask", "note", "code", "cc", "status", "help", "start"]:
        app.add_handler(CommandHandler(cmd_name, _cmd_handler))

    log.info("Starting bot polling (home=%s)...", home)
    app.run_polling(allowed_updates=[Update.MESSAGE], drop_pending_updates=True)
