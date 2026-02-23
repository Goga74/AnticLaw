"""Tests for anticlaw.providers.llm.gemini."""

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from anticlaw.providers.llm.base import Capability
from anticlaw.providers.llm.gemini import GeminiProvider


# --- Fixtures: Gemini Takeout structure ---
# Each conversation is a folder with conversation.json inside
# Takeout/Gemini Apps/Conversations/<folder>/conversation.json

SAMPLE_CONVERSATION_1 = {
    "id": "gemini-conv-001",
    "title": "Auth Discussion",
    "create_time": "2025-02-18T14:30:00.000Z",
    "update_time": "2025-02-20T09:05:00.000Z",
    "model": "gemini-pro",
    "messages": [
        {
            "role": "user",
            "text": "How should we implement auth?",
            "create_time": "2025-02-18T14:30:00.000Z",
        },
        {
            "role": "model",
            "text": "There are three main approaches...",
            "create_time": "2025-02-18T14:31:00.000Z",
        },
        {
            "role": "user",
            "text": "Let's go with JWT.",
            "create_time": "2025-02-18T14:35:00.000Z",
        },
    ],
}

SAMPLE_CONVERSATION_2 = {
    "id": "gemini-conv-002",
    "title": "API Design",
    "create_time": "2025-02-19T10:00:00.000Z",
    "update_time": "2025-02-19T10:00:00.000Z",
    "model": "gemini-flash",
    "messages": [
        {
            "role": "user",
            "text": "What REST conventions should we follow?",
            "create_time": "2025-02-19T10:00:00.000Z",
        },
        {
            "role": "model",
            "text": "Here are the best practices...",
            "create_time": "2025-02-19T10:01:00.000Z",
        },
    ],
}

CONVERSATION_WITH_SYSTEM = {
    "id": "gemini-sys-001",
    "title": "With System Message",
    "create_time": "2025-02-19T10:00:00.000Z",
    "messages": [
        {
            "role": "system",
            "text": "You are a helpful assistant.",
            "create_time": "2025-02-19T10:00:00.000Z",
        },
        {
            "role": "user",
            "text": "Hello",
            "create_time": "2025-02-19T10:00:10.000Z",
        },
        {
            "role": "model",
            "text": "Hi there!",
            "create_time": "2025-02-19T10:00:20.000Z",
        },
    ],
}

CONVERSATION_WITH_SECRETS = {
    "id": "gemini-secret-001",
    "title": "Secret Chat",
    "create_time": "2025-02-18T14:30:00.000Z",
    "messages": [
        {
            "role": "user",
            "text": "My API key is sk-ant-abc123XYZ0987654321long_enough_key",
            "create_time": "2025-02-18T14:30:00.000Z",
        },
        {
            "role": "model",
            "text": "Use Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def for auth",
            "create_time": "2025-02-18T14:31:00.000Z",
        },
    ],
}

CONVERSATION_UNIX_TIMESTAMPS = {
    "id": "gemini-unix-001",
    "title": "Unix Times",
    "create_time": 1739889000.0,
    "update_time": 1740042300.0,
    "messages": [
        {
            "role": "user",
            "text": "Hello",
            "create_time": 1739889000.0,
        },
        {
            "role": "model",
            "text": "Hi!",
            "create_time": 1739889060.0,
        },
    ],
}

CONVERSATION_CONTENT_PARTS = {
    "id": "gemini-parts-001",
    "title": "Content Parts",
    "create_time": "2025-02-19T10:00:00.000Z",
    "messages": [
        {
            "role": "user",
            "content": [{"text": "Part one."}, {"text": "Part two."}],
            "create_time": "2025-02-19T10:00:00.000Z",
        },
        {
            "role": "model",
            "parts": [{"text": "Response part A."}, {"text": "Response part B."}],
            "create_time": "2025-02-19T10:01:00.000Z",
        },
    ],
}

