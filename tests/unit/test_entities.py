"""Tests for anticlaw.core.entities."""

from anticlaw.core.entities import extract_entities, has_causal_language


class TestExtractEntities:
    def test_file_paths(self):
        text = "We edited src/main.py and config.yaml for the fix."
        entities = extract_entities(text)
        assert "src/main.py" in entities
        assert "config.yaml" in entities

    def test_urls(self):
        text = "See https://example.com/docs and http://localhost:8080/api"
        entities = extract_entities(text)
        assert "https://example.com/docs" in entities
        assert "http://localhost:8080/api" in entities

    def test_camel_case(self):
        text = "The ChatStorage and MetaDB classes handle persistence."
        entities = extract_entities(text)
        assert "ChatStorage" in entities
        assert "MetaDB" in entities

    def test_upper_case_terms(self):
        text = "We chose JWT over SAML for the API authentication."
        entities = extract_entities(text)
        assert "JWT" in entities
        assert "SAML" in entities
        assert "API" in entities

    def test_filters_noise_words(self):
        text = "THE system SHOULD NOT use ANY of THESE patterns."
        entities = extract_entities(text)
        assert "THE" not in entities
        assert "NOT" not in entities
        assert "ANY" not in entities

    def test_empty_text(self):
        assert extract_entities("") == []

    def test_no_entities(self):
        text = "just a simple sentence with no special terms"
        assert extract_entities(text) == []

    def test_mixed_entities(self):
        text = (
            "We use SQLite with ChatStorage class in storage.py. "
            "See https://sqlite.org for details."
        )
        entities = extract_entities(text)
        assert "ChatStorage" in entities
        assert "storage.py" in entities
        assert "https://sqlite.org" in entities
        assert "SQLite" in entities

    def test_deduplication(self):
        text = "ChatStorage is great. ChatStorage is the best."
        entities = extract_entities(text)
        assert entities.count("ChatStorage") == 1

    def test_sorted_output(self):
        text = "ZooKeeper and Apache and ChatStorage"
        entities = extract_entities(text)
        assert entities == sorted(entities)


class TestHasCausalLanguage:
    def test_because(self):
        assert has_causal_language("We chose SQLite because it's embedded.")

    def test_therefore(self):
        assert has_causal_language("The test fails, therefore we need a fix.")

    def test_fixed_by(self):
        assert has_causal_language("The race condition was fixed by flock.")

    def test_caused_by(self):
        assert has_causal_language("The crash was caused by a null pointer.")

    def test_due_to(self):
        assert has_causal_language("Failed due to missing permissions.")

    def test_russian_because(self):
        assert has_causal_language("Выбрали SQLite потому что он встроен.")

    def test_russian_due_to(self):
        assert has_causal_language("Ошибка из-за нехватки памяти.")

    def test_no_causal(self):
        assert not has_causal_language("SQLite is an embedded database engine.")

    def test_empty_text(self):
        assert not has_causal_language("")

    def test_case_insensitive(self):
        assert has_causal_language("BECAUSE of the error, we changed approach.")
