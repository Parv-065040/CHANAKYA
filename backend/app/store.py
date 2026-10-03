"""Knowledge base: ingestion, versioning, vector + keyword indexes, local persistence.

Local persistence = JSON metadata + .npy vectors + raw files on disk. The same
interface maps onto Supabase (see sql/schema.sql: documents, chunks + pgvector).
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import Settings
from .core.chunking import ChunkingConfig, StructureAwareChunker
from .core.keyword import BM25Index
from .core.models import Chunk
from .embeddings import Embedder
from .parsers import parse_document
from .persistence import Persistence

log = logging.getLogger("chanakya.store")
_SAFE = re.compile(r"[^A-Za-z0-9._\- ]")


@dataclass
class DocumentRecord:
    document_id: str
    name: str
    department: str
    version: int
    status: str  # indexed | failed
    size_bytes: int
    n_chunks: int
    n_tables: int
    pages: int
    sha256: str
    uploaded_at: float = field(default_factory=time.time)
    error: str = ""


class KnowledgeBase:
    def __init__(self, settings: Settings, embedder: Embedder, valid_departments: set[str], persistence: Persistence | None = None) -> None:
        self.settings, self.embedder, self.valid_departments = settings, embedder, valid_departments
        from .persistence import LocalPersistence
        self.persist: Persistence = persistence or LocalPersistence(Path(settings.data_dir), self.fingerprint_of(settings, embedder))
        self.chunker = StructureAwareChunker(ChunkingConfig(settings.chunk_max_chars, settings.chunk_min_chars))
        self.docs: dict[str, DocumentRecord] = {}
        self.chunks: dict[str, Chunk] = {}
        self._order: list[str] = []
        self._vecs = np.zeros((0, embedder.dimension), np.float32)
        self.bm25 = BM25Index()
        self._lock = threading.RLock()
        self._load()

    @staticmethod
    def fingerprint_of(settings: Settings, embedder: Embedder) -> str:
        return f"{settings.embedding_provider}:{settings.embedding_model}:{embedder.dimension}"

    # ---- ingestion -------------------------------------------------------
    def ingest(self, filename: str, data: bytes, department: str) -> DocumentRecord:
        if department not in self.valid_departments:
            raise ValueError(f"unknown department {department!r}")
        name = _SAFE.sub("_", filename.split("/")[-1].split("\\")[-1])[:120] or "upload"
        if len(data) > self.settings.max_upload_mb * 1024 * 1024:
            raise ValueError(f"file exceeds {self.settings.max_upload_mb} MB limit")
        digest = hashlib.sha256(data).hexdigest()
        with self._lock:
            prior = [d for d in self.docs.values() if d.name == name and d.department == department]
            if any(d.sha256 == digest for d in prior):
                return next(d for d in prior if d.sha256 == digest)  # idempotent re-upload
            version = max((d.version for d in prior), default=0) + 1
            doc_id = uuid.uuid4().hex[:12]
            blocks = parse_document(name, data)
            chunks = self.chunker.chunk(blocks, document_id=doc_id, document_name=name, department=department)
            if not chunks:
                raise ValueError("document produced no chunks")
            vecs = self._embed_all([c.embedding_text for c in chunks])
            rec = DocumentRecord(doc_id, name, department, version, "indexed", len(data), len(chunks),
                                 sum(c.content_type == "table" for c in chunks),
                                 max(b.page for b in blocks), digest)
            superseded = [d for d in prior if d.status == "indexed"]
            snapshot = ({k: DocumentRecord(**vars(v)) for k, v in self.docs.items()}, dict(self.chunks), list(self._order), self._vecs)
            try:
                for old in superseded:  # supersede previous versions (kept in registry as history)
                    self._drop_chunks(old.document_id)
                    old.status = "superseded"
                self.docs[doc_id] = rec
                self._add_chunks(chunks, vecs)
                self._validate_index(doc_id, len(chunks))
                self.persist.save_document(self, rec, chunks, vecs, data, superseded)
            except Exception:
                log.exception("ingest failed; rolling back in-memory index")
                self.docs, self.chunks, self._order, self._vecs = snapshot
                self.bm25 = BM25Index()  # BM25 mutates in place, so rebuild it from the restored chunks
                self.bm25.add(list(self.chunks.values()))
                raise
            log.info("ingested %s v%d: %d chunks", name, version, len(chunks))
            return rec

    def _validate_index(self, doc_id: str, expected: int) -> None:
        got = sum(1 for c in self.chunks.values() if c.document_id == doc_id)
        if got != expected or len(self._vecs) != len(self._order):
            raise RuntimeError("index validation failed")

    def _add_chunks(self, chunks: list[Chunk], vecs: np.ndarray) -> None:
        for c in chunks:
            self.chunks[c.chunk_id] = c
            self._order.append(c.chunk_id)
        self._vecs = np.vstack([self._vecs, vecs]) if len(self._vecs) else vecs
        self.bm25.add(chunks)

    def _drop_chunks(self, doc_id: str) -> None:
        keep = [i for i, cid in enumerate(self._order) if self.chunks[cid].document_id != doc_id]
        for cid in [cid for cid in self._order if self.chunks[cid].document_id == doc_id]:
            del self.chunks[cid]
        self._order = [self._order[i] for i in keep]
        self._vecs = self._vecs[keep] if keep else np.zeros((0, self.embedder.dimension), np.float32)
        self.bm25.remove_document(doc_id)

    def delete(self, document_id: str) -> bool:
        with self._lock:
            if document_id not in self.docs:
                return False
            self._drop_chunks(document_id)
            rec = self.docs.pop(document_id)
            self.persist.delete_document(self, document_id)
            log.info("deleted %s", rec.name)
            return True

    # ---- search ----------------------------------------------------------
    def vector_search(self, query: str, top_k: int, departments: set[str] | None) -> list[tuple[str, float]]:
        with self._lock:
            if not len(self._order):
                return []
            q = self.embedder.embed([query])[0]
            sims = self._vecs @ q
            if departments is not None:
                mask = np.array([self.chunks[c].department in departments for c in self._order])
                sims = np.where(mask, sims, -np.inf)
            idx = np.argsort(-sims)[:top_k]
            return [(self._order[i], float(sims[i])) for i in idx if np.isfinite(sims[i])]

    def keyword_search(self, query: str, top_k: int, departments: set[str] | None) -> list[tuple[str, float]]:
        with self._lock:
            return self.bm25.search(query, top_k, departments)

    def list_documents(self) -> list[DocumentRecord]:
        return sorted(self.docs.values(), key=lambda d: (d.department, d.name, -d.version))

    # ---- persistence -----------------------------------------------------
    def _load(self) -> None:
        state = self.persist.load()
        if not state:
            return
        chunks: list[Chunk] = state["chunks"]
        self.docs = {d["document_id"]: DocumentRecord(**d) for d in state["docs"]}
        self._order = [c.chunk_id for c in chunks]
        self.chunks = {c.chunk_id: c for c in chunks}
        self._vecs = state["vecs"] if len(chunks) else np.zeros((0, self.embedder.dimension), np.float32)
        self.bm25.add(chunks)
        fp = self.fingerprint_of(self.settings, self.embedder)
        if chunks and (state.get("fingerprint") != fp or self._vecs.shape[1] != self.embedder.dimension):
            log.warning("embedding model changed (%s -> %s): re-embedding %d chunks", state.get("fingerprint"), fp, len(chunks))
            self._vecs = self._embed_all([c.embedding_text for c in chunks])
            self.persist.replace_vectors(self)

    def _embed_all(self, texts: list[str], batch: int = 64) -> np.ndarray:
        parts = [self.embedder.embed(texts[i:i + batch]) for i in range(0, len(texts), batch)]
        return np.vstack(parts) if parts else np.zeros((0, self.embedder.dimension), np.float32)