CONVERSATION_CONTENT_STRING = {
    "id": "gemini-str-001",
    "title": "Content String",
    "create_time": "2025-02-19T10:00:00.000Z",
    "messages": [
        {
            "role": "user",
            "content": "Simple string content",
            "create_time": "2025-02-19T10:00:00.000Z",
        },
        {
            "role": "model",
            "content": "Simple response",
            "create_time": "2025-02-19T10:01:00.000Z",
        },
    ],
}

CONVERSATION_CHUNKED_PROMPT = {
    "id": "gemini-studio-001",
    "title": "AI Studio Chat",
    "create_time": "2025-02-19T10:00:00.000Z",
    "chunkedPrompt": {
        "chunks": [
            {
                "role": "user",
                "text": "Hello from AI Studio",
                "create_time": "2025-02-19T10:00:00.000Z",
            },
            {
                "role": "model",
                "text": "Hello! How can I help?",
                "create_time": "2025-02-19T10:01:00.000Z",
            },
        ],
    },
}

CONVERSATION_MODEL_IN_MESSAGE = {
    "id": "gemini-model-msg-001",
    "title": "Model in Message",
    "create_time": "2025-02-19T10:00:00.000Z",
    "messages": [
        {
            "role": "user",
            "text": "Hello",
            "create_time": "2025-02-19T10:00:00.000Z",
        },
        {
            "role": "model",
            "text": "Hi!",
            "model": "gemini-1.5-pro",
            "create_time": "2025-02-19T10:01:00.000Z",
        },
    ],
}


def _make_takeout_zip(
    tmp_path: Path,
    conversations: list[tuple[str, dict]],
    base_dir: str = "Takeout/Gemini Apps/Conversations",
) -> Path:
    """Create a test Google Takeout ZIP with Gemini conversations.

    Args:
        tmp_path: Temp directory for the ZIP.
        conversations: List of (folder_name, conversation_dict) tuples.
        base_dir: Base directory path inside the ZIP.

    Returns:
        Path to the created ZIP file.
    """
    zip_path = tmp_path / "gemini-takeout.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for folder_name, conv_data in conversations:
            entry = f"{base_dir}/{folder_name}/conversation.json"
            zf.writestr(entry, json.dumps(conv_data))
    return zip_path


def _make_takeout_dir(
    tmp_path: Path,
    conversations: list[tuple[str, dict]],
) -> Path:
    """Create an extracted Takeout directory with Gemini conversations."""
    base = tmp_path / "takeout_dir" / "Gemini Apps" / "Conversations"
    base.mkdir(parents=True)
    for folder_name, conv_data in conversations:
        conv_dir = base / folder_name
        conv_dir.mkdir()
        (conv_dir / "conversation.json").write_text(json.dumps(conv_data), encoding="utf-8")
    return tmp_path / "takeout_dir"


# --- Tests ---


class TestGeminiProviderInfo:
    def test_name(self):
        p = GeminiProvider()
        assert p.name == "gemini"

    def test_display_name(self):
        p = GeminiProvider()
        assert p.info.display_name == "Gemini"

    def test_capabilities(self):
        p = GeminiProvider()
        assert Capability.EXPORT_BULK in p.info.capabilities

    def test_auth_returns_true(self):
        p = GeminiProvider()
        assert p.auth({}) is True

    def test_unsupported_methods(self):
        p = GeminiProvider()
        with pytest.raises(NotImplementedError):
            p.export_chat("any-id")
        with pytest.raises(NotImplementedError):
            p.import_chat(None, None)
        with pytest.raises(NotImplementedError):
            p.sync(Path("."), "proj-1")
        with pytest.raises(NotImplementedError):
            p.export_all(Path("."))

    def test_list_projects_empty(self):
        p = GeminiProvider()
        assert p.list_projects() == []

    def test_list_chats_empty(self):
        p = GeminiProvider()
        assert p.list_chats() == []


