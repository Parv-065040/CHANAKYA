"""Deterministic numerical engine. The LLM never does the arithmetic.

Pipeline: parse -> validate -> normalise units -> calculate -> validate result.
All math uses ``Decimal``; every result carries a human-readable formula.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Multipliers to a common base (units).
UNIT_FACTORS: dict[str, Decimal] = {
    "": Decimal(1),
    "thousand": Decimal(10) ** 3,
    "k": Decimal(10) ** 3,
    "lakh": Decimal(10) ** 5,
    "lakhs": Decimal(10) ** 5,
    "million": Decimal(10) ** 6,
    "mn": Decimal(10) ** 6,
    "crore": Decimal(10) ** 7,
    "crores": Decimal(10) ** 7,
    "cr": Decimal(10) ** 7,
    "billion": Decimal(10) ** 9,
    "bn": Decimal(10) ** 9,
}

_NUM_RE = re.compile(
    r"^\s*(?P<neg>\()?\s*(?P<cur>[₹$€£]|rs\.?|inr|usd)?\s*(?P<sign>-)?\s*"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<pct>%)?\s*(?P<unit>[a-z]+)?\s*(?P<close>\))?\s*$",
    re.IGNORECASE,
)


class NumericError(ValueError):
    """Raised for unparseable values, unit mismatches, or invalid operations."""


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: str = ""  # normalised scale unit ("" | "crore" | ...), or "%" for percentages
    source_id: int | None = None  # citation number of the supporting evidence

    def base(self) -> Decimal:
        return self.value * UNIT_FACTORS.get(self.unit, Decimal(1))


@dataclass(frozen=True)
class CalcResult:
    value: Decimal
    unit: str
    formula: str
    source_ids: tuple[int, ...]

    def display(self, places: int = 2) -> str:
        v = quantize(self.value, places)
        return f"{v}%" if self.unit == "%" else (f"{v} {self.unit}".strip())


def quantize(value: Decimal, places: int = 2) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def parse_quantity(raw: str, source_id: int | None = None) -> Quantity:
    """Parse '₹1,25,000.5 crore', '(14.2)' (negative), '18.5%', '148.2'."""
    m = _NUM_RE.match(raw)
    if not m or bool(m.group("neg")) != bool(m.group("close")):
        raise NumericError(f"cannot parse numeric value: {raw!r}")
    try:
        value = Decimal(m.group("num").replace(",", ""))
    except InvalidOperation as exc:  # pragma: no cover - regex guards this
        raise NumericError(f"cannot parse numeric value: {raw!r}") from exc
    if m.group("neg") or m.group("sign"):
        value = -value
    unit = (m.group("unit") or "").lower()
    if m.group("pct"):
        unit = "%"
    elif unit not in UNIT_FACTORS:
        raise NumericError(f"unknown unit {unit!r} in {raw!r}")
    if unit in ("crores", "cr"):
        unit = "crore"
    elif unit == "lakhs":
        unit = "lakh"
    return Quantity(value, unit, source_id)


def _sources(*qs: Quantity) -> tuple[int, ...]:
    return tuple(sorted({q.source_id for q in qs if q.source_id is not None}))


def _align(*qs: Quantity) -> tuple[list[Decimal], str]:
    """Convert to a common scale. Mixed '%' and absolute values are rejected."""
    if any(q.unit == "%" for q in qs):
        if not all(q.unit == "%" for q in qs):
            raise NumericError("cannot combine percentages with absolute values")
        return [q.value for q in qs], "%"
    target = qs[0].unit
    factor = UNIT_FACTORS[target]
    return [q.base() / factor for q in qs], target


def difference(new: Quantity, old: Quantity) -> CalcResult:
    (n, o), unit = _align(new, old)
    return CalcResult(n - o, unit, f"{n} - {o}", _sources(new, old))


def percent_change(new: Quantity, old: Quantity) -> CalcResult:
    (n, o), unit = _align(new, old)
    if unit == "%":
        raise NumericError("use difference() for percentage-point changes")
    if o == 0:
        raise NumericError("percent change undefined: base value is zero")
    return CalcResult((n - o) / o * 100, "%", f"(({n} - {o}) / {o}) x 100", _sources(new, old))


def ratio(numerator: Quantity, denominator: Quantity) -> CalcResult:
    (a, b), _ = _align(numerator, denominator)
    if b == 0:
        raise NumericError("ratio undefined: denominator is zero")
    return CalcResult(a / b, "x", f"{a} / {b}", _sources(numerator, denominator))


def margin(part: Quantity, whole: Quantity) -> CalcResult:
    """part as a percentage of whole (e.g. EBITDA margin = EBITDA / Revenue)."""
    (a, b), _ = _align(part, whole)
    if b == 0:
        raise NumericError("margin undefined: whole is zero")
    return CalcResult(a / b * 100, "%", f"({a} / {b}) x 100", _sources(part, whole))


def total(qs: Sequence[Quantity]) -> CalcResult:
    if not qs:
        raise NumericError("no values to sum")
    vals, unit = _align(*qs)
    return CalcResult(sum(vals, Decimal(0)), unit, " + ".join(map(str, vals)), _sources(*qs))


def average(qs: Sequence[Quantity]) -> CalcResult:
    t = total(qs)
    return CalcResult(t.value / len(qs), t.unit, f"({t.formula}) / {len(qs)}", t.source_ids)
