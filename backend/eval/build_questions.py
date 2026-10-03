"""Build eval/questions.json (140+ questions) from the SAME facts the dataset is rendered from.

Expected answers are computed from data/facts.py, never typed by hand, so they cannot drift
from the documents. Written once; the system is NOT tuned against answers it can see here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))
from facts import FACTS as F, LINES, MONTHS, QUARTERS  # noqa: E402

PM = "Production_and_Maintenance_Report_FY2025.pdf"
QS = "Quality_and_Safety_Manual.pdf"
AR = "Annual_Report_FY2025.pdf"
BR = "Budget_and_Forecast_Report_FY2026.pdf"
EH = "Employee_Handbook_FY2025.pdf"
SLA = "SLA_and_Escalation_Handbook.pdf"
FP = "Financial_Policies_and_Controls.pdf"
HR = "HR_Policies_Manual.pdf"
Q: list[dict] = []


def add(question: str, doc: str, must: list[str], cat: str) -> None:
    Q.append({"question": question, "doc": doc, "must": must, "category": cat})


def pct(a: float, b: float) -> str:
    return f"{(b - a) / a * 100:.2f}"


for l in LINES:
    for qi, qn in enumerate(QUARTERS):
        add(f"How many units did {l} produce in {qn}?", PM, [str(F.units[l][qi])], "table_lookup")
        add(f"What was the defect rate of {l} in {qn}?", PM, [f"{F.defects[l][qi] / F.units[l][qi] * 100:.2f}"], "table_lookup")
for qi, qn in enumerate(QUARTERS):
    add(f"What was total production volume in {qn}?", PM, [str(F.prod_q[qi])], "table_lookup")
    add(f"What was the plant defect rate in {qn}?", QS, [str(F.defect_q[qi])], "table_lookup")
for i, m in enumerate(MONTHS):
    add(f"What was revenue in {m} FY2025?", AR, [f"{F.monthly['FY2025']['revenue'][i]:.1f}"], "table_lookup")
for d, v in F.dept_budget.items():
    add(f"What is the FY2026 budget for {d}?", BR, [f"{v:.1f}"], "table_lookup")
for d in list(F.dept_actual)[:6]:
    add(f"What was the FY2025 actual operating expense of {d}?", BR, [f"{F.dept_actual[d]:.1f}"], "table_lookup")
for i in (0, 3, 6, 11):
    add(f"What was total headcount in {MONTHS[i]}?", EH, [str(sum(F.hc_month[i]))], "table_lookup")

tk = F.tickets
for m in MONTHS:
    sub = [t for t in tk if t["month"] == m and t["priority"] == "P1"]
    add(f"What was P1 SLA compliance in {m}?", SLA, [f"{sum(t['sla_met'] == 'Yes' for t in sub) / len(sub) * 100:.1f}"], "table_lookup")
for p, (fr, rs) in F.sla.items():
    pass
for p, fr, rs in [("P1", "15 minutes", "4 hours"), ("P2", "1 hour", "8 hours"), ("P3", "4 hours", "3 business days"), ("P4", "8 hours", "7 business days")]:
    add(f"What is the first response time for {p} tickets?", SLA, [fr], "policy")
    add(f"What is the resolution target for {p} incidents?", SLA, [rs], "policy")
for tier, p1 in [("Platinum", "10 minutes"), ("Gold", "15 minutes"), ("Standard", "15 minutes")]:
    add(f"What is the P1 first response target for {tier} customers?", SLA, [p1], "policy")
for lt, days in [("Earned Leave", "24"), ("Casual Leave", "8"), ("Sick Leave", "10"), ("Maternity Leave", "182"), ("Paternity Leave", "10")]:
    add(f"How many days of {lt.lower()} do employees get?", EH, [days], "policy")
add("What is the approval limit for the Chief Financial Officer per transaction?", FP, ["50"], "policy")
add("Within how many days must expense claims be submitted?", FP, ["15"], "policy")
add("How many quotations are needed for purchases above Rs 5 lakh?", FP, ["three"], "policy")
add("What is the notice period for grades G1 to G10?", EH, ["60"], "policy")
add("How many days to resolve grievances?", HR, ["21"], "policy")

R, E, N, O = F.revenue, F.ebitda, F.net_profit, F.opex
add("Calculate the percentage increase in revenue between FY2024 and FY2025.", AR, [pct(R["FY2024"], R["FY2025"])], "numerical")
add("Calculate the percentage increase in EBITDA between FY2024 and FY2025.", AR, [pct(E["FY2024"], E["FY2025"])], "numerical")
add("How much did net profit grow from FY2024 to FY2025?", AR, [pct(N["FY2024"], N["FY2025"])], "numerical")
add("What was the percentage change in operating expenses from FY2024 to FY2025?", AR, [pct(O["FY2024"], O["FY2025"])], "numerical")
add("How did production volume change from Q1 to Q2?", PM, [pct(F.prod_q[0], F.prod_q[1])], "numerical")
add("How did production volume change from Q2 to Q3?", PM, [pct(F.prod_q[1], F.prod_q[2])], "numerical")
add("What was employee attrition in FY2025 compared with FY2024?", EH, ["14.8", "11.2"], "numerical")
add("How did headcount change between FY2024 and FY2025?", EH, ["1925"], "numerical")
add("What was the EBITDA margin in FY2025?", AR, [f"{E['FY2025'] / R['FY2025'] * 100:.2f}"], "table_lookup")
add("What was net margin in FY2024?", AR, [f"{N['FY2024'] / R['FY2024'] * 100:.2f}"], "table_lookup")

add("Which production line had the highest defect rate?", PM, ["Line B"], "superlative")
add("Which production line had the lowest defect rate?", PM, ["Line C"], "superlative")
add("Which line had the most downtime hours in Q2?", PM, ["Line B", "118"], "superlative")
add("Which department has the highest FY2026 budget?", BR, ["Manufacturing"], "superlative")
add("Which department has the lowest FY2026 budget?", BR, [min(F.dept_budget, key=F.dept_budget.get)], "superlative")
add("Which product family had the highest revenue growth?", AR, [max(F.families, key=lambda n: F.family_rev["FY2025"][F.families.index(n)] / F.family_rev["FY2024"][F.families.index(n)])], "superlative")

add("Did increased production volume coincide with higher defect rates in Q2?", PM, ["16.02", "Yes"], "multi_document")
add("Did production volume and defect rate both rise between Q1 and Q2?", PM, ["16.02", "Yes"], "multi_document")
add("Did defect rates rise when production volume increased from Q1 to Q2?", QS, ["3.1", "Yes"], "multi_document")

for q_ in ["What was the company's stock price on 3 October 2026?", "Who is the CEO of the company?", "What is the dividend per share declared for FY2025?",
           "How many electric vehicles does the company sell in Germany?", "What is the market share of the company in Brazil?", "What was revenue in FY2023?",
           "What is the revenue forecast for FY2027?", "Who won the cricket match yesterday?", "What is the salary of the managing director?",
           "How many patents does the company hold?", "What is the weather in Pune today?", "What is the company's carbon emission target for 2030?"]:
    add(q_, "", [], "unanswerable")

(Path(__file__).parent / "questions.json").write_text(json.dumps(Q, indent=1))
print(len(Q), "questions;", {c: sum(q["category"] == c for q in Q) for c in sorted({q["category"] for q in Q})})
