"""Maximal Marginal Relevance — stop retrieval from returning the same fact five times.

A pure relevance ranking has a failure mode that gets worse as the corpus
grows: the top-k are all near-duplicates. Five chunks of the same
post-mortem score almost identically, crowd out the one chunk that would
have contradicted them, and the model reads a narrow slice as consensus.

MMR (Carbonell & Goldstein, 1998) fixes this by picking greedily on a blend
of relevance and *novelty relative to what is already selected*::

    score = λ · relevance(d, q) − (1 − λ) · max similarity(d, s) for s in selected

λ = 1.0 is pure relevance (the old behaviour); λ = 0.7 keeps ranking firmly
in charge while breaking up duplicate runs. Similarity here is token
Jaccard rather than cosine, deliberately: it needs no embedding for the
keyword-search path, and near-duplicate prose is exactly what token overlap
is good at detecting.
"""

from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Words too common to signal that two chunks are about the same thing.
_STOP = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "if",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "this",
        "that",
        "these",
        "those",
        "as",
        "at",
        "by",
        "from",
        "has",
        "have",
        "had",
        "not",
        "no",
        "you",
        "your",
        "we",
        "our",
        "they",
        "their",
    }
)


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        w
        for w in _TOKEN_RE.findall((text or "").lower())
        if w not in _STOP and len(w) > 2
    )


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Token-set overlap in [0, 1]. Empty sets are maximally dissimilar."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    if not intersection:
        return 0.0
    return intersection / len(a | b)


def mmr_rerank(
    items: list[dict[str, Any]],
    *,
    limit: int,
    lambda_: float = 0.65,
    text_key: str = "content",
    score_key: str = "score",
) -> list[dict[str, Any]]:
    """Reorder *items* (already relevance-sorted) for relevance + diversity.

    Returns at most *limit* items.

    Scores are normalized by dividing by the maximum, not by min-max. That
    matters more than it looks: min-max stretches whatever range happens to
    be present, so three near-tied duplicates at the top become 1.0 / 0.98 /
    0.96 while a genuinely useful chunk three points behind collapses to
    0.0 — and no λ short of absurd can then promote it. Dividing by the max
    preserves the ratios the scorer actually produced.
    """
    if not items:
        return []
    if limit <= 0:
        return []
    if lambda_ >= 1.0 or len(items) <= 1:
        return items[:limit]

    scores = [float(item.get(score_key, 0.0) or 0.0) for item in items]
    highest = max(scores)
    relevance = [s / highest for s in scores] if highest > 0 else [0.0 for _ in scores]
    token_sets = [_tokens(str(item.get(text_key, ""))) for item in items]

    selected: list[int] = []
    remaining = set(range(len(items)))

    while remaining and len(selected) < limit:
        best_index = -1
        best_value = float("-inf")
        for i in remaining:
            if selected:
                redundancy = max(
                    jaccard(token_sets[i], token_sets[j]) for j in selected
                )
            else:
                redundancy = 0.0
            value = lambda_ * relevance[i] - (1.0 - lambda_) * redundancy
            if value > best_value:
                best_value = value
                best_index = i
        if best_index < 0:  # pragma: no cover — defensive
            break
        selected.append(best_index)
        remaining.discard(best_index)

    return [items[i] for i in selected]


def dedupe_near_identical(
    items: list[dict[str, Any]],
    *,
    threshold: float = 0.92,
    text_key: str = "content",
) -> list[dict[str, Any]]:
    """Drop chunks that are near-verbatim copies of an earlier one.

    Runs before MMR: an exact duplicate carries no information at any λ,
    and re-indexed files produce them routinely.
    """
    kept: list[dict[str, Any]] = []
    kept_tokens: list[frozenset[str]] = []
    for item in items:
        tokens = _tokens(str(item.get(text_key, "")))
        if any(jaccard(tokens, other) >= threshold for other in kept_tokens):
            continue
        kept.append(item)
        kept_tokens.append(tokens)
    return kept
