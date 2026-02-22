"""Tests for anticlaw.providers.llm.chatgpt."""

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from anticlaw.providers.llm.base import Capability
from anticlaw.providers.llm.chatgpt import ChatGPTProvider


# --- Fixtures ---

# ChatGPT uses a mapping dict with message nodes linked by parent/children
SAMPLE_CONVERSATIONS = [
    {
        "title": "Auth Discussion",
        "create_time": 1739889000.0,  # 2025-02-18T14:30:00Z
        "update_time": 1740042300.0,  # 2025-02-20T09:05:00Z
        "conversation_id": "conv-chatgpt-001",
        "mapping": {
            "root-node": {
                "id": "root-node",
                "message": None,  # root has no message
                "parent": None,
                "children": ["msg-node-1"],
            },
            "msg-node-1": {
                "id": "msg-node-1",
                "message": {
                    "id": "msg-1",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["How should we implement auth?"]},
                    "create_time": 1739889000.0,
                    "metadata": {},
                },
                "parent": "root-node",
                "children": ["msg-node-2"],
            },
            "msg-node-2": {
                "id": "msg-node-2",
                "message": {
                    "id": "msg-2",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["There are three main approaches..."]},
                    "create_time": 1739889060.0,
                    "metadata": {"model_slug": "gpt-4"},
                },
                "parent": "msg-node-1",
                "children": ["msg-node-3"],
            },
            "msg-node-3": {
                "id": "msg-node-3",
                "message": {
                    "id": "msg-3",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Let's go with JWT."]},
                    "create_time": 1739889300.0,
                    "metadata": {},
                },
                "parent": "msg-node-2",
                "children": [],
            },
        },
    },
    {
        "title": "API Design",
        "create_time": 1739959200.0,  # 2025-02-19T10:00:00Z
        "update_time": 1739959200.0,
        "conversation_id": "conv-chatgpt-002",
        "mapping": {
            "root": {
                "id": "root",
                "message": None,
                "parent": None,
                "children": ["node-a"],
            },
            "node-a": {
                "id": "node-a",
                "message": {
                    "id": "a",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["What REST conventions should we follow?"]},
                    "create_time": 1739959200.0,
                    "metadata": {},
                },
                "parent": "root",
                "children": ["node-b"],
            },
            "node-b": {
                "id": "node-b",
                "message": {
                    "id": "b",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["Here are the best practices..."]},
                    "create_time": 1739959260.0,
                    "metadata": {"model_slug": "gpt-4o"},
                },
                "parent": "node-a",
                "children": [],
            },
        },
    },
]

CONVERSATIONS_WITH_SYSTEM = [
    {
        "title": "With System Message",
        "create_time": 1739959200.0,
        "conversation_id": "conv-system-001",
        "mapping": {
            "root": {
                "id": "root",
                "message": None,
                "parent": None,
                "children": ["sys"],
            },
            "sys": {
                "id": "sys",
                "message": {
                    "id": "s1",
                    "author": {"role": "system"},
                    "content": {"content_type": "text", "parts": ["You are a helpful assistant."]},
                    "create_time": 1739959200.0,
                    "metadata": {},
                },
                "parent": "root",
                "children": ["u1"],
            },
            "u1": {
                "id": "u1",
                "message": {
                    "id": "um1",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Hello"]},
                    "create_time": 1739959210.0,
                    "metadata": {},
                },
                "parent": "sys",
                "children": ["a1"],
            },
            "a1": {
                "id": "a1",
                "message": {
                    "id": "am1",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["Hi there!"]},
                    "create_time": 1739959220.0,
                    "metadata": {"model_slug": "gpt-3.5-turbo"},
                },
                "parent": "u1",
                "children": [],
            },
        },
    },
]

CONVERSATIONS_WITH_TOOL = [
    {
        "title": "With Tool Call",
        "create_time": 1739959200.0,
        "conversation_id": "conv-tool-001",
        "mapping": {
            "root": {
                "id": "root",
                "message": None,
                "parent": None,
                "children": ["u1"],
            },
            "u1": {
                "id": "u1",
                "message": {
                    "id": "um1",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Search for Python docs"]},
                    "create_time": 1739959200.0,
                    "metadata": {},
                },
                "parent": "root",
                "children": ["t1"],
            },
            "t1": {
                "id": "t1",
                "message": {
                    "id": "tm1",
                    "author": {"role": "tool"},
                    "content": {"content_type": "text", "parts": ["search results..."]},
                    "create_time": 1739959210.0,
                    "metadata": {},
                },
                "parent": "u1",
                "children": ["a1"],
            },
            "a1": {
                "id": "a1",
                "message": {
                    "id": "am1",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["Here's what I found..."]},
                    "create_time": 1739959220.0,
                    "metadata": {"model_slug": "gpt-4"},
                },
                "parent": "t1",
                "children": [],
            },
        },
    },
]