class TestParseTakeoutZip:
    def test_basic_parse(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-18_auth-discussion", SAMPLE_CONVERSATION_1),
            ("2025-02-19_api-design", SAMPLE_CONVERSATION_2),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)
        assert len(chats) == 2

    def test_conversation_fields(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-18_auth-discussion", SAMPLE_CONVERSATION_1),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)

        chat = chats[0]
        assert chat.remote_id == "gemini-conv-001"
        assert chat.title == "Auth Discussion"
        assert chat.provider == "gemini"
        assert chat.model == "gemini-pro"
        assert chat.created == datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc)

    def test_messages_parsed(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-18_auth-discussion", SAMPLE_CONVERSATION_1),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)

        messages = chats[0].messages
        assert len(messages) == 3
        assert messages[0].role == "human"
        assert messages[0].content == "How should we implement auth?"
        assert messages[1].role == "assistant"
        assert messages[1].content == "There are three main approaches..."
        assert messages[2].role == "human"
        assert messages[2].content == "Let's go with JWT."

    def test_message_timestamps(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-18_auth-discussion", SAMPLE_CONVERSATION_1),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)

        msg = chats[0].messages[0]
        assert msg.timestamp == datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc)

    def test_updated_time(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-18_auth-discussion", SAMPLE_CONVERSATION_1),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)

        assert chats[0].updated == datetime(2025, 2, 20, 9, 5, tzinfo=timezone.utc)

    def test_second_conversation(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-18_auth-discussion", SAMPLE_CONVERSATION_1),
            ("2025-02-19_api-design", SAMPLE_CONVERSATION_2),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)

        chat = chats[1]
        assert chat.remote_id == "gemini-conv-002"
        assert chat.title == "API Design"
        assert chat.model == "gemini-flash"
        assert len(chat.messages) == 2

    def test_system_messages_skipped(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-19_system", CONVERSATION_WITH_SYSTEM),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)

        messages = chats[0].messages
        assert len(messages) == 2
        assert messages[0].role == "human"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi there!"

    def test_empty_conversations(self, tmp_path: Path):
        empty_conv = {
            "id": "gemini-empty-001",
            "title": "Empty Chat",
            "create_time": "2025-02-19T10:00:00.000Z",
            "messages": [],
        }
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-19_empty", empty_conv),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)

        assert len(chats) == 1
        assert chats[0].messages == []

    def test_no_gemini_files_raises(self, tmp_path: Path):
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("other.txt", "hello")

        provider = GeminiProvider()
        with pytest.raises(FileNotFoundError, match="No Gemini conversation"):
            provider.parse_takeout_zip(zip_path)

    def test_malformed_conversation_skipped(self, tmp_path: Path):
        zip_path = tmp_path / "mixed.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "Takeout/Gemini Apps/Conversations/good/conversation.json",
                json.dumps(SAMPLE_CONVERSATION_1),
            )
            zf.writestr(
                "Takeout/Gemini Apps/Conversations/bad/conversation.json",
                "not valid json!!!",
            )

        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)
        assert len(chats) == 1

    def test_untitled_conversation_uses_folder_name(self, tmp_path: Path):
        conv = {
            "id": "gemini-notitle-001",
            "create_time": "2025-02-19T10:00:00.000Z",
            "messages": [],
        }
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-01-15_auth-discussion", conv),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)
        # Should derive title from folder name
        assert chats[0].title == "Auth Discussion"

    def test_id_from_conversation_id_field(self, tmp_path: Path):
        conv = {
            "conversation_id": "alt-gemini-id",
            "title": "Alt ID",
            "create_time": "2025-02-19T10:00:00.000Z",
            "messages": [],
        }
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-01-15_alt-id", conv),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)
        assert chats[0].remote_id == "alt-gemini-id"

    def test_id_fallback_to_folder_name(self, tmp_path: Path):
        conv = {
            "title": "No ID",
            "create_time": "2025-02-19T10:00:00.000Z",
            "messages": [],
        }
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-01-15_no-id-chat", conv),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)
        assert chats[0].remote_id == "2025-01-15_no-id-chat"

    def test_alternative_zip_path(self, tmp_path: Path):
        """Conversations under Takeout/Gemini/ instead of Takeout/Gemini Apps/."""
        zip_path = _make_takeout_zip(
            tmp_path,
            [("2025-02-18_auth-discussion", SAMPLE_CONVERSATION_1)],
            base_dir="Takeout/Gemini/Conversations",
        )
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)
        assert len(chats) == 1


