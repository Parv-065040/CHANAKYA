"""Supabase RPC retrieval adapter for CHANAKYA.

This module only retrieves candidate chunks from PostgreSQL/pgvector and
PostgreSQL FTS. Ranking/fusion/evidence validation remains in CHANAKYA's
existing retrieval pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import requests

from .core.models import Chunk


@dataclass(frozen=True)
class SupabaseCandidate:
    chunk: Chunk
    score: float


class SupabaseRetrieval:
    """Candidate retrieval through Supabase RPC functions."""

    def __init__(
        self,
        url: str,
        service_key: str,
        embedder,
        *,
        timeout: int = 60,
    ) -> None:
        self.base = url.rstrip("/")
        self.embedder = embedder
        self.timeout = timeout
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    def _rpc(self, function: str, payload: dict) -> list[dict]:
        response = requests.post(
            f"{self.base}/rest/v1/rpc/{function}",
            headers=self.headers,
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Supabase RPC {function} -> "
                f"{response.status_code}: {response.text[:300]}"
            )
        return response.json()

    @staticmethod
    def _chunk(row: dict) -> Chunk:
        return Chunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            document_name=row["document_name"],
            department=row["department"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            section=row.get("section") or "",
            content_type=row["content_type"],
            text=row["text"],
            table_id=row.get("table_id"),
            table_rows=row.get("table_rows") or 0,
        )

    def vector_search(
        self,
        query: str,
        top_k: int,
        departments: Iterable[str] | None = None,
    ) -> list[SupabaseCandidate]:
        query_embedding = self.embedder.embed([query])[0]

        depts = list(departments or [])
        if not depts:
            rows = self._rpc(
                "match_chunks",
                {
                    "query_embedding": query_embedding.tolist(),
                    "match_count": top_k,
                    "filter_department": None,
                },
            )
            return [
                SupabaseCandidate(self._chunk(row), float(row["similarity"]))
                for row in rows
            ]

        merged: dict[str, SupabaseCandidate] = {}

        for department in depts:
            rows = self._rpc(
                "match_chunks",
                {
                    "query_embedding": query_embedding.tolist(),
                    "match_count": top_k,
                    "filter_department": department,
                },
            )

            for row in rows:
                candidate = SupabaseCandidate(
                    self._chunk(row),
                    float(row["similarity"]),
                )
                previous = merged.get(candidate.chunk.chunk_id)
                if previous is None or candidate.score > previous.score:
                    merged[candidate.chunk.chunk_id] = candidate

        return sorted(
            merged.values(),
            key=lambda item: item.score,
            reverse=True,
        )[:top_k]

    def keyword_search(
        self,
        query: str,
        top_k: int,
        departments: Iterable[str] | None = None,
    ) -> list[SupabaseCandidate]:
        depts = list(departments or [])

        def fetch(department: str | None) -> list[dict]:
            return self._rpc(
                "keyword_chunks",
                {
                    "query_text": query,
                    "match_count": top_k,
                    "filter_department": department,
                },
            )

        rows_by_id: dict[str, SupabaseCandidate] = {}

        if not depts:
            rows = fetch(None)
            for row in rows:
                candidate = SupabaseCandidate(
                    self._chunk(row),
                    float(row["rank"]),
                )
                rows_by_id[candidate.chunk.chunk_id] = candidate
        else:
            for department in depts:
                for row in fetch(department):
                    candidate = SupabaseCandidate(
                        self._chunk(row),
                        float(row["rank"]),
                    )
                    previous = rows_by_id.get(candidate.chunk.chunk_id)
                    if previous is None or candidate.score > previous.score:
                        rows_by_id[candidate.chunk.chunk_id] = candidate

        return sorted(
            rows_by_id.values(),
            key=lambda item: item.score,
            reverse=True,
        )[:top_k]
