"""Hybrid retrieval: vector + BM25 -> RRF -> rerank -> relevance-gated evidence."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .core.fusion import reciprocal_rank_fusion
from .core.keyword import QUERY_STOP, normalize_aliases, tokenize
from .core.models import Chunk
from .core.router import RoutePlan
from .store import KnowledgeBase

_BI = lambda t: set(zip(t, t[1:]))  # noqa: E731
_RECORD_HINT = re.compile(r"\b(register|log|logs|record|records|listing|work orders?|lots?|requisitions?|"
                          r"(t|wo|lot|req|cx|kb|hz|fc)[- ]?\d{3,6})\b", re.I)
BULK_ROWS = 100  # tables at least this long are treated as registers/logs


class LexicalReranker:
    """IDF-weighted query-term coverage + bigram + exact-phrase bonus; score in [0, 1].

    Open-source/zero-cost default. Swap for a cross-encoder (e.g. BAAI/bge-reranker-v2-m3)
    by implementing ``score(query, chunks)``.
    """

    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb

    def _idf(self, term: str) -> float:
        n, df = len(self.kb.bm25), self.kb.bm25._df.get(term, 0)
        df = max(df, 1)  # unseen terms weigh like rare terms, not infinitely
        return math.log(1 + (n - df + 0.5) / (df + 0.5)) if n else 1.0

    def query_terms(self, query: str) -> dict[str, float]:
        q = [t for t in tokenize(normalize_aliases(query)) if t not in QUERY_STOP]
        return {t: self._idf(t) for t in set(q)}

    def score(self, query: str, chunks: list[Chunk]) -> list[float]:
        q = [t for t in tokenize(normalize_aliases(query)) if t not in QUERY_STOP]
        if not q:
            return [0.0] * len(chunks)
        weights = {t: self._idf(t) for t in set(q)}
        total = sum(weights.values()) or 1.0
        out = []
        for c in chunks:
            toks = tokenize(normalize_aliases(c.embedding_text))
            ts = set(toks)
            cov = sum(w for t, w in weights.items() if t in ts) / total
            bi = _BI(q)
            bonus = 0.15 * (len(bi & _BI(toks)) / len(bi)) if bi else 0.0
            score = min(1.0, cov + bonus)
            if c.content_type == "table" and c.table_rows >= BULK_ROWS and not _RECORD_HINT.search(query):
                score *= 0.55  # bulk registers match any query via repeated headers; demote unless record-level
            out.append(score)
        return out


@dataclass
class Retrieved:
    chunk: Chunk
    score: float


class HybridRetriever:
    def __init__(self, kb: KnowledgeBase, min_relevance: float, min_coverage: float = 0.6) -> None:
        self.kb, self.min_relevance, self.min_coverage = kb, min_relevance, min_coverage
        self.reranker = LexicalReranker(kb)

    def _cap(self, ids: list[str], k: int, per_section: int = 2) -> list[str]:
        """Keep at most ``per_section`` chunks per (document, section) so a huge register or log
        cannot crowd out every other source; then truncate to k."""
        seen: dict[tuple[str, str], int] = {}
        out: list[str] = []
        for cid in ids:
            c = self.kb.chunks.get(cid)
            if c is None:
                continue
            key = (c.document_id, c.section)
            if seen.get(key, 0) >= per_section:
                continue
            seen[key] = seen.get(key, 0) + 1
            out.append(cid)
        return out[:k]

    def retrieve(self, query: str, plan: RoutePlan, *, allowed: set[str] | None = None) -> list[Retrieved]:
        depts = set(plan.departments) if plan.departments else set()
        if allowed is not None:
            depts &= allowed
        if not depts:
            return []
        k = plan.candidate_k
        rankings = [self._cap([cid for cid, _ in self.kb.vector_search(query, len(self.kb.chunks), depts)], k),
                    self._cap([cid for cid, _ in self.kb.keyword_search(query, len(self.kb.chunks), depts)], k)]
        fused = reciprocal_rank_fusion(rankings, top_n=k)
        cands = [self.kb.chunks[cid] for cid, _ in fused if cid in self.kb.chunks]
        scores = self.reranker.score(query, cands)
        top_rrf = fused[0][1] if fused else 1.0
        fused_s = {cid: sc / top_rrf for cid, sc in fused}
        ranked = sorted(zip(cands, scores), key=lambda t: -(t[1] + 0.25 * fused_s.get(t[0].chunk_id, 0.0)))
        kept = [Retrieved(c, s) for c, s in ranked if s >= self.min_relevance]
        if plan.needs_multi_retrieval:  # ensure document diversity for multi-source questions
            kept = _diversify(kept, plan.top_k)
        kept = kept[: plan.top_k]
        # Evidence-sufficiency gate. Single-concept questions need ONE chunk covering the key terms
        # (stops "salary" + "managing director" matching two unrelated chunks); multi-source questions
        # may combine chunks.
        terms = self.reranker.query_terms(query)
        if terms and kept:
            total = sum(terms.values()) or 1.0

            def cov(items: list[Retrieved]) -> float:
                have: set[str] = set()
                for it in items:
                    have |= set(tokenize(it.chunk.embedding_text)) & terms.keys()
                return sum(terms[t] for t in have) / total

            best_single = max(cov([it]) for it in kept)

            # For compact 3-term table lookups, require one evidence chunk
            # to contain all meaningful query terms. This prevents unrelated
            # chunks from jointly satisfying an entity/attribute lookup.
            if plan.question_type == "table_lookup" and len(terms) == 3:
                term_set = set(terms)
                has_complete_chunk = any(
                    term_set.issubset(
                        set(tokenize(normalize_aliases(it.chunk.embedding_text)))
                    )
                    for it in kept
                )
                if not has_complete_chunk:
                    return []

            if (cov(kept) if plan.needs_multi_retrieval else best_single) < self.min_coverage:
                return []
        return kept


def _diversify(items: list[Retrieved], top_k: int) -> list[Retrieved]:
    seen: set[str] = set()
    first, rest = [], []
    for it in items:
        (rest if it.chunk.document_id in seen else first).append(it)
        seen.add(it.chunk.document_id)
    return (first + rest)[:top_k]

