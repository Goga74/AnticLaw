"""Tests for anticlaw.providers.llm.claude."""

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from anticlaw.providers.llm.base import Capability
from anticlaw.providers.llm.claude import ClaudeProvider, scrub_text


# --- Fixtures ---

SAMPLE_CONVERSATIONS = [
    {
        "uuid": "28d595a3-5db0-492d-a49a-af74f13de505",
        "name": "Auth Discussion",
        "created_at": "2025-02-18T14:30:00.000Z",
        "updated_at": "2025-02-20T09:15:00.000Z",
        "model": "claude-opus-4-6",
        "chat_messages": [
            {
                "sender": "human",
                "text": "How should we implement auth?",
                "created_at": "2025-02-18T14:30:00.000Z",
            },
            {
                "sender": "assistant",
                "text": "There are three main approaches...",
                "created_at": "2025-02-18T14:31:00.000Z",
            },
            {
                "sender": "human",
                "text": "Let's go with JWT.",
                "created_at": "2025-02-18T14:35:00.000Z",
            },
        ],
    },
    {
        "uuid": "aabbccdd-1234-5678-9012-abcdef012345",
        "name": "API Design",
        "created_at": "2025-02-19T10:00:00.000Z",
        "chat_messages": [
            {
                "sender": "human",
                "text": "What REST conventions should we follow?",
                "created_at": "2025-02-19T10:00:00.000Z",
            },
            {
                "sender": "assistant",
                "text": "Here are the best practices...",
                "created_at": "2025-02-19T10:01:00.000Z",
            },
        ],
    },
]

CONVERSATIONS_WITH_STRUCTURED_CONTENT = [
    {
        "uuid": "struct-1111",
        "name": "Structured Content",
        "created_at": "2025-02-20T10:00:00.000Z",
        "chat_messages": [
            {
                "sender": "human",
                "content": [
                    {"type": "text", "text": "Hello from structured content"}
                ],
                "created_at": "2025-02-20T10:00:00.000Z",
            },
            {
                "sender": "assistant",
                "content": [
                    {"type": "text", "text": "Part one."},
                    {"type": "text", "text": "Part two."},
                ],
                "created_at": "2025-02-20T10:01:00.000Z",
            },
        ],
    },
]

CONVERSATIONS_WITH_SECRETS = [
    {
        "uuid": "secret-0001",
        "name": "Secret chat",
        "created_at": "2025-02-18T14:30:00.000Z",
        "chat_messages": [
            {
                "sender": "human",
                "text": "My API key is sk-ant-abc123XYZ0987654321long_enough_key",
                "created_at": "2025-02-18T14:30:00.000Z",
            },
            {
                "sender": "assistant",
                "text": "Use Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def for auth",
                "created_at": "2025-02-18T14:31:00.000Z",
            },
        ],
    },
]

SAMPLE_PROJECT_MAPPING = {
    "28d595a3-5db0-492d-a49a-af74f13de505": "Project Alpha",
    "aabbccdd-1234-5678-9012-abcdef012345": "Project Beta",
}


def _make_export_zip(tmp_path: Path, conversations: list[dict]) -> Path:
    """Create a test Claude export ZIP with conversations.json."""
    zip_path = tmp_path / "claude-export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("conversations.json", json.dumps(conversations))
    return zip_path


def _make_mapping_file(tmp_path: Path, mapping: dict) -> Path:
    """Create a test project mapping JSON file."""
    path = tmp_path / "project_mapping.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return path


# --- Tests ---


class TestClaudeProviderInfo:
    def test_name(self):
        p = ClaudeProvider()
        assert p.name == "claude"

    def test_capabilities(self):
        p = ClaudeProvider()
        assert Capability.EXPORT_BULK in p.info.capabilities
        assert Capability.SCRAPE in p.info.capabilities

    def test_unsupported_methods(self):
        p = ClaudeProvider()
        with pytest.raises(NotImplementedError):
            p.export_chat("any-id")
        with pytest.raises(NotImplementedError):
            p.import_chat(None, None)
        with pytest.raises(NotImplementedError):
            p.sync(Path("."), "proj-1")


