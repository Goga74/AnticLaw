"""Tests for anticlaw.cli.import_cmd (aw import gemini)."""

import json
import zipfile
from pathlib import Path

from click.testing import CliRunner

from anticlaw.cli.main import cli


SAMPLE_GEMINI_CONVERSATIONS = [
    (
        "2025-02-18_first-chat",
        {
            "id": "gemini-chat-001",
            "title": "First Chat",
            "create_time": "2025-02-18T14:30:00.000Z",
            "update_time": "2025-02-18T15:00:00.000Z",
            "model": "gemini-pro",
            "messages": [
                {
                    "role": "user",
                    "text": "Hello!",
                    "create_time": "2025-02-18T14:30:00.000Z",
                },
                {
                    "role": "model",
                    "text": "Hi there!",
                    "create_time": "2025-02-18T14:31:00.000Z",
                },
            ],
        },
    ),
    (
        "2025-02-19_second-chat",
        {
            "id": "gemini-chat-002",
            "title": "Second Chat",
            "create_time": "2025-02-19T10:00:00.000Z",
            "model": "gemini-flash",
            "messages": [
                {
                    "role": "user",
                    "text": "Question.",
                    "create_time": "2025-02-19T10:00:00.000Z",
                },
                {
                    "role": "model",
                    "text": "Answer.",
                    "create_time": "2025-02-19T10:01:00.000Z",
                },
            ],
        },
    ),
]


def _make_gemini_zip(tmp_path: Path) -> Path:
    zip_path = tmp_path / "gemini-takeout.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for folder_name, conv_data in SAMPLE_GEMINI_CONVERSATIONS:
            entry = f"Takeout/Gemini Apps/Conversations/{folder_name}/conversation.json"
            zf.writestr(entry, json.dumps(conv_data))
    return zip_path


class TestImportGemini:
    def test_import_to_inbox(self, tmp_path: Path):
        zip_path = _make_gemini_zip(tmp_path)
        home = tmp_path / "anticlaw_home"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "import", "gemini", str(zip_path), "--home", str(home),
        ])

        assert result.exit_code == 0, result.output
        assert "Imported: 2" in result.output
        assert "_inbox" in result.output

        # Check files were created in _inbox
        inbox = home / "_inbox"
        md_files = list(inbox.glob("*.md"))
        assert len(md_files) == 2

    def test_imported_file_has_gemini_provider(self, tmp_path: Path):
        zip_path = _make_gemini_zip(tmp_path)
        home = tmp_path / "anticlaw_home"

        runner = CliRunner()
        runner.invoke(cli, [
            "import", "gemini", str(zip_path), "--home", str(home),
        ])

        inbox = home / "_inbox"
        md_files = list(inbox.glob("*.md"))
        assert len(md_files) == 2

        # At least one file should have gemini as provider
        contents = [f.read_text(encoding="utf-8") for f in md_files]
        assert any("provider: gemini" in c for c in contents)

    def test_import_with_scrub(self, tmp_path: Path):
        conv = (
            "2025-02-18_secrets",
            {
                "id": "secret-chat",
                "title": "Secrets",
                "create_time": "2025-02-18T14:30:00.000Z",
                "messages": [
                    {
                        "role": "user",
                        "text": "My key is sk-ant-XXXXXXXXXXXXXXXXXXXXXXXX_longkey",
                        "create_time": "2025-02-18T14:30:00.000Z",
                    },
                ],
            },
        )
        zip_path = tmp_path / "secrets.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            folder_name, conv_data = conv
            entry = f"Takeout/Gemini Apps/Conversations/{folder_name}/conversation.json"
            zf.writestr(entry, json.dumps(conv_data))

        home = tmp_path / "anticlaw_home"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "import", "gemini", str(zip_path), "--scrub", "--home", str(home),
        ])

        assert result.exit_code == 0, result.output
        assert "scrubbing: enabled" in result.output

        # Read the imported file and verify scrubbing
        md_files = list((home / "_inbox").glob("*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text(encoding="utf-8")
        assert "sk-ant-" not in content
        assert "[REDACTED" in content

    def test_import_skips_duplicates(self, tmp_path: Path):
        zip_path = _make_gemini_zip(tmp_path)
        home = tmp_path / "anticlaw_home"

        runner = CliRunner()
        # First import
        result1 = runner.invoke(cli, [
            "import", "gemini", str(zip_path), "--home", str(home),
        ])
        assert result1.exit_code == 0
        assert "Imported: 2" in result1.output

        # Second import — should skip
        result2 = runner.invoke(cli, [
            "import", "gemini", str(zip_path), "--home", str(home),
        ])
        assert result2.exit_code == 0
        assert "Imported: 0" in result2.output
        assert "Skipped" in result2.output

    def test_import_empty_zip(self, tmp_path: Path):
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("Takeout/Gemini Apps/Conversations/empty/conversation.json", json.dumps({
                "id": "empty",
                "title": "Empty",
                "create_time": "2025-02-19T10:00:00.000Z",
                "messages": [],
            }))

        home = tmp_path / "anticlaw_home"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "import", "gemini", str(zip_path), "--home", str(home),
        ])
        assert result.exit_code == 0
        assert "Imported: 1" in result.output

    def test_import_creates_home_structure(self, tmp_path: Path):
        zip_path = _make_gemini_zip(tmp_path)
        home = tmp_path / "fresh_home"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "import", "gemini", str(zip_path), "--home", str(home),
        ])
        assert result.exit_code == 0
        assert (home / ".acl").is_dir()
        assert (home / "_inbox").is_dir()
        assert (home / "_archive").is_dir()

    def test_help_text(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["import", "gemini", "--help"])
        assert result.exit_code == 0
        assert "Gemini" in result.output


