"""Agentic orchestrator: Router -> Retrieval -> Numerical/Table -> Answer -> Citation validator."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal

from .core import numerics as nx
from .core.citations import validate_answer
from .core.context import REFUSAL_MESSAGE, build_context, format_sources, is_sufficient, number_evidence
from .core.keyword import tokenize
from .core.models import Evidence
from .core.router import DEFAULT_DEPARTMENTS, route_query
from .llm import GroqClient, LLMUnavailable
from .retrieval import HybridRetriever
from .store import KnowledgeBase
from . import tables as T

log = logging.getLogger("chanakya.pipeline")


def _unit(header: str) -> str:
    m = re.search(r"[(]([^)]*)[)]", header)
    if not m:
        return ""
    u = m.group(1).strip()
    return "%" if u == "%" else f" ({u})"


@dataclass
class Calc:
    label: str
    result: nx.CalcResult
    text: str


@dataclass
class QueryResult:
    answer: str
    sources: list[dict]
    calculations: list[str]
    evidence: list[dict]
    route: dict
    mode: str  # llm | offline | refusal
    grounded: bool
    issues: list[str] = field(default_factory=list)
    notice: str = ""
    latency_ms: int = 0


class Orchestrator:
    def __init__(self, kb: KnowledgeBase, retriever: HybridRetriever, llm: GroqClient) -> None:
        self.kb, self.retriever, self.llm = kb, retriever, llm

    # ---- public ----------------------------------------------------------
    def ask(self, question: str, *, department: str | None = None, allowed: set[str] | None = None) -> QueryResult:
        t0 = time.time()
        q = question.strip()
        plan = route_query(q, selected_department=department or None, allowed_departments=allowed)
        route = {"departments": list(plan.departments), "question_type": plan.question_type, "notes": plan.notes}
        retrieved = self.retriever.retrieve(q, plan, allowed=allowed)
        evidence = number_evidence([(r.chunk, r.score) for r in retrieved], top_k=plan.top_k)
        if not is_sufficient(evidence):
            return self._done(QueryResult(REFUSAL_MESSAGE, [], [], [], route, "refusal", True), t0)

        calcs, facts_text, offline_body = self._numerical_agent(q, evidence, plan.question_type)
        calc_lines = [c.text for c in calcs]
        calc_vals = [v for c in calcs for v in (c.result.value, abs(c.result.value))]
        notice = ""
        answer, mode = "", "offline"
        if self.llm.available:
            try:
                raw = self.llm.complete(q, build_context(evidence), "\n".join(calc_lines + facts_text))
                rep = validate_answer(raw, evidence, calc_values=calc_vals, question=q)
                if rep.ok:
                    answer, mode = raw, "llm"
                else:
                    notice = "LLM answer failed grounding validation; showing verified evidence-based answer."
                    log.warning("validation failed: %s", [i.code for i in rep.issues])
            except LLMUnavailable as exc:
                notice = f"LLM unavailable ({exc}); showing evidence-based answer."
        else:
            notice = "Offline mode (no GROQ_API_KEY): deterministic evidence-based answer."
        if not answer:
            answer = offline_body or self._extractive(q, evidence)
        rep = validate_answer(answer, evidence, calc_values=calc_vals, question=q)
        sources = format_sources(evidence, rep.cited_sources or [e.source_id for e in evidence[:3]])
        result = QueryResult(
            answer=answer, sources=sources, calculations=calc_lines,
            evidence=[{"source_id": e.source_id, "document": e.chunk.document_name, "page": e.chunk.page_start,
                       "section": e.chunk.section, "type": e.chunk.content_type, "score": round(e.score, 3),
                       "text": e.chunk.text[:600]} for e in evidence],
            route=route, mode=mode, grounded=rep.ok, issues=[i.message for i in rep.issues], notice=notice)
        return self._done(result, t0)

    @staticmethod
    def _done(r: QueryResult, t0: float) -> QueryResult:
        r.latency_ms = int((time.time() - t0) * 1000)
        return r

    # ---- numerical / table agent ----------------------------------------
    def _numerical_agent(self, q: str, evidence: list[Evidence], qtype: str) -> tuple[list[Calc], list[str], str]:
        tables = T.parse_tables(evidence)
        if not tables:
            return [], [], ""
        sup = T.superlative(q, tables)
        if sup:
            label, col, val, sid, _doc = sup
            kind = "highest" if T.SUPER_MAX.search(q) else "lowest"
            unit = "%" if "(%)" in col else ""
            return [], [], f"{label} had the {kind} {col.replace(' (%)', '')} at {val}{unit} [{sid}]."
        multi = qtype in ("multi_document", "cross_department")
        rows = T.lookup_text_row(q, tables)
        if rows:
            tv, row = rows[0]
            parts = "; ".join(f"{h}: {c}" for h, c in zip(tv.header[1:], row[1:]))
            return [], [], f"{row[0]} - {parts} [{tv.source_id}]."
        facts, _ = T.find_row_facts(q, tables, keep_all_tiers=multi)
        if not facts:
            return [], [], ""
        if not any(T.is_period(f.period) for f in facts):  # e.g. leave table: column = attribute, not period
            f0 = facts[0]
            attrs = "; ".join(f"{re.sub(r' *[(].*?[)]', '', f.period)}: {f.raw}{_unit(f.period)}" for f in facts)
            return [], [], f"{f0.metric} - {attrs} [{f0.source_id}]."
        by_metric: dict[tuple[int, str], list[T.Fact]] = {}
        for f in facts:
            by_metric.setdefault((f.source_id, f.metric), []).append(f)
        want_calc = bool(T.GROWTH.search(q)) or multi
        calcs: list[Calc] = []
        sentences: list[str] = []
        directions: list[tuple[str, int]] = []
        for (sid, metric), fs in by_metric.items():
            clean = metric.replace(" (%)", "").replace(" (units)", "")
            suffix = "%" if "(%)" in metric else ""
            vals = f"{clean} was " + " and ".join(f"{f.raw}{suffix} in {re.sub(r' *[(].*?[)]', '', f.period)}" for f in fs)
            sentences.append(f"{vals} [{sid}].")
            if want_calc and len(fs) >= 2:
                old, new = fs[0], fs[-1]
                try:
                    oq, nq = nx.parse_quantity(old.raw, sid), nx.parse_quantity(new.raw, sid)
                    pc = nx.percent_change(nq, oq)
                    pts = nx.difference(nq, oq)
                except nx.NumericError:
                    continue
                unit_pct = "(%)" in metric
                calcs.append(Calc(f"{clean} {old.period}->{new.period}", pc,
                                  f"{clean}: {pc.formula} = {pc.display()} ({old.period} to {new.period})"))
                calcs.append(Calc(f"{clean} points", pts, f"{clean}: difference = {pts.formula} = {nx.quantize(pts.value, 2)}"))
                sentences.append(f"{clean} changed by {nx.quantize(pc.value)}% from {old.period} to {new.period}"
                                 + (f" ({nx.quantize(pts.value, 1)} percentage points)" if unit_pct else "") + f" [{sid}].")
                directions.append((clean, 1 if pc.value > 0 else -1 if pc.value < 0 else 0))
        if multi and len(directions) >= 2:
            same = len({d for _, d in directions if d != 0}) == 1 and all(d != 0 for _, d in directions)
            names = " and ".join(n for n, _ in directions[:2])
            sentences.append(("Yes - " + names + " moved in the same direction over the period, which is consistent with a coincidence"
                              " (this does not by itself establish causation).") if same else
                             f"No - {names} did not move in the same direction over the period.")
        return calcs, [s for s in sentences], " ".join(sentences)

    @staticmethod
    def _extractive(q: str, evidence: list[Evidence]) -> str:
        qs = set(tokenize(q))
        best: list[tuple[float, str, int]] = []
        for ev in evidence[:4]:
            for s in re.split(r"(?<=[.!?])\s+", ev.chunk.text):
                if ev.chunk.content_type == "table" or len(s) < 25:
                    continue
                ts = set(tokenize(s))
                if ts:
                    best.append((len(qs & ts) / (len(qs) or 1), s.strip(), ev.source_id))
        best.sort(key=lambda t: -t[0])
        picks = [b for b in best[:2] if b[0] > 0]
        if not picks:
            ev = evidence[0]
            return f"The most relevant evidence is in {ev.chunk.document_name}, page {ev.chunk.page_start} [{ev.source_id}]."
        return " ".join(f"{s} [{sid}]" if not s.endswith("]") else s for _, s, sid in picks)
