"""Core data models. Stdlib-only so the RAG core is portable and testable."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["heading", "paragraph", "table"]
ContentType = Literal["text", "table"]


@dataclass(frozen=True)
class Block:
    """A parsed structural unit from a document (output of the parser layer)."""

    kind: BlockKind
    page: int
    text: str = ""
    level: int = 1  # heading level (1 = top)
    rows: tuple[tuple[str, ...], ...] = ()  # tables: rows[0] is the header


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    document_name: str
    department: str
    page_start: int
    page_end: int
    section: str
    content_type: ContentType
    text: str
    table_id: str | None = None
    table_rows: int = 0  # total data rows of the source table (registers/logs are large)

    @property
    def embedding_text(self) -> str:
        """Text sent to the embedder/keyword index: content plus provenance context."""
        pages = (
            str(self.page_start)
            if self.page_start == self.page_end
            else f"{self.page_start}-{self.page_end}"
        )
        return (
            f"Document: {self.document_name} | Page: {pages} | "
            f"Section: {self.section or 'N/A'}\n{self.text}"
        )


@dataclass(frozen=True)
class Evidence:
    """A retrieved chunk presented to the LLM under a 1-based citation number."""

    source_id: int
    chunk: Chunk
    score: float = 0.0


@dataclass
class Issue:
    code: str
    message: str


@dataclass
class ValidationReport:
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    cited_sources: list[int] = field(default_factory=list)
