"""Storage backends for the knowledge base: local files (default) or Supabase (PostgREST + pgvector).

Search itself runs in memory over vectors loaded at startup (fine for ~10^4 chunks); the backend is
the durable system of record, so containers can be stateless (free-tier friendly).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

import numpy as np
import requests

from .core.models import Chunk

log = logging.getLogger("chanakya.persistence")


class Persistence(Protocol):
    def load(self) -> dict | None: ...
    def save_document(self, kb, rec, chunks: list[Chunk], vecs: np.ndarray, raw: bytes, superseded: list) -> None: ...
    def delete_document(self, kb, document_id: str) -> None: ...
    def replace_vectors(self, kb) -> None: ...


class LocalPersistence:
    """JSON metadata + .npy vectors + raw files; full snapshot on every change."""

    def __init__(self, directory: Path, fingerprint: str) -> None:
        self.dir, self.fp = Path(directory), fingerprint
        (self.dir / "files").mkdir(parents=True, exist_ok=True)

    def load(self) -> dict | None:
        mp, vp = self.dir / "meta.json", self.dir / "vectors.npy"
        if not (mp.exists() and vp.exists()):
            return None
        meta = json.loads(mp.read_text())
        return {"docs": meta["docs"], "chunks": [Chunk(**c) for c in meta["chunks"]], "vecs": np.load(vp), "fingerprint": meta.get("fingerprint", "")}

    def _snapshot(self, kb) -> None:
        meta = {"docs": [asdict(d) for d in kb.docs.values()], "chunks": [asdict(kb.chunks[c]) for c in kb._order], "fingerprint": self.fp}
        tmp = self.dir / "meta.json.tmp"
        tmp.write_text(json.dumps(meta))
        np.save(self.dir / "vectors.npy", kb._vecs)
        tmp.replace(self.dir / "meta.json")

    def save_document(self, kb, rec, chunks, vecs, raw, superseded) -> None:
        (self.dir / "files" / f"{rec.document_id}_{rec.name}").write_bytes(raw)
        self._snapshot(kb)

    def delete_document(self, kb, document_id: str) -> None:
        for f in (self.dir / "files").glob(f"{document_id}_*"):
            f.unlink(missing_ok=True)
        self._snapshot(kb)

    def replace_vectors(self, kb) -> None:
        self._snapshot(kb)


class SupabasePersistence:
    """Supabase via PostgREST. Requires the tables in sql/schema.sql and a SERVER-SIDE service-role key.

    NOTE: written against the documented PostgREST/Storage REST API and exercised only against a local
    stub server in tests; not verified against a live Supabase project.
    """

    BATCH = 100

    def __init__(self, url: str, service_key: str, bucket: str, fingerprint: str) -> None:
        self.base = url.rstrip("/")
        self.bucket, self.fp = bucket, fingerprint
        self.h = {"apikey": service_key, "Authorization": f"Bearer {service_key}", "Content-Type": "application/json"}

    # -- low-level
    def _req(self, method: str, path: str, **kw):
        for attempt in range(3):
            try:
                r = requests.request(method, f"{self.base}{path}", headers={**self.h, **kw.pop("headers", {})}, timeout=60, **kw)
            except requests.RequestException as exc:
                if attempt == 2:
                    raise RuntimeError(f"Supabase unreachable: {exc.__class__.__name__}") from exc
                time.sleep(1 + attempt)
                continue
            if r.status_code >= 500 and attempt < 2:
                time.sleep(1 + attempt)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"Supabase {method} {path} -> {r.status_code}: {r.text[:200]}")
            return r
        raise RuntimeError("unreachable")

    @staticmethod
    def _vec_str(v: np.ndarray) -> str:
        return "[" + ",".join(f"{x:.6g}" for x in v.tolist()) + "]"

    def _page(self, table: str, order: str) -> list[dict]:
        out: list[dict] = []
        offset = 0
        while True:
            r = self._req("GET", f"/rest/v1/{table}?select=*&order={order}&limit=500&offset={offset}")
            rows = r.json()
            out += rows
            if len(rows) < 500:
                return out
            offset += 500

    # -- interface
    def load(self) -> dict | None:
        docs = self._page("documents", "document_id")
        if not docs:
            return None
        rows = self._page("chunks", "document_id,chunk_id")
        fields = Chunk.__dataclass_fields__.keys()
        chunks = [Chunk(**{k: row[k] for k in fields if k in row}) for row in rows]
        vecs = np.array([json.loads(row["embedding"]) if isinstance(row["embedding"], str) else row["embedding"] for row in rows], dtype=np.float32)
        if len(vecs) == 0:
            vecs = np.zeros((0, 1), np.float32)
        meta = self._req("GET", "/rest/v1/app_meta?key=eq.fingerprint&select=value").json()
        dkeys = {"document_id", "name", "department", "version", "status", "size_bytes", "n_chunks", "n_tables", "pages", "sha256", "uploaded_at", "error"}
        return {"docs": [{k: d[k] for k in dkeys if k in d} for d in docs], "chunks": chunks, "vecs": vecs,
                "fingerprint": meta[0]["value"] if meta else ""}

    def save_document(self, kb, rec, chunks, vecs, raw, superseded) -> None:
        for old in superseded:
            self._req("PATCH", f"/rest/v1/documents?document_id=eq.{old.document_id}", json={"status": "superseded"})
            self._req("DELETE", f"/rest/v1/chunks?document_id=eq.{old.document_id}")
        self._req("POST", "/rest/v1/documents", json=[asdict(rec)], headers={"Prefer": "resolution=merge-duplicates"})
        for i in range(0, len(chunks), self.BATCH):
            rows = [{**asdict(c), "embedding": self._vec_str(v)} for c, v in zip(chunks[i:i + self.BATCH], vecs[i:i + self.BATCH])]
            self._req("POST", "/rest/v1/chunks", json=rows, headers={"Prefer": "resolution=merge-duplicates"})
        self._req("POST", "/rest/v1/app_meta", json=[{"key": "fingerprint", "value": self.fp}], headers={"Prefer": "resolution=merge-duplicates"})
        try:
            self._req("POST", f"/storage/v1/object/{self.bucket}/{rec.document_id}_{rec.name}", data=raw,
                      headers={"Content-Type": "application/octet-stream", "x-upsert": "true"})
        except RuntimeError as exc:  # raw-file archive is best effort; index is the source of truth
            log.warning("raw file upload skipped: %s", exc)

    def delete_document(self, kb, document_id: str) -> None:
        self._req("DELETE", f"/rest/v1/chunks?document_id=eq.{document_id}")
        self._req("DELETE", f"/rest/v1/documents?document_id=eq.{document_id}")

    def replace_vectors(self, kb) -> None:
        for i in range(0, len(kb._order), self.BATCH):
            ids = kb._order[i:i + self.BATCH]
            rows = [{**asdict(kb.chunks[c]), "embedding": self._vec_str(kb._vecs[i + j])} for j, c in enumerate(ids)]
            self._req("POST", "/rest/v1/chunks", json=rows, headers={"Prefer": "resolution=merge-duplicates"})
        self._req("POST", "/rest/v1/app_meta", json=[{"key": "fingerprint", "value": self.fp}], headers={"Prefer": "resolution=merge-duplicates"})
