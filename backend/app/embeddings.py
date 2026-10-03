"""Embedding abstraction. Swap via EMBEDDING_PROVIDER / EMBEDDING_MODEL / EMBEDDING_DIMENSION."""
from __future__ import annotations

import hashlib
import math
from typing import Protocol

import numpy as np

from .core.keyword import tokenize
from .config import Settings


class Embedder(Protocol):
    dimension: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


class HashingEmbedder:
    """Offline, deterministic, zero-download embedder (hashed unigrams+bigrams, sublinear TF).

    Lexical-semantic only: a development/offline default, not a BGE-M3 replacement.
    """

    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = dimension

    def _vec(self, text: str) -> np.ndarray:
        toks = tokenize(text)
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        v = np.zeros(self.dimension, dtype=np.float32)
        for f in feats:
            h = int(hashlib.md5(f.encode()).hexdigest(), 16)
            v[h % self.dimension] += (1.0 if (h >> 64) & 1 else -1.0) * 1.0
        v = np.sign(v) * np.sqrt(np.abs(v))
        n = float(np.linalg.norm(v))
        return v / n if n else v

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dimension), np.float32)


class SentenceTransformerEmbedder:
    """BGE-M3 (or any sentence-transformers model). Requires `pip install sentence-transformers`."""

    def __init__(self, model: str, dimension: int) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self._m = SentenceTransformer(model)
        self.dimension = int(self._m.get_sentence_embedding_dimension() or dimension)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self._m.encode(texts, normalize_embeddings=True, batch_size=16), dtype=np.float32)


class HFInferenceEmbedder:
    """BGE-M3 (or any feature-extraction model) via a Hugging Face Inference endpoint: no local torch.

    Set HF_API_TOKEN and HF_EMBED_URL (the model's feature-extraction endpoint). Not verified live.
    """

    def __init__(self, url: str, token: str, dimension: int) -> None:
        if not (url and token):
            raise ValueError("HF_EMBED_URL and HF_API_TOKEN are required for EMBEDDING_PROVIDER=hf-inference")
        self.url, self.token, self.dimension = url, token, dimension

    def embed(self, texts: list[str]) -> np.ndarray:
        import time

        import requests

        out: list[np.ndarray] = []
        for i in range(0, len(texts), 16):
            batch = texts[i:i + 16]
            for attempt in range(4):
                r = requests.post(self.url, headers={"Authorization": f"Bearer {self.token}"},
                                  json={"inputs": batch, "options": {"wait_for_model": True}}, timeout=120)
                if r.status_code in (429, 503) and attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    continue
                if r.status_code != 200:
                    raise RuntimeError(f"embedding endpoint error {r.status_code}")
                break
            arr = np.asarray(r.json(), dtype=np.float32)
            if arr.ndim == 3:  # token-level output: mean-pool
                arr = arr.mean(axis=1)
            if arr.ndim != 2 or arr.shape[0] != len(batch) or arr.shape[1] != self.dimension:
                raise RuntimeError(f"unexpected embedding shape {arr.shape}; expected ({len(batch)}, {self.dimension})")
            out.append(arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-12))
        return np.vstack(out) if out else np.zeros((0, self.dimension), np.float32)


def make_embedder(s: Settings) -> Embedder:
    if s.embedding_provider == "hashing":
        return HashingEmbedder(s.embedding_dimension)
    if s.embedding_provider in ("sentence-transformers", "bge-m3"):
        return SentenceTransformerEmbedder(s.embedding_model, s.embedding_dimension)
    if s.embedding_provider == "hf-inference":
        return HFInferenceEmbedder(s.hf_embed_url, s.hf_token, s.embedding_dimension)
    raise ValueError(f"unknown EMBEDDING_PROVIDER {s.embedding_provider!r}")
