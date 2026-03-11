"""Tests for anticlaw.bot.handlers — command routing and intent detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from anticlaw.bot.handlers import (
    check_user_allowed,
    detect_intent,
    handle_ask,
    handle_cc,
    handle_code,
    handle_help,
    handle_note,
    handle_search,
    handle_status,
    route_message,
    truncate_response,
)


class TestDetectIntent:
    def test_search_english(self):
        cmd, _ = detect_intent("find all auth discussions")
        assert cmd == "search"

    def test_search_russian(self):
        cmd, _ = detect_intent("найди обсуждение авторизации")
        assert cmd == "search"

    def test_search_keyword(self):
        cmd, _ = detect_intent("search for JWT tokens")
        assert cmd == "search"

    def test_code_english(self):
        cmd, _ = detect_intent("implement a new feature")
        assert cmd == "code"

    def test_code_fix(self):
        cmd, _ = detect_intent("fix the bug in auth module")
        assert cmd == "code"

    def test_code_russian(self):
        cmd, _ = detect_intent("напиши функцию для парсинга")
        assert cmd == "code"

    def test_code_write(self):
        cmd, _ = detect_intent("write a unit test for storage")
        assert cmd == "code"

    def test_ask_default(self):
        cmd, _ = detect_intent("what decisions did we make about auth?")
        assert cmd == "ask"

    def test_ask_plain(self):
        cmd, _ = detect_intent("how does authentication work?")
        assert cmd == "ask"

    def test_returns_original_text(self):
        _, arg = detect_intent("find all auth discussions")
        assert arg == "find all auth discussions"


class TestTruncateResponse:
    def test_short_text_unchanged(self):
        assert truncate_response("hello", 100) == "hello"

    def test_long_text_truncated(self):
        text = "a" * 5000
        result = truncate_response(text, 100)
        assert len(result) <= 100
        assert "truncated" in result

    def test_exact_limit(self):
        text = "a" * 4000
        assert truncate_response(text, 4000) == text


class TestCheckUserAllowed:
    def test_empty_whitelist_allows_all(self):
        assert check_user_allowed(12345, []) is True

    def test_user_in_whitelist(self):
        assert check_user_allowed(12345, [12345, 67890]) is True

    def test_user_not_in_whitelist(self):
        assert check_user_allowed(99999, [12345, 67890]) is False


class TestHandleSearch:
    def test_empty_query(self):
        result = handle_search("", Path("/tmp"))
        assert "Usage" in result

    @patch("anticlaw.bot.runner.run_aw_command", return_value="Found 3 results")
    def test_search_calls_aw(self, mock_run):
        result = handle_search("auth", Path("/tmp"))
        assert result == "Found 3 results"
        mock_run.assert_called_once_with(["search", "auth"], Path("/tmp"))


class TestHandleAsk:
    def test_empty_question(self):
        result = handle_ask("", Path("/tmp"))
        assert "Usage" in result

    @patch("anticlaw.bot.runner.run_aw_command", return_value="JWT is recommended")
    def test_ask_calls_aw(self, mock_run):
        result = handle_ask("what about auth?", Path("/tmp"))
        assert result == "JWT is recommended"
        mock_run.assert_called_once_with(["ask", "what about auth?"], Path("/tmp"))


class TestHandleNote:
    def test_empty_note(self):
        result = handle_note("", Path("/tmp"))
        assert "Usage" in result

    @patch("anticlaw.bot.runner.run_aw_remember", return_value="Saved: acl-123")
    def test_note_saves(self, mock_remember):
        result = handle_note("important decision", Path("/tmp"))
        assert "Saved" in result
        mock_remember.assert_called_once_with("important decision", Path("/tmp"))


class TestHandleCode:
    @patch("anticlaw.bot.runner.is_claude_available", return_value=False)
    def test_code_disabled_no_claude(self, mock_avail):
        result = handle_code("do something", Path("/tmp"))
        assert "not found" in result

    def test_empty_task(self):
        result = handle_code("", Path("/tmp"))
        assert "Usage" in result

    @patch("anticlaw.bot.runner.run_claude_command", return_value="Done!")
    @patch("anticlaw.bot.runner.is_claude_available", return_value=True)
    def test_code_calls_claude(self, mock_avail, mock_run):
        result = handle_code("write a test", Path("/tmp"))
        assert result == "Done!"
        mock_run.assert_called_once_with("write a test", Path("/tmp"), "claude")


class TestHandleCc:
    def test_empty_prompt(self):
        result = handle_cc("")
        assert "Usage" in result

    @patch("anticlaw.bot.runner.is_claude_available", return_value=False)
    def test_cc_disabled_no_claude(self, mock_avail):
        result = handle_cc("hello")
        assert "not found" in result

    @patch("anticlaw.bot.runner.run_claude_raw", return_value="Hello!")
    @patch("anticlaw.bot.runner.is_claude_available", return_value=True)
    def test_cc_calls_claude_raw(self, mock_avail, mock_run):
        result = handle_cc("say hello")
        assert result == "Hello!"
        mock_run.assert_called_once_with("say hello", "claude")


class TestHandleStatus:
    @patch("anticlaw.bot.runner.run_aw_command", side_effect=["All OK", "Daemon: running"])
    def test_status_combines_output(self, mock_run):
        result = handle_status(Path("/tmp"))
        assert "Health" in result
        assert "Daemon" in result
        assert mock_run.call_count == 2


class TestHandleHelp:
    def test_help_lists_commands(self):
        result = handle_help()
        assert "/search" in result
        assert "/ask" in result
        assert "/note" in result
        assert "/code" in result
        assert "/cc" in result
        assert "/status" in result


class TestRouteMessage:
    @patch("anticlaw.bot.handlers.handle_search", return_value="results")
    def test_route_search_command(self, mock_search):
        result = route_message("/search auth tokens", Path("/tmp"))
        assert result == "results"
        mock_search.assert_called_once_with("auth tokens", Path("/tmp"))

    @patch("anticlaw.bot.handlers.handle_ask", return_value="answer")
    def test_route_ask_command(self, mock_ask):
        result = route_message("/ask what about auth?", Path("/tmp"))
        assert result == "answer"
        mock_ask.assert_called_once_with("what about auth?", Path("/tmp"))

    @patch("anticlaw.bot.handlers.handle_note", return_value="saved")
    def test_route_note_command(self, mock_note):
        result = route_message("/note important thing", Path("/tmp"))
        assert result == "saved"
        mock_note.assert_called_once_with("important thing", Path("/tmp"))

    @patch("anticlaw.bot.handlers.handle_code", return_value="done")
    def test_route_code_command(self, mock_code):
        result = route_message("/code write test", Path("/tmp"))
        assert result == "done"
        mock_code.assert_called_once_with("write test", Path("/tmp"), "claude")

    @patch("anticlaw.bot.handlers.handle_cc", return_value="hi")
    def test_route_cc_command(self, mock_cc):
        result = route_message("/cc say hello", Path("/tmp"))
        assert result == "hi"
        mock_cc.assert_called_once_with("say hello", "claude")

    def test_route_help_command(self):
        result = route_message("/help", Path("/tmp"))
        assert "/search" in result

    def test_route_start_command(self):
        result = route_message("/start", Path("/tmp"))
        assert "/search" in result

    def test_route_unknown_command(self):
        result = route_message("/foo", Path("/tmp"))
        assert "Unknown command" in result

    @patch("anticlaw.bot.handlers.handle_ask", return_value="answer")
    def test_route_natural_language_ask(self, mock_ask):
        result = route_message("what decisions about auth?", Path("/tmp"))
        assert result == "answer"

    @patch("anticlaw.bot.handlers.handle_search", return_value="results")
    def test_route_natural_language_search(self, mock_search):
        result = route_message("find auth discussions", Path("/tmp"))
        assert result == "results"

    @patch("anticlaw.bot.handlers.handle_code", return_value="done")
    def test_route_natural_language_code(self, mock_code):
        result = route_message("implement auth module", Path("/tmp"))
        assert result == "done"

    @patch("anticlaw.bot.handlers.handle_search", return_value="results")
    def test_route_command_with_bot_suffix(self, mock_search):
        result = route_message("/search@anticlaw_bot query", Path("/tmp"))
        assert result == "results"
        mock_search.assert_called_once_with("query", Path("/tmp"))
