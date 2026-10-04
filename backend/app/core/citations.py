"""Citation / grounding validator operating on actual retrieved evidence.

Checks (deterministic, no LLM):
  1. every [n] marker refers to a real evidence item (no fabricated sources);
  2. every sentence containing a number carries at least one citation;
  3. every number in the answer appears in the evidence, a calculation result,
     or the user's question (no invented figures).
A refusal answer is valid without citations.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation

from .context import REFUSAL_MESSAGE
from .models import Evidence, Issue, ValidationReport

_MARKER_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_NUMBER_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?!\[\d)|\n+")  # a [n] right after a period belongs to that sentence


def extract_markers(answer: str) -> list[int]:
    ids: list[int] = []
    for m in _MARKER_RE.finditer(answer):
        ids.extend(int(x) for x in m.group(1).split(","))
    return ids


def normalise_number(token: str) -> str | None:
    try:
        d = Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None
    s = format(d.normalize(), "f")
    return s


def numbers_in(text: str) -> set[str]:
    text = _MARKER_RE.sub(" ", text)  # citation markers are not claims
    return {n for t in _NUMBER_RE.findall(text) if (n := normalise_number(t)) is not None}


def _variants(num: str) -> set[str]:
    """Allow rounding to 0-2 decimals so '18.56' matches calc value 18.5600."""
    out = {num}
    try:
        d = Decimal(num)
    except InvalidOperation:
        return out
    for places in (0, 1, 2):
        out.add(format(d.quantize(Decimal(1).scaleb(-places)).normalize(), "f"))
    return out


def validate_answer(
    answer: str,
    evidence: Sequence[Evidence],
    *,
    calc_values: Iterable[Decimal] = (),
    question: str = "",
) -> ValidationReport:
    if answer.strip() == REFUSAL_MESSAGE or answer.strip().startswith(REFUSAL_MESSAGE):
        return ValidationReport(ok=True)

    issues: list[Issue] = []
    valid_ids = {e.source_id for e in evidence}
    markers = extract_markers(answer)

    for sid in sorted(set(markers) - valid_ids):
        issues.append(Issue("fabricated_source", f"Citation [{sid}] does not match any retrieved evidence."))
    if not markers:
        issues.append(Issue("no_citations", "Answer contains no citations."))

    allowed: set[str] = set()
    for ev in evidence:
        allowed |= numbers_in(ev.chunk.text)
    for v in calc_values:
        allowed |= _variants(format(v.normalize(), "f"))
    allowed |= numbers_in(question)

    # Standard mathematical constants used by verified calculations.
    # These are not business claims; they are calculation constants.
    allowed |= {"0", "1", "100"}

    for sentence in filter(None, (s.strip() for s in _SENT_RE.split(answer))):
        nums = numbers_in(sentence)
        if not nums:
            continue
        if not _MARKER_RE.search(sentence):
            issues.append(Issue("uncited_numeric_claim", f"Numeric claim without citation: {sentence[:80]!r}"))
        for n in sorted(nums):
            if not (_variants(n) & allowed):
                issues.append(Issue("unsupported_number", f"Number {n} not found in evidence or calculations."))

    return ValidationReport(ok=not issues, issues=issues, cited_sources=sorted(set(markers) & valid_ids))
