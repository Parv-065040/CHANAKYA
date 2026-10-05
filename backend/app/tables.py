"""Numerical/table agent: structured table reading, value extraction, calculations."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .core.keyword import QUERY_STOP, _stem, normalize_aliases, tokenize

TABLE_STOP = frozenset(_stem(w) for w in "did does do had has have from much many than between compared about into could would should can will their there any when who whom were been being during year time give tell show list provide value number amount level current per please s average mean avg median standard deviation std dev variance total sum aggregate combined count number minimum min lowest smallest maximum max highest largest greatest".split())
from .core.models import Evidence
from .core import numerics as nx

GROWTH = re.compile(r"\b(grew|grow|growth|increase[d]?|decrease[d]?|decline[d]?|change[d]?|percent(age)?|difference|compare[d]?|rise|rose|fell|higher|lower)\b", re.I)
STAT_AVG = re.compile(r"\b(average|mean|avg)\b", re.I)
STAT_MEDIAN = re.compile(r"\bmedian\b", re.I)
STAT_STD = re.compile(r"\b(std(?:\.|andard)?\s*dev(?:iation)?|standard\s*deviation|variance)\b", re.I)
STAT_SUM = re.compile(r"\b(total|sum|aggregate|combined)\b", re.I)
STAT_COUNT = re.compile(r"\b(count|number of|how many)\b", re.I)
STAT_MIN = re.compile(r"\b(minimum|min|lowest|smallest)\b", re.I)
STAT_MAX = re.compile(r"\b(maximum|max|highest|largest|greatest)\b", re.I)
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



def _chunk_table_rows(chunk) -> tuple[list[str], list[list[str]]]:
    """Parse one stored table chunk into its repeated header and body rows."""
    rows: list[list[str]] = []
    for ln in chunk.text.splitlines():
        ln = ln.strip()
        if ln.startswith("|") and not set(ln) <= set("|- :"):
            rows.append([c.strip() for c in ln.strip("|").split("|")])
    if len(rows) < 2:
        return [], []
    return rows[0], rows[1:]


def descriptive_statistics(query: str, evidence: list[Evidence], all_chunks) -> dict | None:
    """Compute descriptive statistics over the complete logical table."""
    if not (STAT_AVG.search(query) or STAT_MEDIAN.search(query) or
            STAT_STD.search(query) or STAT_SUM.search(query) or
            STAT_COUNT.search(query) or STAT_MIN.search(query) or STAT_MAX.search(query)):
        return None

    table_evidence = [ev for ev in evidence if ev.chunk.content_type == "table"]
    if not table_evidence:
        return None

    raw_tokens = set(tokenize(norm(re.sub(r"\([^)]*\)", " ", query))))
    stat_tokens = {
        "average", "mean", "avg", "median", "standard", "deviation",
        "std", "dev", "variance", "total", "sum", "aggregate", "combined",
        "count", "number", "minimum", "min", "lowest", "smallest",
        "maximum", "max", "highest", "largest", "greatest",
    }
    metric_tokens = raw_tokens - stat_tokens
    if not metric_tokens:
        return None

    candidates: list[tuple[float, TableView, int, list[Decimal], int]] = []
    seen_tables: set[str] = set()

    for ev in table_evidence:
        c = ev.chunk
        table_key = c.table_id or f"{c.document_id}:{c.section}:{c.document_name}"
        if table_key in seen_tables:
            continue
        seen_tables.add(table_key)

        matching = [
            x for x in all_chunks
            if x.content_type == "table"
            and (x.table_id or f"{x.document_id}:{x.section}:{x.document_name}") == table_key
        ]
        if not matching:
            matching = [c]

        header: list[str] = []
        rows: list[list[str]] = []
        seen_rows: set[tuple[str, ...]] = set()
        for chunk in sorted(matching, key=lambda x: (x.page_start, x.chunk_id)):
            h, body = _chunk_table_rows(chunk)
            if h and not header:
                header = h
            for row in body:
                key = tuple(row)
                if key not in seen_rows:
                    seen_rows.add(key)
                    rows.append(row)

        if not header or not rows:
            continue

        best_col: tuple[float, int] | None = None
        for ci, h in enumerate(header[1:], start=1):
            ht = set(qtokens(h))
            if not ht:
                continue
            overlap = len(ht & metric_tokens)
            score = (overlap / len(ht)) + 0.75 * (overlap / max(len(metric_tokens), 1))
            if overlap and (best_col is None or score > best_col[0]):
                best_col = (score, ci)

        if best_col is None:
            continue

        ci = best_col[1]
        values: list[Decimal] = []
        for row in rows:
            if ci >= len(row):
                continue
            try:
                values.append(nx.parse_quantity(row[ci]).value)
            except nx.NumericError:
                continue

        if values:
            tv = TableView(ev.source_id, c.document_name, header, rows, c.section)
            candidates.append((best_col[0], tv, ci, values, ev.source_id))

    if not candidates:
        return None

    _, tv, ci, values, sid = max(candidates, key=lambda x: (x[0], len(x[3])))
    n = len(values)
    total = sum(values, Decimal(0))
    mean = total / n
    ordered = sorted(values)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / Decimal(2)
    ss = sum((v - mean) ** 2 for v in values)
    population_std = (ss / Decimal(n)).sqrt()
    sample_std = (ss / Decimal(n - 1)).sqrt() if n > 1 else Decimal(0)

    if STAT_STD.search(query):
        if "variance" in query.lower() and not re.search(r"std|deviation", query, re.I):
            result = ss / Decimal(n)
            kind = "variance"
        else:
            result = sample_std
            kind = "standard deviation"
        return {
            "metric": tv.header[ci], "n": n, "value": result, "unit": "",
            "formula": f"{kind} over {n} values",
            "text": f"{kind.title()} for {tv.header[ci]}: {quantize(result, 4)} "
                    f"(sample; population standard deviation = {quantize(population_std, 4)}) "
                    f"over {n} numeric values [{sid}].",
            "source_id": sid, "kind": "std",
        }

    if STAT_AVG.search(query):
        return {
            "metric": tv.header[ci], "n": n, "value": mean, "unit": "",
            "formula": f"{quantize(total, 4)} / {n}",
            "text": f"Average {tv.header[ci]}: {quantize(mean, 4)} = {quantize(total, 4)} / {n} [{sid}].",
            "source_id": sid, "kind": "average",
        }

    if STAT_MEDIAN.search(query):
        return {
            "metric": tv.header[ci], "n": n, "value": median, "unit": "",
            "formula": f"median of {n} sorted values",
            "text": f"Median {tv.header[ci]}: {quantize(median, 4)} over {n} numeric values [{sid}].",
            "source_id": sid, "kind": "median",
        }

    if STAT_SUM.search(query):
        return {
            "metric": tv.header[ci], "n": n, "value": total, "unit": "",
            "formula": f"sum of {n} values",
            "text": f"Total {tv.header[ci]}: {quantize(total, 4)} over {n} numeric values [{sid}].",
            "source_id": sid, "kind": "sum",
        }

    if STAT_COUNT.search(query):
        return {
            "metric": tv.header[ci], "n": n, "value": Decimal(n), "unit": "",
            "formula": f"count of {n} numeric values",
            "text": f"Count of numeric {tv.header[ci]} values: {n} [{sid}].",
            "source_id": sid, "kind": "count",
        }

    if STAT_MIN.search(query):
        value = min(values)
        return {
            "metric": tv.header[ci], "n": n, "value": value, "unit": "",
            "formula": f"minimum of {n} values",
            "text": f"Minimum {tv.header[ci]}: {quantize(value, 4)} [{sid}].",
            "source_id": sid, "kind": "min",
        }

    if STAT_MAX.search(query):
        value = max(values)
        return {
            "metric": tv.header[ci], "n": n, "value": value, "unit": "",
            "formula": f"maximum of {n} values",
            "text": f"Maximum {tv.header[ci]}: {quantize(value, 4)} [{sid}].",
            "source_id": sid, "kind": "max",
        }

    return None

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
