"""Reciprocal Rank Fusion (Cormack et al., 2009).

score(d) = sum_over_rankers  weight / (k + rank(d)),  rank starting at 1.
RRF is rank-based, so vector cosine scores and BM25 scores (different scales)
can be combined without calibration.
"""
from __future__ import annotations

from collections.abc import Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    *,
    k: int = 60,
    weights: Sequence[float] | None = None,
    top_n: int | None = None,
) -> list[tuple[str, float]]:
    if k < 0:
        raise ValueError("k must be >= 0")
    if weights is not None and len(weights) != len(rankings):
        raise ValueError("weights must match number of rankings")
    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    for i, ranking in enumerate(rankings):
        w = 1.0 if weights is None else weights[i]
        seen: set[str] = set()
        for rank, doc_id in enumerate(ranking, start=1):
            if doc_id in seen:  # ignore duplicates within one ranker
                continue
            seen.add(doc_id)
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank)
            best_rank[doc_id] = min(best_rank.get(doc_id, rank), rank)
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], best_rank[kv[0]], kv[0]))
    return ordered[:top_n] if top_n is not None else ordered
