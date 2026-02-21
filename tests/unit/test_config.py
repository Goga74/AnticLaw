"""Tests for anticlaw.core.config."""

import os
from pathlib import Path

from anticlaw.core.config import DEFAULTS, _deep_merge, load_config


class TestDeepMerge:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3}

    def test_nested_merge(self):
        base = {"search": {"alpha": 0.6, "max_results": 20}}
        override = {"search": {"alpha": 0.8}}
        result = _deep_merge(base, override)
        assert result["search"]["alpha"] == 0.8
        assert result["search"]["max_results"] == 20

    def test_new_keys(self):
        base = {"a": 1}
        override = {"b": 2}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 2}

    def test_does_not_mutate_base(self):
        base = {"a": {"b": 1}}
        override = {"a": {"b": 2}}
        _deep_merge(base, override)
        assert base["a"]["b"] == 1


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_path: Path):
        config = load_config(tmp_path / "nonexistent.yaml")
        assert config["search"]["alpha"] == DEFAULTS["search"]["alpha"]
        assert config["search"]["max_results"] == DEFAULTS["search"]["max_results"]

    def test_loads_and_merges(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("search:\n  alpha: 0.9\n")

        config = load_config(config_file)
        assert config["search"]["alpha"] == 0.9
        # Defaults preserved for unset keys
        assert config["search"]["max_results"] == 20

    def test_acl_home_env_override(self, tmp_path: Path, monkeypatch):
        custom_home = tmp_path / "custom"
        monkeypatch.setenv("ACL_HOME", str(custom_home))

        config = load_config(tmp_path / "nonexistent.yaml")
        assert config["home"] == str(custom_home.resolve())

    def test_handles_empty_file(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        config = load_config(config_file)
        assert config["search"]["alpha"] == DEFAULTS["search"]["alpha"]

    def test_handles_corrupt_yaml(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(": : : invalid yaml [[[")

        # Should fall back to defaults without crashing
        config = load_config(config_file)
        assert "search" in config
