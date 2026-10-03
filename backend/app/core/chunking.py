"""Structure-aware chunking that never loses page/section provenance.

* Headings update the section path and force a chunk boundary.
* Paragraphs are packed up to ``max_chars``; oversize paragraphs are split on
  sentence boundaries; a tiny trailing piece is merged into its predecessor.
* Tables are never mixed with prose. They are rendered as Markdown with a
  context header; oversize tables split by rows with the header row repeated.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .models import Block, Chunk

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9₹(])")


@dataclass(frozen=True)
class ChunkingConfig:
    max_chars: int = 1200
    min_chars: int = 250

    def __post_init__(self) -> None:
        if self.min_chars <= 0 or self.max_chars <= self.min_chars:
            raise ValueError("require 0 < min_chars < max_chars")


def split_text(text: str, max_chars: int, min_chars: int) -> list[str]:
    """Greedy sentence packing; hard-splits sentences longer than max_chars."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_RE.split(text.strip()):
        while len(sentence) > max_chars:  # pathological: no sentence breaks
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            pieces.append(current)
            current = sentence
    if current:
        pieces.append(current)
    if len(pieces) > 1 and len(pieces[-1]) < min_chars:
        merged = f"{pieces[-2]} {pieces[-1]}"
        if len(merged) <= int(max_chars * 1.25):
            pieces[-2:] = [merged]
    return pieces


def render_table(rows: tuple[tuple[str, ...], ...]) -> str:
    """Render rows (header first) as a Markdown table."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [tuple(r) + ("",) * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(norm[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return "\n".join(lines)


def _split_table_rows(
    rows: tuple[tuple[str, ...], ...], max_chars: int
) -> list[tuple[tuple[str, ...], ...]]:
    header, body = rows[0], rows[1:]
    groups: list[list[tuple[str, ...]]] = []
    current: list[tuple[str, ...]] = []
    for row in body:
        trial = render_table((header, *current, row))
        if current and len(trial) > max_chars:
            groups.append(current)
            current = []
        current.append(row)
    if current or not groups:
        groups.append(current)
    return [(header, *g) for g in groups]


class StructureAwareChunker:
    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    def chunk(
        self,
        blocks: list[Block],
        *,
        document_id: str,
        document_name: str,
        department: str,
    ) -> list[Chunk]:
        cfg = self.config
        out: list[Chunk] = []
        # Tables that continue across pages (consecutive table blocks, same header) form one logical table.
        group_rows: dict[int, int] = {}
        group_id: dict[int, int] = {}
        gid, prev_hdr = -1, None
        for i, b in enumerate(blocks):
            if b.kind != "table" or not b.rows:
                prev_hdr = None
                continue
            if b.rows[0] != prev_hdr:
                gid += 1
            group_id[i] = gid
            group_rows[gid] = group_rows.get(gid, 0) + len(b.rows) - (0 if b.rows[0] != prev_hdr else 1)
            prev_hdr = b.rows[0]
        group_tid: dict[int, str] = {}
        heading_path: list[tuple[int, str]] = []
        buffer: list[Block] = []
        table_count = 0

        def section() -> str:
            return " > ".join(t for _, t in heading_path)

        def emit(text: str, p0: int, p1: int, ctype: str, table_id: str | None = None, n_rows: int = 0) -> None:
            idx = len(out)
            cid = hashlib.sha1(f"{document_id}:{idx}".encode()).hexdigest()[:16]
            out.append(
                Chunk(cid, document_id, document_name, department, p0, p1,
                      section(), ctype, text, table_id, n_rows)  # type: ignore[arg-type]
            )

        def flush() -> None:
            if not buffer:
                return
            # Pack paragraphs; remember each paragraph's page for provenance.
            units: list[tuple[str, int]] = []
            for b in buffer:
                for piece in split_text(b.text, cfg.max_chars, cfg.min_chars):
                    units.append((piece, b.page))
            cur_text, p0, p1 = "", 0, 0
            for piece, page in units:
                cand = f"{cur_text}\n\n{piece}" if cur_text else piece
                if cur_text and len(cand) > cfg.max_chars:
                    emit(cur_text, p0, p1, "text")
                    cur_text, p0, p1 = piece, page, page
                else:
                    if not cur_text:
                        p0 = page
                    cur_text, p1 = cand, page
            if cur_text:
                emit(cur_text, p0, p1, "text")
            buffer.clear()

        for bi, block in enumerate(blocks):
            if block.kind == "heading":
                flush()
                while heading_path and heading_path[-1][0] >= block.level:
                    heading_path.pop()
                heading_path.append((block.level, block.text.strip()))
            elif block.kind == "paragraph":
                if block.text.strip():
                    buffer.append(block)
            elif block.kind == "table":
                flush()
                if not block.rows:
                    continue
                g = group_id[bi]
                if g not in group_tid:
                    table_count += 1
                    group_tid[g] = hashlib.sha1(f"{document_id}:t{table_count}".encode()).hexdigest()[:12]
                table_id = group_tid[g]
                for part in _split_table_rows(block.rows, cfg.max_chars):
                    body = (
                        f"Document: {document_name}\nPage: {block.page}\n"
                        f"Section: {section() or 'N/A'}\n\nTable:\n{render_table(part)}"
                    )
                    emit(body, block.page, block.page, "table", table_id, group_rows[g] - 1)
        flush()
        return out
