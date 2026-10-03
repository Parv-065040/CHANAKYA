"""Numerical/table agent: structured table reading, value extraction, calculations."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .core.keyword import QUERY_STOP, _stem, normalize_aliases, tokenize

TABLE_STOP = frozenset(_stem(w) for w in "did does do had has have from much many than between compared about into could would should can will their there any when who whom were been being during year time give tell show list provide value number amount level current per please s".split())
from .core.models import Evidence
from .core import numerics as nx

GROWTH = re.compile(r"\b(grew|grow|growth|increase[d]?|decrease[d]?|decline[d]?|change[d]?|percent(age)?|difference|compare[d]?|rise|rose|fell|higher|lower)\b", re.I)
SUPER_MAX = re.compile(r"\b(highest|largest|maximum|most|greatest|peak)\b", re.I)
SUPER_MIN = re.compile(r"\b(lowest|smallest|minimum|least)\b", re.I)
def norm(text: str) -> str:
    return normalize_aliases(text)


def qtokens(text: str) -> list[str]:
    return [t for t in tokenize(norm(re.sub(r"\([^)]*\)", " ", text))) if t not in TABLE_STOP]


@dataclass
class TableView:
    source_id: int
    document: str
    header: list[str]
    rows: list[list[str]]
    section: str = ""


@dataclass
class Fact:
    source_id: int
    document: str
    metric: str
    period: str
    raw: str
    score: float


def parse_tables(evidence: list[Evidence]) -> list[TableView]:
    out: list[TableView] = []
    for ev in evidence:
        if ev.chunk.content_type != "table":
            continue
        rows = []
        for ln in ev.chunk.text.splitlines():
            ln = ln.strip()
            if ln.startswith("|") and not set(ln) <= set("|- :"):
                rows.append([c.strip() for c in ln.strip("|").split("|")])
        if len(rows) >= 2:
            out.append(TableView(ev.source_id, ev.chunk.document_name, rows[0], rows[1:], ev.chunk.section))
    return out


def _overlap(label: str, qset: set[str]) -> float:
    lt = qtokens(label)
    return sum(t in qset for t in lt) / len(lt) if lt else 0.0


def _numeric(raw: str) -> Decimal | None:
    try:
        return nx.parse_quantity(raw).value
    except nx.NumericError:
        return None


_PERIOD = re.compile(r"^(fy ?\d{2,4}|q[1-4]\b|(apr|may|jun|jul|aug|sep|oct|nov|dec|jan|feb|mar)\b|w\d+|\d{4}$)", re.I)


def is_period(header_cell: str) -> bool:
    return bool(_PERIOD.match(header_cell.strip()))


def _period_hits(header: list[str], qset: set[str]) -> float:
    hits = [qtokens(h) for h in header[1:] if (ht := qtokens(h)) and set(ht) <= qset]
    return len(hits) + 0.15 * max((len(h) for h in hits), default=0)


_PERIOD_TOKEN = re.compile(r"^(fy\d{4}|q[1-4]|apr|may|jun|jul|aug|sep|oct|nov|dec|jan|feb|mar)$")


def _period_specificity(header: list[str], qset: set[str]) -> float:
    """+0.6 for every period the question names (Q3, FY2025, jun...) that appears in a column header."""
    wanted = {t for t in qset if _PERIOD_TOKEN.match(t)}
    if not wanted:
        return 0.0
    got = set()
    for h in header[1:]:
        got |= set(qtokens(h)) & wanted
    return 0.6 * len(got)


def find_row_facts(query: str, tables: list[TableView], *, keep_all_tiers: bool) -> tuple[list[Fact], list[tuple[TableView, list[str], float]]]:
    """Pick the best (table, row) by row-label match, column-period match and evidence rank."""
    qset = set(qtokens(query))
    cands: list[tuple[float, int, TableView, list[str], float]] = []
    for rank, tv in enumerate(tables):
        ph = _period_hits(tv.header, qset)
        ctx = set(qtokens(" ".join(tv.header))) | set(qtokens(tv.section))
        for row in tv.rows:
            s = _overlap(row[0], qset)
            lt = qtokens(row[0])
            if s >= 0.5 and any(re.search(r"[a-z]", t) for t in lt if t in qset):
                cset = {t for t in qset if t not in QUERY_STOP} or qset
                cover = len(cset & (set(lt) | ctx)) / len(cset)
                if cover < 0.5:
                    continue  # row matches by accident (e.g. 'G1' in a salary table for a notice-period question)
                extra = len([t for t in lt if t not in qset])
                s += 0.6 if (set(lt) & qset) & {t for t in qset if _PERIOD_TOKEN.match(t)} else 0.0
                cands.append((s + 0.4 * min(ph, 2.3) + _period_specificity(tv.header, qset) - 0.25 * extra - 0.01 * rank, rank, tv, row, s))
    if not cands:
        return [], []
    cands.sort(key=lambda c: -c[0])
    chosen: list[tuple[float, int, TableView, list[str], float]] = []
    if keep_all_tiers:
        # multi-concept question: greedily pick rows that cover *different* parts of the question
        remaining = {t for t in qset if t not in QUERY_STOP and not _PERIOD_TOKEN.match(t)}
        for c in cands:
            lt = set(qtokens(c[3][0]))
            if lt & remaining and all(set(qtokens(x[3][0])) != lt for x in chosen):
                chosen.append(c)
                remaining -= lt
            if len(chosen) >= 3 or not remaining:
                break
        if not chosen:
            chosen = cands[:1]
    else:
        chosen = cands[:1]
    facts: list[Fact] = []
    for _, _, tv, row, s in chosen:
        periods = [(i, h) for i, h in enumerate(tv.header) if 0 < i < len(row)]
        mentioned = [(i, h) for i, h in periods if (ht := qtokens(h)) and set(ht) <= qset]
        use = mentioned or periods
        if len(use) == 1 and use[0][0] > 1:  # single period named: compare with the previous column
            use = [(use[0][0] - 1, tv.header[use[0][0] - 1]), use[0]]
        for i, h in use:
            facts.append(Fact(tv.source_id, tv.document, row[0], h, row[i], s))
    return facts, [(c[2], c[3], c[4]) for c in chosen]


def superlative(query: str, tables: list[TableView]) -> tuple[str, str, str, int, str] | None:
    """'Which line had the highest defect rate?' -> (row label, column, value, source_id, doc).

    Requires the table's first column header to match the entity asked about ('line'), prefers
    columns with no extra qualifiers (Q1, FY...), and walks tables in evidence-rank order."""
    is_max, is_min = bool(SUPER_MAX.search(query)), bool(SUPER_MIN.search(query))
    if not (is_max or is_min):
        return None
    qset = set(qtokens(query))
    wants_total = "total" in query.lower()
    best: tuple[tuple, TableView, int, list] | None = None
    for rank, tv in enumerate(tables):
        if _overlap(tv.header[0], qset) < 0.5:
            continue
        for ci, h in enumerate(tv.header[1:], start=1):
            ht = qtokens(h)
            s = _overlap(h, qset)
            if s < 0.5 or not ht:
                continue
            vals = [(Decimal(str(v)), r) for r in tv.rows if ci < len(r) and (v := _numeric(r[ci])) is not None
                    and (wants_total or not r[0].lower().startswith("total"))]
            if not vals:
                continue
            key = (-len([t for t in ht if t not in qset]), s, len([t for t in ht if t in qset]), -rank)
            if best is None or key > best[0]:
                best = (key, tv, ci, vals)
    if best is None:
        return None
    _, tv, ci, vals = best
    v, row = (max if is_max else min)(vals, key=lambda t: t[0])
    return row[0], tv.header[ci], row[ci], tv.source_id, tv.document


def lookup_text_row(query: str, tables: list[TableView]) -> list[tuple[TableView, list[str]]]:
    """Non-numeric rows (e.g. SLA targets): the row label must match AND the table must cover
    >= 75% of the question's terms (header/section/row) so 'P1 SLA compliance in Apr' does not
    hit the P1 row of an unrelated targets table."""
    qset = set(qtokens(query))
    periods = {t for t in qset if _PERIOD_TOKEN.match(t)}
    hits = []
    for tv in tables:
        ctx = set(qtokens(" ".join(tv.header))) | set(qtokens(tv.section))
        for row in tv.rows:
            lt = qtokens(row[0])
            if not lt or _overlap(row[0], qset) < 1.0 or not any(re.search(r"[a-z]", t) for t in lt):
                continue
            if not all(_numeric(c) is None for c in row[1:]):
                continue
            cset = {t for t in qset if t not in QUERY_STOP} or qset
            if len(cset & (set(lt) | ctx)) / len(cset) < 0.75 or (periods - set(lt) - ctx):
                continue
            hits.append((tv, row))
    return hits
