"""Hybrid retrieval: local or Supabase vector + keyword -> RRF -> rerank -> evidence gate."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .config import Settings
from .core.fusion import reciprocal_rank_fusion
from .core.keyword import QUERY_STOP, normalize_aliases, tokenize
from .core.models import Chunk
from .core.router import RoutePlan
from .store import KnowledgeBase
from .supabase_retrieval import SupabaseRetrieval

_BI = lambda t: set(zip(t, t[1:]))  # noqa: E731
_RECORD_HINT = re.compile(
    r"\b(register|log|logs|record|records|listing|work orders?|lots?|requisitions?|"
    r"(t|wo|lot|req|cx|kb|hz|fc)[- ]?\d{3,6})\b",
    re.I,
)
BULK_ROWS = 100


class LexicalReranker:
    """IDF-weighted query-term coverage + bigram + exact-phrase bonus."""

    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb

    def _idf(self, term: str) -> float:
        n, df = len(self.kb.bm25), self.kb.bm25._df.get(term, 0)
        df = max(df, 1)
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
            bonus = (
                0.15 * (len(bi & _BI(toks)) / len(bi))
                if bi
                else 0.0
            )

            score = min(1.0, cov + bonus)

            if (
                c.content_type == "table"
                and c.table_rows >= BULK_ROWS
                and not _RECORD_HINT.search(query)
            ):
                score *= 0.55

            out.append(score)

        return out


@dataclass
class Retrieved:
    chunk: Chunk
    score: float


class HybridRetriever:
    def __init__(
        self,
        kb: KnowledgeBase,
        min_relevance: float,
        min_coverage: float = 0.6,
        settings: Settings | None = None,
    ) -> None:
        self.kb = kb
        self.min_relevance = min_relevance
        self.min_coverage = min_coverage
        self.reranker = LexicalReranker(kb)

        self.backend = (settings.retrieval_backend if settings else "local").lower()

        if self.backend == "supabase":
            if not (settings and settings.supabase_url and settings.supabase_service_key):
                raise ValueError(
                    "RETRIEVAL_BACKEND=supabase requires "
                    "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"
                )

            self.remote = SupabaseRetrieval(
                settings.supabase_url,
                settings.supabase_service_key,
                kb.embedder,
            )
        elif self.backend == "local":
            self.remote = None
        else:
            raise ValueError(
                f"unknown RETRIEVAL_BACKEND {self.backend!r}"
            )

    def _cap(
        self,
        ids: list[str],
        k: int,
        per_section: int = 2,
    ) -> list[str]:
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

    def _cap_chunks(
        self,
        chunks: list[Chunk],
        k: int,
        per_section: int = 2,
    ) -> list[Chunk]:
        seen: dict[tuple[str, str], int] = {}
        out: list[Chunk] = []

        for c in chunks:
            key = (c.document_id, c.section)

            if seen.get(key, 0) >= per_section:
                continue

            seen[key] = seen.get(key, 0) + 1
            out.append(c)

            if len(out) >= k:
                break

        return out

    def _retrieve_local_candidates(
        self,
        query: str,
        k: int,
        depts: set[str],
    ) -> tuple[list[str], dict[str, Chunk], dict[str, float]]:
        vector_ranked = self.kb.vector_search(
            query, len(self.kb.chunks), depts
        )
        vector_ids = self._cap([cid for cid, _ in vector_ranked], k)
        semantic_scores = {cid: score for cid, score in vector_ranked if cid in vector_ids}

        keyword_ids = self._cap(
            [cid for cid, _ in self.kb.keyword_search(query, len(self.kb.chunks), depts)],
            k,
        )

        chunks = {
            cid: self.kb.chunks[cid]
            for cid in set(vector_ids + keyword_ids)
            if cid in self.kb.chunks
        }
        return vector_ids, {cid: chunks[cid] for cid in chunks}, semantic_scores

    def _retrieve_supabase_candidates(
        self,
        query: str,
        k: int,
        depts: set[str],
    ) -> tuple[list[str], dict[str, Chunk], dict[str, float]]:
        assert self.remote is not None
        remote_k = max(k * 3, 60)

        vector = self.remote.vector_search(query, remote_k, depts)
        keyword = self.remote.keyword_search(query, remote_k, depts)

        vector_chunks = self._cap_chunks([x.chunk for x in vector], remote_k)
        keyword_chunks = self._cap_chunks([x.chunk for x in keyword], remote_k)

        vector_ids = [c.chunk_id for c in vector_chunks]
        keyword_ids = [c.chunk_id for c in keyword_chunks]
        chunks = {c.chunk_id: c for c in vector_chunks + keyword_chunks}
        semantic_scores = {x.chunk.chunk_id: x.score for x in vector}

        return vector_ids, {cid: chunks[cid] for cid in set(vector_ids + keyword_ids)}, semantic_scores

    def retrieve(
        self,
        query: str,
        plan: RoutePlan,
        *,
        allowed: set[str] | None = None,
    ) -> list[Retrieved]:

        depts = set(plan.departments) if plan.departments else set()

        if allowed is not None:
            depts &= allowed

        if not depts:
            return []

        k = plan.candidate_k

        if self.backend == "supabase":
            vector_ids, chunk_map, semantic_scores = self._retrieve_supabase_candidates(
                query,
                k,
                depts,
            )

            remote_k = max(k * 3, 60)
            keyword_candidates = self.remote.keyword_search(
                query,
                remote_k,
                depts,
            )
            keyword_chunks = self._cap_chunks(
                [x.chunk for x in keyword_candidates],
                remote_k,
            )
            keyword_ids = [c.chunk_id for c in keyword_chunks]
        else:
            vector_ids, chunk_map, semantic_scores = self._retrieve_local_candidates(
                query,
                k,
                depts,
            )

            keyword_ids = self._cap(
                [
                    cid
                    for cid, _ in self.kb.keyword_search(
                        query,
                        len(self.kb.chunks),
                        depts,
                    )
                ],
                k,
            )

        rankings = [vector_ids, keyword_ids]

        fused = reciprocal_rank_fusion(
            rankings,
            top_n=k,
        )

        cands = [
            chunk_map[cid]
            for cid, _ in fused
            if cid in chunk_map
        ]

        lexical_scores = self.reranker.score(query, cands)

        # Preserve dense BGE-M3 relevance for natural-language questions.
        # Previously, semantically relevant chunks could receive lexical score
        # 0 and be discarded even though vector retrieval found them.
        scores = []
        for chunk, lexical in zip(cands, lexical_scores):
            semantic = max(0.0, min(1.0, semantic_scores.get(chunk.chunk_id, 0.0)))
            scores.append(0.65 * semantic + 0.35 * lexical)

        top_rrf = fused[0][1] if fused else 1.0
        fused_s = {
            cid: sc / top_rrf
            for cid, sc in fused
        }

        ranked = sorted(
            zip(cands, scores),
            key=lambda t: -(
                t[1]
                + 0.25 * fused_s.get(t[0].chunk_id, 0.0)
            ),
        )

        kept = [
            Retrieved(c, s)
            for c, s in ranked
            if s >= self.min_relevance
        ]

        if plan.needs_multi_retrieval:
            kept = _diversify(kept, plan.top_k)

        kept = kept[: plan.top_k]

        terms = self.reranker.query_terms(query)

        if terms and kept:
            total = sum(terms.values()) or 1.0

            def cov(items: list[Retrieved]) -> float:
                have: set[str] = set()

                for it in items:
                    have |= (
                        set(tokenize(it.chunk.embedding_text))
                        & terms.keys()
                    )

                return sum(
                    terms[t]
                    for t in have
                ) / total

            best_single = max(
                cov([it])
                for it in kept
            )

            if (
                plan.question_type == "table_lookup"
                and len(terms) == 3
            ):
                term_set = set(terms)

                has_complete_chunk = any(
                    term_set.issubset(
                        set(
                            tokenize(
                                normalize_aliases(
                                    it.chunk.embedding_text
                                )
                            )
                        )
                    )
                    for it in kept
                )

                if not has_complete_chunk:
                    return []

            # Broad factual/semantic questions do not need every query token
            # to appear in one chunk. Keep the evidence gate strict for
            # calculations and multi-source questions, but avoid false refusals
            # for natural-language knowledge questions.
            if plan.needs_numerics or plan.needs_multi_retrieval:
                coverage = cov(kept)
                if coverage < self.min_coverage:
                    return []

        return kept


def _diversify(
    items: list[Retrieved],
    top_k: int,
) -> list[Retrieved]:
    seen: set[str] = set()
    first: list[Retrieved] = []
    rest: list[Retrieved] = []

    for it in items:
        (
            rest
            if it.chunk.document_id in seen
            else first
        ).append(it)

        seen.add(it.chunk.document_id)

    return (first + rest)[:top_k]