CONVERSATIONS_WITH_SECRETS = [
    {
        "title": "Secret Chat",
        "create_time": 1739889000.0,
        "conversation_id": "conv-secret-001",
        "mapping": {
            "root": {
                "id": "root",
                "message": None,
                "parent": None,
                "children": ["u1"],
            },
            "u1": {
                "id": "u1",
                "message": {
                    "id": "um1",
                    "author": {"role": "user"},
                    "content": {
                        "content_type": "text",
                        "parts": ["My API key is sk-ant-abc123XYZ0987654321long_enough_key"],
                    },
                    "create_time": 1739889000.0,
                    "metadata": {},
                },
                "parent": "root",
                "children": ["a1"],
            },
            "a1": {
                "id": "a1",
                "message": {
                    "id": "am1",
                    "author": {"role": "assistant"},
                    "content": {
                        "content_type": "text",
                        "parts": ["Use Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def for auth"],
                    },
                    "create_time": 1739889060.0,
                    "metadata": {"model_slug": "gpt-4"},
                },
                "parent": "u1",
                "children": [],
            },
        },
    },
]

CONVERSATIONS_MULTIPART = [
    {
        "title": "Multipart Content",
        "create_time": 1739959200.0,
        "conversation_id": "conv-multi-001",
        "mapping": {
            "root": {
                "id": "root",
                "message": None,
                "parent": None,
                "children": ["u1"],
            },
            "u1": {
                "id": "u1",
                "message": {
                    "id": "um1",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Hello"]},
                    "create_time": 1739959200.0,
                    "metadata": {},
                },
                "parent": "root",
                "children": ["a1"],
            },
            "a1": {
                "id": "a1",
                "message": {
                    "id": "am1",
                    "author": {"role": "assistant"},
                    "content": {
                        "content_type": "text",
                        "parts": ["Part one.", "Part two.", "Part three."],
                    },
                    "create_time": 1739959260.0,
                    "metadata": {"model_slug": "gpt-4"},
                },
                "parent": "u1",
                "children": [],
            },
        },
    },
]

CONVERSATIONS_EMPTY_MAPPING = [
    {
        "title": "Empty Chat",
        "create_time": 1739959200.0,
        "conversation_id": "conv-empty-001",
        "mapping": {},
    },
]

CONVERSATIONS_CODE_CONTENT = [
    {
        "title": "Code Content",
        "create_time": 1739959200.0,
        "conversation_id": "conv-code-001",
        "mapping": {
            "root": {
                "id": "root",
                "message": None,
                "parent": None,
                "children": ["u1"],
            },
            "u1": {
                "id": "u1",
                "message": {
                    "id": "um1",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Show me code"]},
                    "create_time": 1739959200.0,
                    "metadata": {},
                },
                "parent": "root",
                "children": ["a1"],
            },
            "a1": {
                "id": "a1",
                "message": {
                    "id": "am1",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "code", "text": "print('hello world')"},
                    "create_time": 1739959260.0,
                    "metadata": {"model_slug": "gpt-4"},
                },
                "parent": "u1",
                "children": [],
            },
        },
    },
]


def _make_export_zip(tmp_path: Path, conversations: list[dict]) -> Path:
    """Create a test ChatGPT export ZIP with conversations.json."""
    zip_path = tmp_path / "chatgpt-export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("conversations.json", json.dumps(conversations))
    return zip_path


# --- Tests ---


class TestChatGPTProviderInfo:
    def test_name(self):
        p = ChatGPTProvider()
        assert p.name == "chatgpt"

    def test_display_name(self):
        p = ChatGPTProvider()
        assert p.info.display_name == "ChatGPT"

    def test_capabilities(self):
        p = ChatGPTProvider()
        assert Capability.EXPORT_BULK in p.info.capabilities

    def test_auth_returns_true(self):
        p = ChatGPTProvider()
        assert p.auth({}) is True

    def test_unsupported_methods(self):
        p = ChatGPTProvider()
        with pytest.raises(NotImplementedError):
            p.export_chat("any-id")
        with pytest.raises(NotImplementedError):
            p.import_chat(None, None)
        with pytest.raises(NotImplementedError):
            p.sync(Path("."), "proj-1")
        with pytest.raises(NotImplementedError):
            p.export_all(Path("."))

    def test_list_projects_empty(self):
        p = ChatGPTProvider()
        assert p.list_projects() == []

    def test_list_chats_empty(self):
        p = ChatGPTProvider()
        assert p.list_chats() == []


