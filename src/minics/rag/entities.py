"""Lightweight entity extraction for the knowledge graph.

The graph does not need perfect NLP to be useful: it needs stable *topology*.
We extract a handful of high-signal entity types with cheap heuristics and let
the LLM enrichment pass (when configured) refine them later.

Extracted kinds:

``term``     significant single words (frequency ranked)
``acronym``  ALL-CAPS tokens such as ``RRF`` or ``LLM``
``phrase``   capitalised multi-word sequences such as ``Reciprocal Rank Fusion``
``markup``   terms the author emphasised (``**bold**`` or `` `code` ``)
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "which", "these",
    "those", "when", "where", "while", "there", "their", "then", "than", "them",
    "they", "have", "has", "had", "was", "were", "are", "is", "be", "been", "being",
    "will", "would", "can", "could", "should", "may", "might", "must", "not", "but",
    "you", "your", "our", "its", "it", "as", "at", "by", "on", "of", "or", "to",
    "in", "an", "a", "we", "us", "if", "so", "such", "also", "more", "most", "other",
    "some", "any", "all", "each", "how", "what", "who", "why", "using", "used", "use",
    "one", "two", "between", "over", "under", "about", "after", "before", "here",
}

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_\-']{2,}")
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,6}\b")
_MARKUP = re.compile(r"\*\*([^*\n]{2,60})\*\*|`([^`\n]{2,60})`")
_CONNECTIVES = {"of", "the", "and", "for", "to", "in", "on", "with", "vs"}
_PHRASE = re.compile(
    r"\b[A-Z][A-Za-z0-9\-]*(?:\s+(?:[A-Z][A-Za-z0-9\-]*|of|the|and|for|to|in|on|with|vs)){1,5}"
)


@dataclass
class Entity:
    name: str
    kind: str = "term"
    weight: float = 1.0
    mentions: int = 1
    metadata: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return self.name.strip()


def extract_entities(text: str, *, max_entities: int = 24) -> list[Entity]:
    """Extract a deduplicated, weighted entity list from ``text``."""
    if not text:
        return []
    found: dict[str, Entity] = {}

    def add(name: str, kind: str, weight: float = 1.0) -> None:
        name = " ".join(name.split()).strip(" .,;:!?()[]{}\"'")
        if not name or len(name) < 2:
            return
        if name.lower() in _STOPWORDS:
            return
        existing = found.get(name.lower())
        if existing is None:
            found[name.lower()] = Entity(name=name, kind=kind, weight=weight, mentions=1)
        else:
            existing.mentions += 1
            existing.weight += weight

    for match in _MARKUP.finditer(text):
        value = match.group(1) or match.group(2)
        if value:
            add(value.strip(), "markup", weight=2.0)

    for match in _PHRASE.finditer(text):
        words = match.group(0).split()
        while words and words[-1].lower() in _CONNECTIVES:
            words.pop()
        if len(words) < 2:
            continue
        if sum(1 for word in words if word[:1].isupper()) < 2:
            continue
        add(" ".join(words), "phrase", weight=1.5)

    for match in _ACRONYM.finditer(text):
        token = match.group(0)
        if token.lower() not in _STOPWORDS:
            add(token, "acronym", weight=1.5)

    counts = Counter(
        word.group(0).lower()
        for word in _WORD.finditer(text)
        if word.group(0).lower() not in _STOPWORDS
    )
    for word, count in counts.most_common(max_entities):
        if len(word) < 4:
            continue
        add(word, "term", weight=1.0 + 0.25 * (count - 1))

    ranked = sorted(found.values(), key=lambda e: (-e.weight, -e.mentions, e.name))
    return ranked[:max_entities]


def extract_cooccurrence(
    entities: list[Entity], *, limit: int = 40
) -> list[tuple[str, str, float]]:
    """Return ``(a, b, weight)`` pairs for entities appearing together."""
    names = [e.name for e in entities]
    pairs: list[tuple[str, str, float]] = []
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            if left.lower() == right.lower():
                continue
            pairs.append((left, right, 1.0))
            if len(pairs) >= limit:
                return pairs
    return pairs
