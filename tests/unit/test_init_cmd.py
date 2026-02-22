"""Tests for anticlaw.cli.init_cmd (aw init)."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from anticlaw.cli.main import cli


class TestInitBasic:
    def test_init_creates_structure(self, tmp_path: Path):
        home = tmp_path / "anticlaw_home"
        runner = CliRunner()
        result = runner.invoke(cli, ["init", str(home)])

        assert result.exit_code == 0, result.output
        assert "Initialized" in result.output
        assert (home / ".acl").is_dir()
        assert (home / "_inbox").is_dir()
        assert (home / "_archive").is_dir()

    def test_init_creates_config_yaml(self, tmp_path: Path):
        home = tmp_path / "anticlaw_home"
        runner = CliRunner()
        runner.invoke(cli, ["init", str(home)])

        config_file = home / ".acl" / "config.yaml"
        assert config_file.exists()

        config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert "search" in config
        assert "llm" in config
        assert "providers" in config
        assert config["providers"]["claude"]["enabled"] is True
        assert config["providers"]["chatgpt"]["enabled"] is True

    def test_init_creates_gitignore(self, tmp_path: Path):
        home = tmp_path / "anticlaw_home"
        runner = CliRunner()
        runner.invoke(cli, ["init", str(home)])

        gitignore = home / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text(encoding="utf-8")
        assert "meta.db" in content
        assert "chroma" in content
        assert ".DS_Store" in content

    def test_init_already_initialized(self, tmp_path: Path):
        home = tmp_path / "anticlaw_home"
        runner = CliRunner()

        # First init
        result1 = runner.invoke(cli, ["init", str(home)])
        assert result1.exit_code == 0

        # Second init — should report already initialized
        result2 = runner.invoke(cli, ["init", str(home)])
        assert result2.exit_code == 0
        assert "already initialized" in result2.output

    def test_init_does_not_overwrite_gitignore(self, tmp_path: Path):
        home = tmp_path / "anticlaw_home"
        runner = CliRunner()

        # Init once
        runner.invoke(cli, ["init", str(home)])

        # Modify .gitignore
        gitignore = home / ".gitignore"
        gitignore.write_text("custom content\n", encoding="utf-8")

        # Re-init with --interactive (bypasses "already initialized" check)
        result = runner.invoke(cli, ["init", str(home), "--interactive"], input="y\ny\nn\nn\nn\n")
        assert result.exit_code == 0

        # .gitignore should not be overwritten
        assert gitignore.read_text(encoding="utf-8") == "custom content\n"

    def test_init_shows_next_steps(self, tmp_path: Path):
        home = tmp_path / "anticlaw_home"
        runner = CliRunner()
        result = runner.invoke(cli, ["init", str(home)])

        assert "Next steps" in result.output
        assert "aw import claude" in result.output
        assert "aw import chatgpt" in result.output
        assert "aw search" in result.output

    def test_init_default_path(self, tmp_path: Path, monkeypatch):
        """Without a path argument, init uses resolve_home()."""
        home = tmp_path / "default_home"
        monkeypatch.setenv("ACL_HOME", str(home))

        runner = CliRunner()
        result = runner.invoke(cli, ["init"])

        assert result.exit_code == 0
        assert (home / ".acl").is_dir()


class TestInitInteractive:
    def test_interactive_all_defaults(self, tmp_path: Path):
        home = tmp_path / "anticlaw_home"
        runner = CliRunner()

        # Answer all prompts with defaults (just press Enter)
        # Prompts: claude? [Y], chatgpt? [Y], gemini? [N], ollama? [N], daemon? [N]
        result = runner.invoke(
            cli,
            ["init", str(home), "--interactive"],
            input="y\ny\nn\nn\nn\n",
        )

        assert result.exit_code == 0, result.output
        assert "Setup" in result.output

        config = yaml.safe_load(
            (home / ".acl" / "config.yaml").read_text(encoding="utf-8")
        )
        assert config["providers"]["claude"]["enabled"] is True
        assert config["providers"]["chatgpt"]["enabled"] is True
        assert config["providers"]["gemini"]["enabled"] is False

    def test_interactive_enable_gemini(self, tmp_path: Path):
        home = tmp_path / "anticlaw_home"
        runner = CliRunner()

        # claude=Y, chatgpt=Y, gemini=Y, ollama=N, daemon=N
        result = runner.invoke(
            cli,
            ["init", str(home), "--interactive"],
            input="y\ny\ny\nn\nn\n",
        )

        assert result.exit_code == 0, result.output
        config = yaml.safe_load(
            (home / ".acl" / "config.yaml").read_text(encoding="utf-8")
        )
        assert config["providers"]["gemini"]["enabled"] is True

    def test_interactive_enable_ollama(self, tmp_path: Path):
        home = tmp_path / "anticlaw_home"
        runner = CliRunner()

        # claude=Y, chatgpt=Y, gemini=N, ollama=Y, model=default, embed=default, daemon=N
        result = runner.invoke(
            cli,
            ["init", str(home), "--interactive"],
            input="y\ny\nn\ny\nllama3.1:8b\nnomic-embed-text\nn\n",
        )

        assert result.exit_code == 0, result.output
        config = yaml.safe_load(
            (home / ".acl" / "config.yaml").read_text(encoding="utf-8")
        )
        assert config["llm"]["model"] == "llama3.1:8b"
        assert config["embeddings"]["model"] == "nomic-embed-text"

    def test_interactive_enable_daemon(self, tmp_path: Path):
        home = tmp_path / "anticlaw_home"
        runner = CliRunner()

        # claude=Y, chatgpt=Y, gemini=N, ollama=N, daemon=Y, autostart=N
        result = runner.invoke(
            cli,
            ["init", str(home), "--interactive"],
            input="y\ny\nn\nn\ny\nn\n",
        )

        assert result.exit_code == 0, result.output
        config = yaml.safe_load(
            (home / ".acl" / "config.yaml").read_text(encoding="utf-8")
        )
        assert config["daemon"]["enabled"] is True
        assert config["daemon"]["autostart"] is False

    def test_interactive_reconfigures_existing(self, tmp_path: Path):
        """--interactive allows re-running on an existing KB."""
        home = tmp_path / "anticlaw_home"
        runner = CliRunner()

        # First init
        runner.invoke(cli, ["init", str(home)])

        # Second init with --interactive should work (not skip)
        result = runner.invoke(
            cli,
            ["init", str(home), "--interactive"],
            input="y\ny\nn\nn\nn\n",
        )
        assert result.exit_code == 0
        assert "Initialized" in result.output


class TestInitHelp:
    def test_help_text(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--help"])
        assert result.exit_code == 0
        assert "Initialize" in result.output
        assert "--interactive" in result.output
        assert "PATH" in result.output