class TestParseExportZip:
    def test_basic_parse(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ClaudeProvider()

        chats = provider.parse_export_zip(zip_path)
        assert len(chats) == 2

    def test_conversation_fields(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ClaudeProvider()
        chats = provider.parse_export_zip(zip_path)

        chat = chats[0]
        assert chat.remote_id == "28d595a3-5db0-492d-a49a-af74f13de505"
        assert chat.title == "Auth Discussion"
        assert chat.provider == "claude"
        assert chat.model == "claude-opus-4-6"
        assert chat.created == datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc)

    def test_messages_parsed(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ClaudeProvider()
        chats = provider.parse_export_zip(zip_path)

        messages = chats[0].messages
        assert len(messages) == 3
        assert messages[0].role == "human"
        assert messages[0].content == "How should we implement auth?"
        assert messages[1].role == "assistant"
        assert messages[2].role == "human"
        assert messages[2].content == "Let's go with JWT."

    def test_message_timestamps(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ClaudeProvider()
        chats = provider.parse_export_zip(zip_path)

        msg = chats[0].messages[0]
        assert msg.timestamp == datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc)

    def test_structured_content(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, CONVERSATIONS_WITH_STRUCTURED_CONTENT)
        provider = ClaudeProvider()
        chats = provider.parse_export_zip(zip_path)

        assert len(chats) == 1
        messages = chats[0].messages
        assert messages[0].content == "Hello from structured content"
        assert messages[1].content == "Part one.\nPart two."

    def test_empty_export(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, [])
        provider = ClaudeProvider()
        chats = provider.parse_export_zip(zip_path)
        assert chats == []

    def test_missing_conversations_json(self, tmp_path: Path):
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("other.txt", "hello")

        provider = ClaudeProvider()
        with pytest.raises(FileNotFoundError, match="conversations.json"):
            provider.parse_export_zip(zip_path)

    def test_nested_conversations_json(self, tmp_path: Path):
        """conversations.json can be in a subdirectory."""
        zip_path = tmp_path / "nested.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("export/data/conversations.json", json.dumps(SAMPLE_CONVERSATIONS))

        provider = ClaudeProvider()
        chats = provider.parse_export_zip(zip_path)
        assert len(chats) == 2

    def test_malformed_conversation_skipped(self, tmp_path: Path):
        """A malformed conversation should be skipped, not crash the whole import."""
        conversations = [
            {"uuid": "good", "name": "Good", "created_at": "2025-02-18T14:30:00.000Z",
             "chat_messages": [{"sender": "human", "text": "hello"}]},
            {"broken": True},  # malformed
        ]
        zip_path = _make_export_zip(tmp_path, conversations)
        provider = ClaudeProvider()
        chats = provider.parse_export_zip(zip_path)
        # At least the good one should be parsed
        assert len(chats) >= 1


class TestScrubbing:
    def test_scrub_flag(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, CONVERSATIONS_WITH_SECRETS)
        provider = ClaudeProvider()
        chats = provider.parse_export_zip(zip_path, scrub=True)

        msg0 = chats[0].messages[0].content
        assert "sk-ant-" not in msg0
        assert "[REDACTED" in msg0

        msg1 = chats[0].messages[1].content
        assert "Bearer eyJ" not in msg1
        assert "[REDACTED" in msg1

    def test_no_scrub_by_default(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, CONVERSATIONS_WITH_SECRETS)
        provider = ClaudeProvider()
        chats = provider.parse_export_zip(zip_path, scrub=False)

        msg0 = chats[0].messages[0].content
        assert "sk-ant-" in msg0

    def test_scrub_api_key(self):
        assert "[REDACTED" in scrub_text("key: sk-abc1234567890abcdefghij")

    def test_scrub_github_token(self):
        assert "[REDACTED" in scrub_text("token ghp_aaaBBBcccDDDeeeFFFF111222333444556677")

    def test_scrub_aws_key(self):
        assert "[REDACTED" in scrub_text("aws key AKIAIOSFODNN7EXAMPLE")

    def test_scrub_private_key(self):
        result = scrub_text("-----BEGIN RSA PRIVATE KEY-----")
        assert "[REDACTED:private_key]" in result

    def test_scrub_connection_string(self):
        result = scrub_text("db: postgres://user:password@host:5432/db")
        assert "[REDACTED:connection_string]" in result

    def test_scrub_password_assignment(self):
        result = scrub_text('password="super_secret_pw_123"')
        assert "[REDACTED" in result

    def test_clean_text_unchanged(self):
        text = "This is normal text about authentication."
        assert scrub_text(text) == text


class TestProjectMapping:
    def test_load_mapping(self, tmp_path: Path):
        mapping_path = _make_mapping_file(tmp_path, SAMPLE_PROJECT_MAPPING)
        provider = ClaudeProvider()
        mapping = provider.load_project_mapping(mapping_path)

        assert mapping["28d595a3-5db0-492d-a49a-af74f13de505"] == "Project Alpha"
        assert mapping["aabbccdd-1234-5678-9012-abcdef012345"] == "Project Beta"

    def test_invalid_mapping_format(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text('["not", "a", "dict"]')

        provider = ClaudeProvider()
        with pytest.raises(ValueError, match="JSON object"):
            provider.load_project_mapping(path)
