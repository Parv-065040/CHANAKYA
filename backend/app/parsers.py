"""Parser layer: PDF / XLSX / CSV -> list[Block]. Register new types in PARSERS."""
from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable

from .core.models import Block


class ParseError(ValueError):
    pass


_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+[A-Za-z].{0,80}$")
_CELL_SPLIT = re.compile(r"\s{2,}")


def _cells(line: str) -> tuple[str, ...]:
    return tuple(c.strip() for c in _CELL_SPLIT.split(line.strip()) if c.strip())


def _squeeze_table_gaps(lines: list[str]) -> list[str]:
    """Layout extraction inserts blank lines between padded table rows; drop blanks that sit
    between two rows with the same column count so the table stays one block."""
    idx = [i for i, ln in enumerate(lines) if ln.strip()]
    drop: set[int] = set()
    for a, b in zip(idx, idx[1:]):
        if b - a > 1:
            ca, cb = _cells(lines[a]), _cells(lines[b])
            if len(ca) >= 2 and len(ca) == len(cb):
                drop.update(range(a + 1, b))
    return [ln for i, ln in enumerate(lines) if i not in drop]


def _classify_pdf_lines(lines: list[str], page: int) -> list[Block]:
    lines = _squeeze_table_gaps(lines)
    blocks: list[Block] = []
    para: list[str] = []
    table: list[tuple[str, ...]] = []

    def flush_para() -> None:
        if para:
            blocks.append(Block("paragraph", page, " ".join(para)))
            para.clear()

    def flush_table() -> None:
        if len(table) >= 2:
            blocks.append(Block("table", page, rows=tuple(table)))
        elif table:  # a lone multi-cell line is prose
            para.append(" ".join(table[0]))
        table.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_table(); flush_para()
            continue
        cells = tuple(c.strip() for c in _CELL_SPLIT.split(line) if c.strip())
        if len(cells) >= 2:
            if table and len(cells) != len(table[0]):
                flush_table()
            flush_para()
            table.append(cells)
            continue
        flush_table()
        m = _HEADING_RE.match(line)
        if m and not line.endswith((".", ",")) and len(line) < 90:
            flush_para()
            blocks.append(Block("heading", page, line, level=m.group(1).count(".") + 1))
        else:
            para.append(line)
    flush_table(); flush_para()
    return blocks


def parse_pdf(data: bytes) -> list[Block]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = list(reader.pages)
    except (PdfReadError, ValueError, OSError) as exc:
        raise ParseError(f"invalid PDF: {exc}") from exc
    blocks: list[Block] = []
    for i, page in enumerate(pages, start=1):
        text = page.extract_text(extraction_mode="layout") or ""
        if len(text.strip()) < 20:
            text = _ocr_fallback(page)
        blocks.extend(_classify_pdf_lines(text.splitlines(), i))
    if not blocks:
        raise ParseError("no extractable text (scanned PDF? install OCR extras: pytesseract + pdf2image)")
    return blocks


def _ocr_fallback(page) -> str:  # noqa: ANN001
    """OCR hook for scanned pages; requires optional pytesseract. Returns '' if unavailable."""
    try:
        import pytesseract  # type: ignore
        from pypdf.generic import IndirectObject  # noqa: F401
    except ImportError:
        return ""
    images = list(getattr(page, "images", []))
    from PIL import Image  # type: ignore
    return "\n".join(pytesseract.image_to_string(Image.open(io.BytesIO(im.data))) for im in images)


def _rows_block(rows: list[list[str]], page: int, title: str) -> list[Block]:
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        return []
    width = max(len(r) for r in rows)
    norm = tuple(tuple(c.strip() for c in r) + ("",) * (width - len(r)) for r in rows)
    return [Block("heading", page, title, level=1), Block("table", page, rows=norm)]


def parse_csv(data: bytes) -> list[Block]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    rows = list(csv.reader(io.StringIO(text)))
    blocks = _rows_block(rows, 1, "CSV data")
    if not blocks:
        raise ParseError("CSV has no data rows")
    return blocks


def parse_xlsx(data: bytes) -> list[Block]:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception as exc:  # openpyxl raises many types
        raise ParseError(f"invalid XLSX: {exc}") from exc
    blocks: list[Block] = []
    for i, ws in enumerate(wb.worksheets, start=1):
        rows = [["" if v is None else (f"{v:g}" if isinstance(v, float) else str(v)) for v in r]
                for r in ws.iter_rows(values_only=True)]
        blocks.extend(_rows_block(rows, i, f"Sheet: {ws.title}"))
    if not blocks:
        raise ParseError("workbook has no data")
    return blocks


PARSERS: dict[str, Callable[[bytes], list[Block]]] = {
    ".pdf": parse_pdf, ".csv": parse_csv, ".xlsx": parse_xlsx,
}
MAGIC = {".pdf": b"%PDF", ".xlsx": b"PK"}


def parse_document(filename: str, data: bytes) -> list[Block]:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in PARSERS:
        raise ParseError(f"unsupported file type {ext!r}; supported: {', '.join(sorted(PARSERS))}")
    if not data:
        raise ParseError("empty file")
    if ext in MAGIC and not data.startswith(MAGIC[ext]):
        raise ParseError(f"file content does not look like {ext}")
    return PARSERS[ext](data)
