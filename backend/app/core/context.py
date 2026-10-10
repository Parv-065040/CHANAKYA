"""Context builder and evidence-sufficiency gate."""
from __future__ import annotations

from collections.abc import Sequence

from .models import Chunk, Evidence

REFUSAL_MESSAGE = (
    "I could not find sufficient evidence for this question in the available "
    "CHANAKYA knowledge base."
)


def number_evidence(
    ranked: Sequence[tuple[Chunk, float]], *, top_k: int = 8, min_score: float = 0.0
) -> list[Evidence]:
    """Assign 1-based citation numbers to the best chunks above ``min_score``."""
    kept = [(c, s) for c, s in ranked if s >= min_score][:top_k]
    return [Evidence(i, c, s) for i, (c, s) in enumerate(kept, start=1)]


def is_sufficient(evidence: Sequence[Evidence]) -> bool:
    """Gate before calling the LLM: no evidence means refuse, never guess."""
    return len(evidence) > 0


def build_context(evidence: Sequence[Evidence], max_chars: int = 12000) -> str:
    """Render numbered evidence blocks the LLM must cite as [n]."""
    parts: list[str] = []
    used = 0
    for ev in evidence:
        c = ev.chunk
        pages = str(c.page_start) if c.page_start == c.page_end else f"{c.page_start}-{c.page_end}"
        block = (
            f"[{ev.source_id}] {c.document_name} | page {pages} | "
            f"section: {c.section or 'N/A'} | type: {c.content_type}\n{c.text}"
        )
        if used + len(block) > max_chars and parts:
            break
        parts.append(block)
        used += len(block)
    return "\n\n---\n\n".join(parts)


def format_sources(evidence: Sequence[Evidence], cited: Sequence[int]) -> list[dict[str, object]]:
    """Source list built only from real retrieved evidence (never from LLM text)."""
    by_id = {e.source_id: e for e in evidence}
    out: list[dict[str, object]] = []
    for sid in sorted(set(cited)):
        ev = by_id.get(sid)
        if ev is None:
            continue
        c = ev.chunk
        out.append({
            "source_id": sid,
            "chunk_id": c.chunk_id,
            "document_id": c.document_id,
            "document": c.document_name,
            "page": c.page_start if c.page_start == c.page_end else f"{c.page_start}-{c.page_end}",
            "page_start": c.page_start,
            "page_end": c.page_end,
            "section": c.section,
            "department": c.department,
            "content_type": c.content_type,
        })
    return out
