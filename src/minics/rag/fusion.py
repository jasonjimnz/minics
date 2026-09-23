"""Reciprocal Rank Fusion.

RRF is the glue between the vector retriever and the graph retriever.  Because
the two produce scores on incomparable scales (cosine similarity vs. entity
weight), we fuse *ranks* instead of scores:

    score(d) = Σ_r  w_r / (k + rank_r(d))

``k`` (default 60) damps the influence of the very top of each list, which makes
the fusion robust to one retriever being noisy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[str]],
    *,
    k: int = 60,
    weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Fuse ``{retriever_name: [id, id, ...]}`` into ``{id: score}``."""
    weights = weights or {}
    scores: dict[str, float] = {}
    for name, ranked in rankings.items():
        weight = float(weights.get(name, 1.0))
        if weight <= 0:
            continue
        for rank, item in enumerate(ranked, start=1):
            if item is None:
                continue
            scores[item] = scores.get(item, 0.0) + weight / (k + rank)
    return scores


def fuse_hit_lists(
    rankings: Mapping[str, Sequence[dict[str, Any]]],
    *,
    key: str = "chunk_id",
    k: int = 60,
    weights: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Fuse lists of hit dicts, merging their metadata.

    Returns hits sorted by fused score, each annotated with ``fused_score``,
    ``ranks`` and ``sources``.
    """
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    hits: dict[str, dict[str, Any]] = {}
    sources: dict[str, list[str]] = {}

    for name, ranked in rankings.items():
        weight = float((weights or {}).get(name, 1.0))
        for rank, hit in enumerate(ranked, start=1):
            identifier = str(hit.get(key) or hit.get("id") or "")
            if not identifier:
                continue
            merged = hits.setdefault(identifier, {})
            for field, value in hit.items():
                if value not in (None, "", [], {}) and (
                    field not in merged or merged[field] in (None, "", [], {})
                ):
                    merged[field] = value
            ranks.setdefault(identifier, {})[name] = rank
            if weight > 0:
                scores[identifier] = scores.get(identifier, 0.0) + weight / (k + rank)
            sources.setdefault(identifier, [])
            if name not in sources[identifier]:
                sources[identifier].append(name)

    output: list[dict[str, Any]] = []
    for identifier, score in sorted(scores.items(), key=lambda kv: -kv[1]):
        hit = dict(hits[identifier])
        hit["fused_score"] = score
        hit["ranks"] = ranks.get(identifier, {})
        hit["sources"] = sources.get(identifier, [])
        output.append(hit)
    return output


def normalise(scores: Mapping[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    lowest = min(scores.values())
    highest = max(scores.values())
    span = highest - lowest
    if span <= 0:
        return {key: 1.0 for key in scores}
    return {key: (value - lowest) / span for key, value in scores.items()}
