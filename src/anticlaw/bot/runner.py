"""Subprocess wrapper for aw CLI and claude CLI."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 120


def run_aw_command(args: list[str], home: Path, timeout: int = _TIMEOUT_SECONDS) -> str:
    """Run an aw CLI command and return its output.

    Args:
        args: Command arguments (e.g. ["search", "query"]).
        home: ACL_HOME path (passed via env).
        timeout: Timeout in seconds.

    Returns:
        Combined stdout+stderr output, trimmed.
    """
    cmd = ["aw", *args]
    env_override = {"ACL_HOME": str(home)}

    log.debug("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**_get_env(), **env_override},
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr.strip():
            output = f"{output}\n{result.stderr.strip()}".strip()
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s."
    except FileNotFoundError:
        return "Error: 'aw' CLI not found in PATH."
    except Exception as e:
        return f"Error running command: {e}"


def run_claude_command(
    task: str,
    home: Path,
    claude_path: str = "claude",
    timeout: int = _TIMEOUT_SECONDS,
) -> str:
    """Run claude CLI with --print flag and return output.

    Args:
        task: The task/prompt to send to Claude.
        home: Working directory for the command.
        claude_path: Path to claude CLI executable.
        timeout: Timeout in seconds.

    Returns:
        Claude CLI output, trimmed.
    """
    cmd = [claude_path, "--print", "--dangerously-skip-permissions", task]

    log.debug("Running claude: %s", task[:80])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(home),
            env=_get_env(),
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr.strip():
            output = f"{output}\n{result.stderr.strip()}".strip()
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Claude command timed out after {timeout}s."
    except FileNotFoundError:
        return f"Error: '{claude_path}' CLI not found in PATH."
    except Exception as e:
        return f"Error running claude: {e}"


def run_claude_raw(
    prompt: str,
    claude_path: str = "claude",
    timeout: int = _TIMEOUT_SECONDS,
) -> str:
    """Run claude CLI with --print flag in default working directory.

    Unlike run_claude_command, this does NOT set cwd to ACL_HOME —
    it runs in whatever directory the bot process was started from.
    """
    cmd = [claude_path, "--print", "--dangerously-skip-permissions", prompt]

    log.debug("Running claude raw: %s", prompt[:80])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_get_env(),
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr.strip():
            output = f"{output}\n{result.stderr.strip()}".strip()
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Claude command timed out after {timeout}s."
    except FileNotFoundError:
        return f"Error: '{claude_path}' CLI not found in PATH."
    except Exception as e:
        return f"Error running claude: {e}"


def is_claude_available(claude_path: str = "claude") -> bool:
    """Check if claude CLI is available in PATH."""
    try:
        result = subprocess.run(
            [claude_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False


def run_aw_remember(
    content: str,
    home: Path,
    category: str = "fact",
    tags: list[str] | None = None,
) -> str:
    """Save an insight via aw CLI (calls MCP remember internally).

    Uses the storage layer directly to avoid needing MCP running.
    """
    from anticlaw.mcp.server import remember_impl

    try:
        result = remember_impl(home, content, category, "medium", tags, "")
        return f"Saved: {result.get('id', 'unknown')}"
    except Exception as e:
        return f"Error saving note: {e}"


def _get_env() -> dict[str, str]:
    """Get current environment as a dict."""
    import os
    return dict(os.environ)
