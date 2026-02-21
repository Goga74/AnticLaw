"""Hook definitions and turn tracking for MCP integration."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# --- Turn tracking for AutoReminder ---

_THRESHOLDS = [10, 20, 30]
_MESSAGES = [
    (
        "\n\n---\nReminder: Consider saving important decisions or findings "
        "with aw_remember before your session ends."
    ),
    (
        "\n\n---\nWarning: You should save your context now. "
        "Call aw_remember to preserve decisions and findings."
    ),
    (
        "\n\n---\nSAVE REQUIRED: You have made many tool calls without saving. "
        "Call aw_remember immediately to preserve your work."
    ),
]


class TurnTracker:
    """Tracks tool call count and emits progressive reminders."""

    def __init__(self, thresholds: list[int] | None = None) -> None:
        self.count = 0
        self.thresholds = thresholds or list(_THRESHOLDS)

    def increment(self) -> str | None:
        """Increment the turn counter. Returns a reminder message at thresholds."""
        self.count += 1
        for i, threshold in enumerate(self.thresholds):
            if self.count == threshold:
                return _MESSAGES[i]
        return None

    def reset(self) -> None:
        """Reset the turn counter (called after aw_remember)."""
        self.count = 0


# --- Hook configuration generation ---


def generate_mcp_config(python_exe: str | None = None) -> dict:
    """Generate MCP server configuration for Claude Code / Cursor.

    Returns a dict suitable for merging into settings.json.
    """
    exe = python_exe or sys.executable
    return {
        "mcpServers": {
            "anticlaw": {
                "command": exe,
                "args": ["-m", "anticlaw.mcp"],
            }
        }
    }


def install_claude_code(python_exe: str | None = None) -> Path:
    """Write AnticLaw MCP config into Claude Code settings.

    Merges into ~/.claude/settings.json, preserving existing config.
    Returns the path to settings.json.
    """
    settings_path = Path.home() / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("Failed to read existing settings.json, starting fresh")

    mcp_config = generate_mcp_config(python_exe)
    servers = existing.get("mcpServers", {})
    servers.update(mcp_config["mcpServers"])
    existing["mcpServers"] = servers

    settings_path.write_text(
        json.dumps(existing, indent=2), encoding="utf-8"
    )
    return settings_path


def install_cursor(python_exe: str | None = None) -> Path:
    """Write AnticLaw MCP config for Cursor.

    Writes to ~/.cursor/mcp.json, preserving existing config.
    Returns the path to mcp.json.
    """
    mcp_path = Path.home() / ".cursor" / "mcp.json"
    mcp_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if mcp_path.exists():
        try:
            existing = json.loads(mcp_path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("Failed to read existing mcp.json, starting fresh")

    mcp_config = generate_mcp_config(python_exe)
    servers = existing.get("mcpServers", {})
    servers.update(mcp_config["mcpServers"])
    existing["mcpServers"] = servers

    mcp_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return mcp_path