class TestCrossProviderImportWithGemini:
    """Verify that importing from Claude, ChatGPT, and Gemini produces files that coexist."""

    def test_three_providers_in_inbox(self, tmp_path: Path):
        home = tmp_path / "anticlaw_home"
        runner = CliRunner()

        # Import Claude
        claude_conversations = [
            {
                "uuid": "claude-001",
                "name": "Claude Chat",
                "created_at": "2025-02-18T14:30:00.000Z",
                "chat_messages": [
                    {"sender": "human", "text": "Hello from Claude!", "created_at": "2025-02-18T14:30:00.000Z"},
                    {"sender": "assistant", "text": "Hi!", "created_at": "2025-02-18T14:31:00.000Z"},
                ],
            },
        ]
        claude_zip = tmp_path / "claude-export.zip"
        with zipfile.ZipFile(claude_zip, "w") as zf:
            zf.writestr("conversations.json", json.dumps(claude_conversations))

        result1 = runner.invoke(cli, [
            "import", "claude", str(claude_zip), "--home", str(home),
        ])
        assert result1.exit_code == 0

        # Import ChatGPT
        chatgpt_conversations = [
            {
                "title": "ChatGPT Chat",
                "create_time": 1739889000.0,
                "conversation_id": "chatgpt-001",
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
                            "content": {"content_type": "text", "parts": ["Hello from ChatGPT!"]},
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
                            "content": {"content_type": "text", "parts": ["Hi!"]},
                            "create_time": 1739889060.0,
                            "metadata": {"model_slug": "gpt-4"},
                        },
                        "parent": "u1",
                        "children": [],
                    },
                },
            },
        ]
        chatgpt_zip = tmp_path / "chatgpt-export.zip"
        with zipfile.ZipFile(chatgpt_zip, "w") as zf:
            zf.writestr("conversations.json", json.dumps(chatgpt_conversations))

        result2 = runner.invoke(cli, [
            "import", "chatgpt", str(chatgpt_zip), "--home", str(home),
        ])
        assert result2.exit_code == 0

        # Import Gemini
        gemini_zip = _make_gemini_zip(tmp_path)
        result3 = runner.invoke(cli, [
            "import", "gemini", str(gemini_zip), "--home", str(home),
        ])
        assert result3.exit_code == 0

        # All three should be in _inbox
        inbox = home / "_inbox"
        md_files = list(inbox.glob("*.md"))
        assert len(md_files) == 4  # 1 Claude + 1 ChatGPT + 2 Gemini

        # Verify providers in files
        contents = [f.read_text(encoding="utf-8") for f in md_files]
        providers_found = set()
        for content in contents:
            if "provider: claude" in content:
                providers_found.add("claude")
            if "provider: chatgpt" in content:
                providers_found.add("chatgpt")
            if "provider: gemini" in content:
                providers_found.add("gemini")

        assert "claude" in providers_found
        assert "chatgpt" in providers_found
        assert "gemini" in providers_found
