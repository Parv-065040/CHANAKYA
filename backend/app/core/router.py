"""Rule-based query router. Departments are configuration, not code.

Adding a department (e.g. Legal) means adding a ``DepartmentConfig`` entry; no
retrieval code changes. A rules router is deterministic and free; it can be
swapped for an LLM router behind the same ``route_query`` signature.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

QUESTION_TYPES = (
    "semantic", "factual", "table_lookup", "numerical", "comparison",
    "aggregation", "multi_document", "cross_department", "policy",
)


@dataclass(frozen=True)
class DepartmentConfig:
    name: str
    label: str
    keywords: tuple[str, ...]


DEFAULT_DEPARTMENTS: dict[str, DepartmentConfig] = {
    d.name: d
    for d in (
        DepartmentConfig("finance", "Finance", (
            "revenue", "ebitda", "profit", "budget", "forecast", "cash flow", "balance sheet",
            "income statement", "expense", "margin", "financial", "audit")),
        DepartmentConfig("hr", "HR", (
            "employee", "attrition", "leave", "recruitment", "compensation", "benefit",
            "handbook", "payroll", "performance review", "training", "headcount")),
        DepartmentConfig("manufacturing", "Manufacturing", (
            "production", "defect", "downtime", "machine", "maintenance", "inventory",
            "assembly", "quality", "safety", "line", "plant", "throughput")),
        DepartmentConfig("customer_support", "Customer Support", (
            "sla", "ticket", "escalation", "incident", "priority-1", "p1", "customer",
            "troubleshoot", "support", "resolution", "response time")),
    )
}

_NUMERICAL = re.compile(r"\b(calculate|compute|percent(age)?|growth|increase[d]?|decrease[d]?|"
                        r"ratio|margin|how much|change|difference|cagr)\b|%", re.I)
_COMPARISON = re.compile(r"\b(compare[d]?|versus|vs\.?|compared with|between .+ and)\b", re.I)
_AGGREGATION = re.compile(r"\b(total|sum|average|mean|overall|combined|aggregate)\b", re.I)
_MULTIDOC = re.compile(r"\b(coincide|correlat\w*|alongside|relationship between|at the same time|"
                       r"both .*(rise|rose|increase[d]?|fall|fell|decline[d]?)|"
                       r"(rise|rose|increase[d]?|fall|fell|decline[d]?|higher|lower) (when|while|with|alongside)|"
                       r"did .+ (rise|increase|fall|decline) .+ (with|when|while))\b", re.I)
_TABLE = re.compile(r"\b(what (was|is|were)|which|highest|lowest|how many)\b", re.I)
_POLICY = re.compile(r"\b(policy|procedure|sop|guideline|entitle\w*|eligib\w*|allowed|must|required)\b", re.I)
_SEMANTIC = re.compile(r"\b(why|factors?|reasons?|how (does|do|can|should)|explain|influence)\b", re.I)


@dataclass(frozen=True)
class RoutePlan:
    departments: tuple[str, ...]
    question_type: str
    needs_numerics: bool
    needs_multi_retrieval: bool
    candidate_k: int
    top_k: int
    notes: list[str] = field(default_factory=list)


def detect_departments(query: str, departments: Mapping[str, DepartmentConfig]) -> list[str]:
    q = query.lower()
    scored = []
    for name, cfg in departments.items():
        hits = sum(1 for kw in cfg.keywords if re.search(r"\b" + re.escape(kw), q))
        if hits:
            scored.append((hits, name))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [n for _, n in scored]


def route_query(
    query: str,
    *,
    departments: Mapping[str, DepartmentConfig] = DEFAULT_DEPARTMENTS,
    allowed_departments: set[str] | None = None,
    selected_department: str | None = None,
) -> RoutePlan:
    """Choose departments and strategy; always intersect with the access allow-list."""
    notes: list[str] = []
    detected = detect_departments(query, departments)
    if selected_department:
        # UI selection is a hard filter, unless the question clearly spans departments.
        chosen = [selected_department]
        if len(detected) > 1 and selected_department in detected:
            chosen = detected
            notes.append("query spans departments; widened beyond UI selection")
    else:
        chosen = detected or list(departments)
    if allowed_departments is not None:
        denied = [d for d in chosen if d not in allowed_departments]
        chosen = [d for d in chosen if d in allowed_departments]
        if denied:
            notes.append(f"access control removed: {', '.join(denied)}")

    if len(chosen) > 1 and len(detected) > 1:
        qtype = "cross_department"
    elif _MULTIDOC.search(query):
        qtype = "multi_document"
    elif _SEMANTIC.search(query):
        qtype = "semantic"  # "why/factors/explain" beats incidental words like "increased"
    elif _COMPARISON.search(query):
        qtype = "comparison"
    elif _AGGREGATION.search(query):
        qtype = "aggregation"
    elif _NUMERICAL.search(query):
        qtype = "numerical"
    elif _POLICY.search(query):
        qtype = "policy"
    elif _TABLE.search(query):
        qtype = "table_lookup"
    else:
        qtype = "factual"

    needs_numerics = qtype in {"numerical", "comparison", "aggregation", "multi_document"}
    multi = qtype in {"multi_document", "cross_department", "comparison"}
    return RoutePlan(
        departments=tuple(chosen),
        question_type=qtype,
        needs_numerics=needs_numerics,
        needs_multi_retrieval=multi,
        candidate_k=30 if multi else 20,
        top_k=10 if multi else 6,
        notes=notes,
    )
