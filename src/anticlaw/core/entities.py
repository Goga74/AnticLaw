"""Regex entity extractor for knowledge graph edges."""

from __future__ import annotations

import re

# --- Entity patterns ---

_FILE_PATH_RE = re.compile(
    r"[\w./\\-]+\.(?:py|js|ts|java|go|rs|sql|md|yaml|yml|json|toml|xml|html|css|sh|rb|c|cpp|h)\b",
    re.IGNORECASE,
)

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

# CamelCase: ChatStorage, MetaDB, JavaScript (lowercase then uppercase transition)
_CAMEL_CASE_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-zA-Z]*)+\b")

# Mixed-case technical terms: SQLite, HTMLElement (uppercase prefix + lowercase)
_MIXED_CASE_RE = re.compile(r"\b[A-Z]{2,}[a-z]{2,}\w*\b")

_UPPER_IDENT_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")

# --- Causal keywords ---

CAUSAL_KEYWORDS: list[str] = [
    "because",
    "therefore",
    "thus",
    "hence",
    "since",
    "so that",
    "caused by",
    "fixed by",
    "due to",
    "as a result",
    "leads to",
    "results in",
    "in order to",
    "resolved by",
    # Russian
    "потому что",
    "из-за",
    "в результате",
    "поэтому",
    "следовательно",
    "решили потому что",
    "чтобы",
]

_CAUSAL_RE = re.compile(
    "|".join(re.escape(kw) for kw in CAUSAL_KEYWORDS),
    re.IGNORECASE,
)

# Common noise words to exclude from upper-case identifiers
_NOISE = frozenset({
    "THE", "AND", "FOR", "NOT", "BUT", "ALL", "ARE", "WAS", "HAS",
    "WITH", "THIS", "THAT", "FROM", "HAVE", "WILL", "CAN", "USE",
    "ALSO", "SOME", "EACH", "THEN", "THAN", "WHEN", "WHAT", "HOW",
    "WHO", "WHY", "WHERE", "WHICH", "DOES", "DID", "MAY", "SHOULD",
    "COULD", "WOULD", "INTO", "OVER", "YOUR", "JUST", "LIKE",
    "ANY", "NEW", "GET", "SET", "TWO", "WAY",
    "TODO", "NOTE", "FIXME", "HACK", "XXX",
})


def extract_entities(text: str) -> list[str]:
    """Extract entities from text using regex patterns.

    Returns sorted, deduplicated list of entities found:
    file paths, URLs, CamelCase identifiers, and UPPER_CASE technical terms.
    """
    entities: set[str] = set()

    # File paths
    for m in _FILE_PATH_RE.finditer(text):
        entities.add(m.group())

    # URLs
    for m in _URL_RE.finditer(text):
        url = m.group().rstrip(".,;:")
        entities.add(url)

    # CamelCase identifiers (e.g. ChatStorage, MetaDB)
    for m in _CAMEL_CASE_RE.finditer(text):
        entities.add(m.group())

    # Mixed-case technical terms (e.g. SQLite, HTMLElement)
    for m in _MIXED_CASE_RE.finditer(text):
        entities.add(m.group())

    # UPPER_CASE technical terms (e.g. JWT, API → filtered)
    for m in _UPPER_IDENT_RE.finditer(text):
        term = m.group()
        if term not in _NOISE:
            entities.add(term)

    return sorted(entities)


def has_causal_language(text: str) -> bool:
    """Check if text contains causal keywords."""
    return bool(_CAUSAL_RE.search(text))
