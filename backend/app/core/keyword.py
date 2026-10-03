"""In-memory BM25 keyword retriever with department filtering.

Tokenizer keeps decimals/identifiers intact ("148.2", "FY2025", "P-1") so
exact-match queries on numbers, KPIs and IDs work. Production deployments can
back the same ``KeywordRetriever`` interface with PostgreSQL full-text search.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Collection

from .models import Chunk

_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*|[a-z0-9]+(?:-[a-z0-9]+)*")
_ALIAS = re.compile(r"priority-?\s?(\d)", re.I)
_QUERY_WORDS = ("a an did does do had has have from much many than between compared about into could would should can will their there any when who whom were been being during year calculate percentage percent increased decreased increase decrease higher lower coincide rise rose fell grew grow growth difference compare change changed ratio highest lowest most least average s time give tell show list provide value number amount level current per please".split())



def normalize_aliases(text: str) -> str:
    """Map 'Priority-1' -> 'p1' so tables and prose share vocabulary."""
    return _ALIAS.sub(lambda m: f"p{m.group(1)}", text.lower())
_STOP = frozenset(
    "s t the of in on for to and or is are was were be by with at as its this that what which how".split()
)


_LINE_ID = re.compile(r"\b(line|machine|plant|shift|tier|grade|zone|unit)[\s-]+([a-z]|\d{1,3})\b")


_MONTHS = {"january": "jan", "february": "feb", "march": "mar", "april": "apr", "june": "jun", "july": "jul",
           "august": "aug", "september": "sep", "sept": "sep", "october": "oct", "november": "nov", "december": "dec"}
_MONTH_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\b")
_FY_RE = re.compile(r"\bfy\s?(\d{4})\b")


def _norm(text: str) -> str:
    """Lowercase and unify identifiers: 'Priority-1' -> 'p1', 'Line A' -> 'line-a',
    'June' -> 'jun', 'FY 2025' -> 'fy2025'."""
    t = _FY_RE.sub(r"fy\1", normalize_aliases(text))
    t = _MONTH_RE.sub(lambda m: _MONTHS[m.group(1)], t)
    return _LINE_ID.sub(r"\1-\2", t)


def _stem(t: str) -> str:
    """Light, symmetric suffix folding so singular/plural/tense variants share one form:
    rate/rates -> rat, produce/produced -> produc, units -> unit."""
    if len(t) <= 3 or not t.isalpha():
        return t
    for suf in ("ing", "ed"):
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            t = t[: -len(suf)]
            break
    if t.endswith("s") and not t.endswith(("ss", "us", "is")) and len(t) > 3:
        t = t[:-1]
    return t[:-1] if t.endswith("e") and len(t) > 3 else t


QUERY_STOP = frozenset(_stem(w) for w in _QUERY_WORDS)  # compared against already-stemmed tokens


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN_RE.findall(_norm(text)) if t not in _STOP]


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._chunks: dict[str, Chunk] = {}
        self._tf: dict[str, Counter[str]] = {}
        self._len: dict[str, int] = {}
        self._df: Counter[str] = Counter()
        self._total_len = 0

    def __len__(self) -> int:
        return len(self._chunks)

    def add(self, chunks: Collection[Chunk]) -> None:
        for c in chunks:
            if c.chunk_id in self._chunks:
                self.remove_document_chunk(c.chunk_id)
            toks = tokenize(c.embedding_text)
            tf = Counter(toks)
            self._chunks[c.chunk_id] = c
            self._tf[c.chunk_id] = tf
            self._len[c.chunk_id] = len(toks)
            self._total_len += len(toks)
            self._df.update(tf.keys())

    def remove_document_chunk(self, chunk_id: str) -> None:
        tf = self._tf.pop(chunk_id, None)
        if tf is None:
            return
        self._df.subtract(tf.keys())
        self._total_len -= self._len.pop(chunk_id)
        del self._chunks[chunk_id]

    def remove_document(self, document_id: str) -> None:
        for cid in [c.chunk_id for c in self._chunks.values() if c.document_id == document_id]:
            self.remove_document_chunk(cid)

    def search(
        self,
        query: str,
        top_k: int = 10,
        departments: Collection[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Return (chunk_id, score) best-first. ``departments`` is an allow-list."""
        n = len(self._chunks)
        if n == 0:
            return []
        avgdl = self._total_len / n or 1.0
        q_terms = set(tokenize(query))
        scored: list[tuple[str, float]] = []
        for cid, tf in self._tf.items():
            if departments is not None and self._chunks[cid].department not in departments:
                continue
            score = 0.0
            dl = self._len[cid]
            for t in q_terms:
                f = tf.get(t, 0)
                if not f:
                    continue
                df = self._df[t]
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / avgdl))
            if score > 0:
                scored.append((cid, score))
        scored.sort(key=lambda kv: (-kv[1], kv[0]))
        return scored[:top_k]

    def get(self, chunk_id: str) -> Chunk:
        return self._chunks[chunk_id]
