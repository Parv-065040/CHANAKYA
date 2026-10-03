"""Single source of truth for the synthetic company 'Veritas Forge Industries Ltd'.

Every document is rendered from this model; sums are exact by construction and
re-verified in tests/test_dataset.py. FY2025 = Apr 2024 - Mar 2025 (Indian FY).
"""
from __future__ import annotations

import random

MONTHS = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]
LINES = ["Line A", "Line B", "Line C"]


def alloc(total: int, weights: list[float]) -> list[int]:
    """Split an integer total across weights so parts sum exactly (largest remainder)."""
    s = sum(weights)
    raw = [total * w / s for w in weights]
    base = [int(x) for x in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)[: total - sum(base)]:
        base[i] += 1
    return base


def jitter(rng: random.Random, n: int, amp: float = 0.18) -> list[float]:
    return [1 + rng.uniform(-amp, amp) for _ in range(n)]


class Facts:
    def __init__(self, seed: int = 2025) -> None:
        r = self.rng = random.Random(seed)
        # ---- finance (units of Rs 0.1 crore for exact allocation) --------------
        self.revenue = {"FY2024": 125.0, "FY2025": 148.2}
        self.ebitda = {"FY2024": 28.4, "FY2025": 35.7}
        self.net_profit = {"FY2024": 14.2, "FY2025": 18.6}
        self.opex = {"FY2024": 96.6, "FY2025": 112.5}
        season = [0.9, 0.95, 1.0, 1.0, 1.02, 1.05, 1.08, 1.05, 1.0, 0.95, 0.97, 1.05]
        self.monthly: dict[str, dict[str, list[float]]] = {}
        for fy in ("FY2024", "FY2025"):
            self.monthly[fy] = {}
            for name, tot in (("revenue", self.revenue), ("ebitda", self.ebitda), ("net_profit", self.net_profit)):
                parts = alloc(round(tot[fy] * 10), [a * b for a, b in zip(season, jitter(r, 12, 0.04))])
                self.monthly[fy][name] = [p / 10 for p in parts]
        # product-family revenue (sums to annual revenue)
        self.families = ["Precision Shafts", "Gear Blanks", "Bearing Housings", "Hydraulic Manifolds", "Valve Bodies",
                         "Flanges & Couplings", "Turbine Components", "Brake Discs", "Pump Casings", "Custom Tooling"]
        wts = [18, 14, 12, 11, 10, 9, 8, 7, 6, 5]
        self.family_rev = {fy: [p / 10 for p in alloc(round(self.revenue[fy] * 10), [w * j for w, j in zip(wts, jitter(r, 10, 0.05))])]
                           for fy in ("FY2024", "FY2025")}
        # departments: FY2025 actual opex in Rs crore (Facilities is the balancing item)
        d = [("Manufacturing", 54.6), ("Quality & Safety", 5.4), ("Maintenance", 6.3), ("Supply Chain & Logistics", 5.6),
             ("HR", 8.1), ("Customer Support", 7.9), ("Finance & Admin", 4.5), ("IT", 4.1), ("Sales & Marketing", 6.8),
             ("R&D", 4.6), ("Legal & Compliance", 1.5)]
        d.append(("Facilities", round(self.opex["FY2025"] - sum(v for _, v in d), 1)))
        assert d[-1][1] > 0
        self.dept_actual = dict(d)
        growth = [1.12, 1.30, 1.09, 1.10, 1.06, 1.09, 1.07, 1.15, 1.18, 1.22, 1.03]
        bud = [(n, round(v * g, 1)) for (n, v), g in zip(d, growth)]
        self.budget_total = 128.0
        bud.append(("Facilities", round(self.budget_total - sum(v for _, v in bud), 1)))
        assert bud[-1][1] > 0
        self.dept_budget = dict(bud)
        subs = {"Manufacturing": ["Line A Machining", "Line B Machining", "Line C Machining", "Heat Treatment", "Assembly & Packing"],
                "Quality & Safety": ["Inspection Lab", "Safety & EHS", "Calibration"], "Maintenance": ["Mechanical", "Electrical", "Tool Room"],
                "Supply Chain & Logistics": ["Procurement", "Warehouse", "Outbound Logistics"], "HR": ["Talent & Recruitment", "Learning", "Payroll & Benefits"],
                "Customer Support": ["Tier-1 Desk", "Field Service", "Escalation Desk"], "Finance & Admin": ["Accounts", "Treasury & Audit"],
                "IT": ["Infrastructure", "Applications"], "Sales & Marketing": ["Key Accounts", "Marketing"], "R&D": ["Process Engineering", "Product Development"],
                "Legal & Compliance": ["Legal"], "Facilities": ["Plant Utilities", "Campus Services"]}
        self.cost_centers = [(dept, cc) for dept, ccs in subs.items() for cc in ccs]
        self.ledger = self._ledger(self.dept_actual, season, "A")  # {(dept, cc): [12 months in Rs lakh]}
        self.budget_ledger = self._ledger(self.dept_budget, season, "B")
        # ---- manufacturing ------------------------------------------------------
        units = {"Line A": [14500, 17200, 16800, 17700], "Line B": [13100, 15600, 16400, 17900], "Line C": [13600, 15000, 16300, 16700]}
        defects = {"Line A": [336, 447, 395, 380], "Line B": [359, 702, 600, 520], "Line C": [294, 333, 391, 408]}
        self.units, self.defects = units, defects
        self.prod_q = [sum(units[l][q] for l in LINES) for q in range(4)]
        self.defect_q = [round(sum(defects[l][q] for l in LINES) / self.prod_q[q] * 100, 1) for q in range(4)]
        assert self.prod_q == [41200, 47800, 49500, 52300] and self.defect_q == [2.4, 3.1, 2.8, 2.5], (self.prod_q, self.defect_q)
        self.downtime_q = {"Line A": [62, 70, 58, 55], "Line B": [71, 118, 96, 84], "Line C": [49, 52, 47, 44]}
        self.machines = {l: [f"{l[-1]}-{i:02d}" for i in range(1, 9)] for l in LINES}
        # weekly production/defects per line (13 weeks per quarter, exact quarter sums)
        # shift-level log: 4 quarters x 13 weeks x 7 days x 3 shifts = 1092 shifts per line
        self.shift_units = {l: sum((alloc(units[l][q], jitter(r, 273, 0.12)) for q in range(4)), []) for l in LINES}
        self.shift_defects = {l: sum((alloc(defects[l][q], jitter(r, 273, 0.5)) for q in range(4)), []) for l in LINES}
        self.week_units = {l: [sum(self.shift_units[l][w * 21:(w + 1) * 21]) for w in range(52)] for l in LINES}
        self.week_defects = {l: [sum(self.shift_defects[l][w * 21:(w + 1) * 21]) for w in range(52)] for l in LINES}
        self.month_units = {l: sum((alloc(units[l][q], jitter(r, 3, 0.06)) for q in range(4)), []) for l in LINES}
        # weekly downtime per machine: exact line-quarter totals
        self.week_down: dict[str, list[list[int]]] = {}
        for l in LINES:
            grid: list[list[int]] = [[0] * 8 for _ in range(52)]
            for q in range(4):
                w = [r.random() ** 3 + 0.01 for _ in range(13 * 8)]
                for k, v in enumerate(alloc(self.downtime_q[l][q], w)):
                    grid[q * 13 + k // 8][k % 8] = v
            self.week_down[l] = grid
        # ---- HR -----------------------------------------------------------------
        self.hr_depts = ["Production", "Quality", "Maintenance", "Supply Chain", "Sales", "Customer Support", "Finance", "HR", "IT", "R&D"]
        self.headcount = {"FY2024": 1840, "FY2025": 1925}
        self.avg_headcount = {"FY2024": 1790, "FY2025": 1883}
        self.leavers = {"FY2024": 265, "FY2025": 211}
        self.attrition = {fy: round(self.leavers[fy] / self.avg_headcount[fy] * 100, 1) for fy in self.leavers}
        assert self.attrition == {"FY2024": 14.8, "FY2025": 11.2}, self.attrition
        dw = [900, 140, 150, 90, 120, 160, 60, 40, 70, 95]
        self.hc_month = []
        for m in range(12):
            tot = round(self.headcount["FY2024"] + (self.headcount["FY2025"] - self.headcount["FY2024"]) * (m + 1) / 12)
            self.hc_month.append(alloc(tot, [w * j for w, j in zip(dw, jitter(r, 10, 0.01))]))
        self.leave_month = []
        for fy, tot in (("FY2025", 211),):
            mm = alloc(tot, jitter(r, 12, 0.3))
            lw = [0.34, 0.07, 0.06, 0.06, 0.1, 0.17, 0.04, 0.03, 0.06, 0.07]
            self.leave_month = [alloc(m, [a * b for a, b in zip(lw, jitter(r, 10, 0.4))]) for m in mm]
        self.grades = [f"G{i}" for i in range(1, 21)]
        # ---- customer support: ticket-level data -------------------------------------
        self.sla = {"P1": (15, 4), "P2": (60, 8), "P3": (240, 72), "P4": (480, 168)}  # first response min, resolution hours
        self.products = [f"{s}-{n}" for s in ("FC", "HP", "SM", "TL", "VX") for n in (110, 120, 210, 220, 310, 410)]
        self.tiers = ["Platinum", "Gold", "Standard"]
        self.tickets = self._tickets(3000)

    def _ledger(self, dept_crore: dict[str, float], season: list[float], tag: str) -> dict[tuple[str, str], list[int]]:
        r = random.Random({'A': 7, 'B': 8}[tag])
        out: dict[tuple[str, str], list[int]] = {}
        for dept, total in dept_crore.items():
            ccs = [cc for d, cc in self.cost_centers if d == dept]
            cells = [w * s for w in jitter(r, len(ccs), 0.4) for s in season]
            vals = alloc(round(total * 100), [c * j for c, j in zip(cells, jitter(r, len(cells), 0.05))])
            for i, cc in enumerate(ccs):
                out[(dept, cc)] = vals[i * 12:(i + 1) * 12]
        return out

    def _tickets(self, n: int) -> list[dict]:
        r = random.Random(99)
        rows = []
        for i in range(1, n + 1):
            p = r.choices(["P1", "P2", "P3", "P4"], [1.2, 3, 5, 3])[0]
            tgt_fr, tgt_rs = self.sla[p]
            late = r.random() < {"P1": 0.04, "P2": 0.09, "P3": 0.12, "P4": 0.15}[p]
            fr = round(tgt_fr * (r.uniform(1.05, 1.8) if late else r.uniform(0.15, 0.95)))
            rs = round(tgt_rs * (r.uniform(1.05, 1.6) if r.random() < 0.05 else r.uniform(0.1, 0.95)), 1)
            met = fr <= tgt_fr and rs <= tgt_rs
            rows.append({"ticket_id": f"T{10000+i}", "priority": p, "month": r.choice(MONTHS), "product": r.choice(self.products),
                         "tier": r.choices(self.tiers, [2, 3, 5])[0], "first_response_min": fr, "resolution_hours": rs,
                         "sla_met": "Yes" if met else "No", "status": "Closed"})
        return rows


FACTS = Facts()
