"""Tests for anticlaw.core.models."""

from datetime import datetime, timezone

from anticlaw.core.models import (
    Chat,
    ChatData,
    ChatMessage,
    Edge,
    EdgeType,
    Importance,
    Insight,
    InsightCategory,
    Project,
    RemoteChat,
    RemoteProject,
    Status,
    SyncResult,
)


class TestChatMessage:
    def test_defaults(self):
        msg = ChatMessage(role="human", content="hello")
        assert msg.role == "human"
        assert msg.content == "hello"
        assert msg.timestamp is None

    def test_with_timestamp(self):
        ts = datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc)
        msg = ChatMessage(role="assistant", content="hi", timestamp=ts)
        assert msg.timestamp == ts


class TestChat:
    def test_defaults(self):
        chat = Chat()
        assert chat.id  # UUID generated
        assert chat.title == ""
        assert chat.tags == []
        assert chat.messages == []
        assert chat.importance == Importance.MEDIUM
        assert chat.status == Status.ACTIVE

    def test_custom_fields(self):
        chat = Chat(
            id="test-123",
            title="Auth discussion",
            provider="claude",
            tags=["auth", "jwt"],
            importance=Importance.HIGH,
        )
        assert chat.id == "test-123"
        assert chat.title == "Auth discussion"
        assert chat.provider == "claude"
        assert chat.tags == ["auth", "jwt"]
        assert chat.importance == "high"

    def test_messages_are_independent(self):
        """Each Chat instance should have its own messages list."""
        c1 = Chat()
        c2 = Chat()
        c1.messages.append(ChatMessage(role="human", content="hi"))
        assert len(c2.messages) == 0


class TestProject:
    def test_defaults(self):
        proj = Project(name="test")
        assert proj.name == "test"
        assert proj.status == Status.ACTIVE
        assert proj.providers == {}
        assert proj.settings == {}


class TestInsight:
    def test_defaults(self):
        ins = Insight(content="SQLite is good")
        assert ins.id  # UUID generated
        assert ins.content == "SQLite is good"
        assert ins.category == InsightCategory.FACT
        assert ins.importance == Importance.MEDIUM
        assert ins.chat_id is None


class TestEdge:
    def test_defaults(self):
        edge = Edge(source_id="a", target_id="b")
        assert edge.edge_type == EdgeType.SEMANTIC
        assert edge.weight == 1.0


class TestProviderModels:
    def test_remote_project(self):
        rp = RemoteProject(id="p1", name="Alpha", provider="claude")
        assert rp.id == "p1"

    def test_remote_chat(self):
        rc = RemoteChat(id="c1", title="Chat 1", provider="claude")
        assert rc.message_count == 0

    def test_chat_data(self):
        cd = ChatData(remote_id="r1", title="Test", provider="claude")
        assert cd.messages == []

    def test_sync_result(self):
        sr = SyncResult(provider="claude", pulled=5, pushed=2)
        assert sr.conflicts == 0
        assert sr.errors == []
