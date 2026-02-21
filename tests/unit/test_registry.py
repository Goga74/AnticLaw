"""Tests for anticlaw.providers.registry."""

from anticlaw.providers.registry import ProviderEntry, ProviderRegistry


class _DummyProvider:
    def __init__(self, config: dict | None = None):
        self.config = config


class _AnotherProvider:
    def __init__(self):
        pass


class TestProviderRegistry:
    def test_register_and_get(self):
        reg = ProviderRegistry()
        reg.register("llm", "dummy", _DummyProvider)

        instance = reg.get("llm", "dummy", {"key": "val"})
        assert isinstance(instance, _DummyProvider)
        assert instance.config == {"key": "val"}

    def test_register_and_get_no_config(self):
        reg = ProviderRegistry()
        reg.register("llm", "another", _AnotherProvider)

        instance = reg.get("llm", "another")
        assert isinstance(instance, _AnotherProvider)

    def test_get_unknown_family(self):
        reg = ProviderRegistry()
        try:
            reg.get("nonexistent", "x")
            assert False, "Should raise KeyError"
        except KeyError:
            pass

    def test_get_unknown_provider(self):
        reg = ProviderRegistry()
        reg.register("llm", "dummy", _DummyProvider)
        try:
            reg.get("llm", "nonexistent")
            assert False, "Should raise KeyError"
        except KeyError:
            pass

    def test_list_family(self):
        reg = ProviderRegistry()
        reg.register("llm", "a", _DummyProvider)
        reg.register("llm", "b", _AnotherProvider)
        reg.register("backup", "c", _DummyProvider)

        llm_entries = reg.list_family("llm")
        assert len(llm_entries) == 2
        assert all(isinstance(e, ProviderEntry) for e in llm_entries)
        names = {e.name for e in llm_entries}
        assert names == {"a", "b"}

    def test_list_family_empty(self):
        reg = ProviderRegistry()
        assert reg.list_family("nonexistent") == []

    def test_list_all(self):
        reg = ProviderRegistry()
        reg.register("llm", "claude", _DummyProvider)
        reg.register("backup", "local", _AnotherProvider)

        all_entries = reg.list_all()
        assert len(all_entries) == 2

    def test_families(self):
        reg = ProviderRegistry()
        reg.register("llm", "x", _DummyProvider)
        reg.register("backup", "y", _DummyProvider)
        reg.register("embedding", "z", _DummyProvider)

        assert set(reg.families()) == {"llm", "backup", "embedding"}

    def test_get_entry(self):
        reg = ProviderRegistry()
        reg.register("llm", "dummy", _DummyProvider, extras=["scraper"])

        entry = reg.get_entry("llm", "dummy")
        assert entry.family == "llm"
        assert entry.name == "dummy"
        assert entry.cls is _DummyProvider
        assert entry.extras == ["scraper"]

    def test_extras_default_empty(self):
        reg = ProviderRegistry()
        reg.register("llm", "dummy", _DummyProvider)

        entry = reg.get_entry("llm", "dummy")
        assert entry.extras == []
