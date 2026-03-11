"""Entry point for python -m anticlaw.bot (background mode)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="AnticLaw Telegram bot")
    parser.add_argument("--token", required=True, help="Telegram bot token")
    parser.add_argument("--home", required=True, help="ACL_HOME path")
    parser.add_argument("--allowed-ids", default="", help="Comma-separated user IDs")
    parser.add_argument("--claude-path", default="claude", help="Path to claude CLI")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    allowed_ids = [int(x) for x in args.allowed_ids.split(",") if x.strip()]

    from anticlaw.bot.bot import start_bot

    start_bot(
        token=args.token,
        home=Path(args.home),
        allowed_user_ids=allowed_ids,
        claude_code_path=args.claude_path,
    )


if __name__ == "__main__":
    main()
