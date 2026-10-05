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
        stat = T.descriptive_statistics(q, evidence, self.kb.chunks.values())
        if stat:
            stat_result = nx.CalcResult(
                stat["value"],
                stat.get("unit", ""),
                stat["formula"],
                (stat["source_id"],),
            )
            calcs.append(Calc(stat["kind"], stat_result, stat["text"]))
            facts_text.append(stat["text"])
            offline_body = stat["text"] + (f" {offline_body}" if offline_body else "")
        calc_lines = [c.text for c in calcs]
        calc_vals = [v for c in calcs for v in (c.result.value, abs(c.result.value))]
        notice = ""
        answer, mode = "", "offline"
        if self.llm.available:
            try:
                raw = self.llm.complete(q, build_context(evidence), "\n".join(calc_lines + facts_text))
                rep = validate_answer(raw, evidence, calc_values=calc_vals, question=q)
                llm_refused = raw.strip() == REFUSAL_MESSAGE or raw.strip().startswith(REFUSAL_MESSAGE)
                if rep.ok and not llm_refused:
                    answer, mode = raw, "llm"
                else:
                    notice = "LLM refused or failed grounding validation; showing verified evidence-based answer."
                    log.warning("LLM answer rejected: refused=%s issues=%s", llm_refused, [i.code for i in rep.issues])
            except LLMUnavailable as exc:
                notice = f"LLM unavailable ({exc}); showing evidence-based answer."
        else:
            notice = "Offline mode (no GROQ_API_KEY): deterministic evidence-based answer."
        if stat:
            answer = offline_body or stat["text"]
            mode = "offline"
        elif not answer:
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

        # Targeted SLA priority lookup.
        # SLA tables use priority-specific columns such as
        # "P1 First Response", "P2 First Response", etc.,
        # rather than normal period columns.
        priority_match = re.search(r"\b(P[1-4])\b", q, re.I)
        if priority_match:
            priority = priority_match.group(1).upper()
            q_lower = q.lower()

            wants_first_response = (
                "first response" in q_lower
                or "response time" in q_lower
            )
            wants_resolution = (
                "resolution target" in q_lower
                or "resolution time" in q_lower
            )

            if wants_first_response or wants_resolution:
                target_words = (
                    ("first", "response")
                    if wants_first_response
                    else ("resolution",)
                )

                for tv in tables:
                    matched_col = None

                    for ci, header in enumerate(tv.header[1:], start=1):
                        h = header.lower()
                        if priority.lower() in h and all(
                            word in h for word in target_words
                        ):
                            matched_col = ci
                            break

                    if matched_col is not None:
                        values = []
                        for row in tv.rows:
                            if matched_col < len(row):
                                values.append(
                                    f"{row[0]}: {row[matched_col]}"
                                )

                        if values:
                            return (
                                [],
                                [],
                                f"{priority} "
                                f"{'first response' if wants_first_response else 'resolution target'} "
                                f"- "
                                + "; ".join(values)
                                + f" [{tv.source_id}]."
                            )

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

        is_comparison = qtype == "comparison"

        # Handle explicit comparisons deterministically.
        # Prefer facts from the period explicitly named in the question.
        if is_comparison:
            comparison_facts = facts

            requested_periods = [
                f.period for f in facts
                if re.search(r"\b(?:FY|Q)[0-9]{2,4}\b", f.period, re.I)
                and re.search(re.escape(f.period), q, re.I)
            ]

            if requested_periods:
                requested_period = requested_periods[0]
                filtered = [
                    f for f in facts
                    if f.period.lower() == requested_period.lower()
                ]
                if len(filtered) >= 2:
                    comparison_facts = filtered

            # Keep one value per metric for the requested period.
            comparison_values: list[tuple[str, float, str, int]] = []
            seen_metrics: set[str] = set()

            for f in comparison_facts:
                metric = f.metric.replace(" (%)", "").replace(" (units)", "")
                if metric in seen_metrics:
                    continue
                try:
                    value = nx.parse_quantity(f.raw, f.source_id).value
                except nx.NumericError:
                    continue
                seen_metrics.add(metric)
                comparison_values.append(
                    (metric, float(value), f.raw, f.source_id)
                )

            if len(comparison_values) >= 2:
                left = comparison_values[0]
                right = comparison_values[1]

                if left[1] > right[1]:
                    relation = "higher than"
                elif left[1] < right[1]:
                    relation = "lower than"
                else:
                    relation = "equal to"

                comparison_sentence = (
                    f"{left[0]} was {left[2]} and {right[0]} was {right[2]}; "
                    f"{left[0]} was {relation} {right[0]} [{left[3]}]."
                )

                return [], [comparison_sentence], comparison_sentence

        want_calc = (
            bool(T.GROWTH.search(q))
            or bool(re.search(
                r"\b(total|overall|aggregate|combined|sum|annual total|yearly total)\b",
                q,
                re.I,
            ))
        )

        calcs: list[Calc] = []
        sentences: list[str] = []
        directions: list[tuple[str, int]] = []

        for (sid, metric), fs in by_metric.items():

            if (
                bool(re.search(
                    r"\b(total|overall|aggregate|combined|sum|annual total|yearly total)\b",
                    q,
                    re.I,
                ))
                and len(fs) >= 2
                and all(T.is_period(f.period) for f in fs)
            ):
                try:
                    quantities = [nx.parse_quantity(f.raw, sid) for f in fs]
                    total_value = sum(q.value for q in quantities)
                    total = nx.parse_quantity(str(total_value), sid)

                    clean = metric.replace(" (%)", "").replace(" (units)", "")
                    components = " + ".join(f.raw for f in fs)

                    calcs.append(
                        Calc(
                            f"{clean} total",
                            total,
                            f"{clean} total: {components} = {nx.quantize(total.value, 2)}"
                        )
                    )

                    sentences.append(
                        f"{clean} total was {nx.quantize(total.value, 2)} [{sid}]."
                    )
                except nx.NumericError:
                    pass

            clean = metric.replace(" (%)", "").replace(" (units)", "")
            suffix = "%" if "(%)" in metric else ""
            vals = f"{clean} was " + " and ".join(
                f"{f.raw}{suffix} in {re.sub(r' *[(].*?[)]', '', f.period)}"
                for f in fs
            )
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
                calcs.append(
                    Calc(
                        f"{clean} {old.period}->{new.period}",
                        pc,
                        f"{clean}: {pc.formula} = {pc.display()} ({old.period} to {new.period})"
                    )
                )
                calcs.append(
                    Calc(
                        f"{clean} points",
                        pts,
                        f"{clean}: difference = {pts.formula} = {nx.quantize(pts.value, 2)}"
                    )
                )
                sentences.append(
                    f"{clean} changed by {nx.quantize(pc.value)}% from "
                    f"{old.period} to {new.period}"
                    + (
                        f" ({nx.quantize(pts.value, 1)} percentage points)"
                        if unit_pct else ""
                    )
                    + f" [{sid}]."
                )
                directions.append(
                    (clean, 1 if pc.value > 0 else -1 if pc.value < 0 else 0)
                )

        if multi and len(directions) >= 2:
            same = (
                len({d for _, d in directions if d != 0}) == 1
                and all(d != 0 for _, d in directions)
            )
            names = " and ".join(n for n, _ in directions[:2])
            sentences.append(
                ("Yes - " + names +
                 " moved in the same direction over the period, which is consistent "
                 "with a coincidence (this does not by itself establish causation).")
                if same
                else f"No - {names} did not move in the same direction over the period."
            )

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