class TestParseExportZip:
    def test_basic_parse(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ChatGPTProvider()

        chats = provider.parse_export_zip(zip_path)
        assert len(chats) == 2

    def test_conversation_fields(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        chat = chats[0]
        assert chat.remote_id == "conv-chatgpt-001"
        assert chat.title == "Auth Discussion"
        assert chat.provider == "chatgpt"
        assert chat.model == "gpt-4"
        assert chat.created == datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc)

    def test_messages_parsed(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        messages = chats[0].messages
        assert len(messages) == 3
        assert messages[0].role == "human"
        assert messages[0].content == "How should we implement auth?"
        assert messages[1].role == "assistant"
        assert messages[1].content == "There are three main approaches..."
        assert messages[2].role == "human"
        assert messages[2].content == "Let's go with JWT."

    def test_message_timestamps(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        msg = chats[0].messages[0]
        assert msg.timestamp == datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc)

    def test_updated_time(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        assert chats[0].updated == datetime(2025, 2, 20, 9, 5, tzinfo=timezone.utc)

    def test_second_conversation(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        chat = chats[1]
        assert chat.remote_id == "conv-chatgpt-002"
        assert chat.title == "API Design"
        assert chat.model == "gpt-4o"
        assert len(chat.messages) == 2

    def test_system_messages_skipped(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, CONVERSATIONS_WITH_SYSTEM)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        messages = chats[0].messages
        # System message should be skipped, only user + assistant remain
        assert len(messages) == 2
        assert messages[0].role == "human"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi there!"

    def test_tool_messages_skipped(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, CONVERSATIONS_WITH_TOOL)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        messages = chats[0].messages
        # Tool message should be skipped
        assert len(messages) == 2
        assert messages[0].role == "human"
        assert messages[1].role == "assistant"

    def test_multipart_content(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, CONVERSATIONS_MULTIPART)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        messages = chats[0].messages
        assert messages[1].content == "Part one.\nPart two.\nPart three."

    def test_code_content(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, CONVERSATIONS_CODE_CONTENT)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        messages = chats[0].messages
        assert messages[1].content == "print('hello world')"

    def test_empty_mapping(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, CONVERSATIONS_EMPTY_MAPPING)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        assert len(chats) == 1
        assert chats[0].messages == []

    def test_empty_export(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, [])
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)
        assert chats == []

    def test_missing_conversations_json(self, tmp_path: Path):
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("other.txt", "hello")

        provider = ChatGPTProvider()
        with pytest.raises(FileNotFoundError, match="conversations.json"):
            provider.parse_export_zip(zip_path)

    def test_nested_conversations_json(self, tmp_path: Path):
        """conversations.json can be in a subdirectory."""
        zip_path = tmp_path / "nested.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("export/data/conversations.json", json.dumps(SAMPLE_CONVERSATIONS))

        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)
        assert len(chats) == 2

    def test_malformed_conversation_skipped(self, tmp_path: Path):
        """A malformed conversation should be skipped, not crash the whole import."""
        conversations = [
            SAMPLE_CONVERSATIONS[0],
            {"broken": True},  # malformed
        ]
        zip_path = _make_export_zip(tmp_path, conversations)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)
        assert len(chats) >= 1

    def test_untitled_conversation(self, tmp_path: Path):
        conversations = [
            {
                "title": "",
                "create_time": 1739959200.0,
                "conversation_id": "conv-untitled",
                "mapping": {},
            },
        ]
        zip_path = _make_export_zip(tmp_path, conversations)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)
        assert chats[0].title == "Untitled"

    def test_null_title_conversation(self, tmp_path: Path):
        conversations = [
            {
                "title": None,
                "create_time": 1739959200.0,
                "conversation_id": "conv-null-title",
                "mapping": {},
            },
        ]
        zip_path = _make_export_zip(tmp_path, conversations)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)
        assert chats[0].title == "Untitled"

    def test_conversation_with_id_field(self, tmp_path: Path):
        """Some exports use 'id' instead of 'conversation_id'."""
        conversations = [
            {
                "title": "Alt ID",
                "create_time": 1739959200.0,
                "id": "alt-id-001",
                "mapping": {},
            },
        ]
        zip_path = _make_export_zip(tmp_path, conversations)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)
        assert chats[0].remote_id == "alt-id-001"


class TestScrubbing:
    def test_scrub_flag(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, CONVERSATIONS_WITH_SECRETS)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path, scrub=True)

        msg0 = chats[0].messages[0].content
        assert "sk-ant-" not in msg0
        assert "[REDACTED" in msg0

        msg1 = chats[0].messages[1].content
        assert "Bearer eyJ" not in msg1
        assert "[REDACTED" in msg1

    def test_no_scrub_by_default(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, CONVERSATIONS_WITH_SECRETS)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path, scrub=False)

        msg0 = chats[0].messages[0].content
        assert "sk-ant-" in msg0


class TestRoleNormalization:
    def test_user_becomes_human(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        assert chats[0].messages[0].role == "human"

    def test_assistant_stays_assistant(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        assert chats[0].messages[1].role == "assistant"


class TestModelExtraction:
    def test_model_from_assistant_metadata(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, SAMPLE_CONVERSATIONS)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        assert chats[0].model == "gpt-4"
        assert chats[1].model == "gpt-4o"

    def test_model_from_system_message_chat(self, tmp_path: Path):
        zip_path = _make_export_zip(tmp_path, CONVERSATIONS_WITH_SYSTEM)
        provider = ChatGPTProvider()
        chats = provider.parse_export_zip(zip_path)

        assert chats[0].model == "gpt-3.5-turbo"