class TestUnixTimestamps:
    def test_unix_timestamps_parsed(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-18_unix", CONVERSATION_UNIX_TIMESTAMPS),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)

        chat = chats[0]
        assert chat.created == datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc)
        assert chat.messages[0].timestamp == datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc)


class TestContentFormats:
    def test_content_parts_list(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-19_parts", CONVERSATION_CONTENT_PARTS),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)

        messages = chats[0].messages
        assert messages[0].content == "Part one.\nPart two."
        assert messages[1].content == "Response part A.\nResponse part B."

    def test_content_string(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-19_str", CONVERSATION_CONTENT_STRING),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)

        messages = chats[0].messages
        assert messages[0].content == "Simple string content"
        assert messages[1].content == "Simple response"

    def test_chunked_prompt_format(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-19_studio", CONVERSATION_CHUNKED_PROMPT),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)

        messages = chats[0].messages
        assert len(messages) == 2
        assert messages[0].content == "Hello from AI Studio"
        assert messages[1].content == "Hello! How can I help?"


class TestModelExtraction:
    def test_model_from_conversation_metadata(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-18_auth", SAMPLE_CONVERSATION_1),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)
        assert chats[0].model == "gemini-pro"

    def test_model_from_message_metadata(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-19_model-msg", CONVERSATION_MODEL_IN_MESSAGE),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)
        assert chats[0].model == "gemini-1.5-pro"


class TestRoleNormalization:
    def test_user_becomes_human(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-18_auth", SAMPLE_CONVERSATION_1),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)
        assert chats[0].messages[0].role == "human"

    def test_model_becomes_assistant(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-18_auth", SAMPLE_CONVERSATION_1),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)
        assert chats[0].messages[1].role == "assistant"


class TestScrubbing:
    def test_scrub_flag(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-18_secret", CONVERSATION_WITH_SECRETS),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path, scrub=True)

        msg0 = chats[0].messages[0].content
        assert "sk-ant-" not in msg0
        assert "[REDACTED" in msg0

        msg1 = chats[0].messages[1].content
        assert "Bearer eyJ" not in msg1
        assert "[REDACTED" in msg1

    def test_no_scrub_by_default(self, tmp_path: Path):
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-02-18_secret", CONVERSATION_WITH_SECRETS),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path, scrub=False)

        msg0 = chats[0].messages[0].content
        assert "sk-ant-" in msg0


class TestDirectoryParsing:
    def test_parse_extracted_directory(self, tmp_path: Path):
        dir_path = _make_takeout_dir(tmp_path, [
            ("2025-02-18_auth-discussion", SAMPLE_CONVERSATION_1),
            ("2025-02-19_api-design", SAMPLE_CONVERSATION_2),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(dir_path)
        assert len(chats) == 2

    def test_directory_not_found_raises(self, tmp_path: Path):
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()

        provider = GeminiProvider()
        with pytest.raises(FileNotFoundError, match="No Gemini Conversations"):
            provider.parse_takeout_zip(empty_dir)


class TestTitleFromFolderName:
    def test_date_prefix_stripped(self, tmp_path: Path):
        conv = {
            "id": "gemini-title-001",
            "create_time": "2025-02-19T10:00:00.000Z",
            "messages": [],
        }
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-01-15_auth-discussion", conv),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)
        assert chats[0].title == "Auth Discussion"

    def test_title_from_json_preferred(self, tmp_path: Path):
        """JSON title should take priority over folder name."""
        conv = {
            "id": "gemini-title-002",
            "title": "My Custom Title",
            "create_time": "2025-02-19T10:00:00.000Z",
            "messages": [],
        }
        zip_path = _make_takeout_zip(tmp_path, [
            ("2025-01-15_folder-title", conv),
        ])
        provider = GeminiProvider()
        chats = provider.parse_takeout_zip(zip_path)
        assert chats[0].title == "My Custom Title"
