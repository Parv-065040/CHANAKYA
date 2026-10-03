"""Generate the CHANAKYA Demonstration Dataset (SYNTHETIC; fictional 'Veritas Forge Industries Ltd').

Every number is rendered from data/facts.py so documents agree with each other.
Manuals mix hand-written policy text with parameter-driven sections (per machine, per product,
per grade); registers/logs are data tables. See README for an honest description.
"""
from __future__ import annotations

import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from facts import FACTS as F, LINES, MONTHS, QUARTERS, alloc, jitter  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

CO = "Veritas Forge Industries Ltd"
TAG = "CHANAKYA Demonstration Dataset - synthetic data for a fictional company. Not real."
ST = getSampleStyleSheet()
SMALL = ParagraphStyle("small", parent=ST["BodyText"], fontSize=9, leading=11)


def pct(a: float, b: float) -> str:
    return f"{(b - a) / a * 100:.2f}"


EXPECTED: dict[str, int] = {}


def build_pdf(path: Path, title: str, sections: list) -> None:
    """sections: (heading, [paragraphs], [(caption, rows), ...], page_break_before)"""
    story = [Paragraph(title, ST["Title"]), Paragraph(CO, ST["Heading3"]), Paragraph(TAG, ST["Italic"]), Spacer(1, 10)]
    for n, sec in enumerate(sections, start=1):
        head, paras, tables = sec[0], sec[1], sec[2] if len(sec) > 2 else []
        if len(sec) > 3 and sec[3]:
            story.append(PageBreak())
        story.append(Paragraph(f"{n}. {head}", ST["Heading1"]))
        for p in paras:
            story += [Paragraph(p, ST["BodyText"]), Spacer(1, 5)]
        for k, (cap, rows) in enumerate(tables, start=1):
            EXPECTED[path.name] = EXPECTED.get(path.name, 0) + len(rows) - 1
            story.append(Paragraph(f"{n}.{k} {cap}", ST["Heading2"]))
            big = len(rows) > 12 or len(rows[0]) > 6
            t = Table(rows, hAlign="LEFT", repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                   ("FONTSIZE", (0, 0), (-1, -1), (7 if len(rows[0]) > 9 else 8) if big else 9.5),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 14), ("TOPPADDING", (0, 0), (-1, -1), 3 if big else 4),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 3 if big else 4)]))
            story += [t, Spacer(1, 8)]
    SimpleDocTemplate(str(path), pagesize=A4, title=title, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36).build(story)


def f1(x): return f"{x:.1f}"
def lk(x): return f"{x / 100:.2f}"


D0 = date(2024, 4, 1)


def dstr(i): return (D0 + timedelta(days=i)).strftime("%d-%b-%Y")


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    r = random.Random(11)
    R, E, N, O = F.revenue, F.ebitda, F.net_profit, F.opex
    q_of = lambda series, fy: [round(sum(series[fy][i * 3:(i + 1) * 3]), 1) for i in range(4)]  # noqa: E731

    # ============ FINANCE ============
    names_a = ["Apex", "Bharat", "Crown", "Delta", "Eastern", "Fulcrum", "Globe", "Horizon", "Indus", "Jupiter", "Keystone", "Lotus", "Meridian", "Nova", "Orion", "Pinnacle", "Quantum", "Regal", "Sterling", "Titan"]
    names_b = ["Auto Components", "Heavy Machinery", "Rail Systems", "Energy", "Aerospace", "Marine Works", "Agri Equipment", "Industrial Pumps", "Mining Equipment", "Power Tools"]
    custs = [f"{names_a[i % 20]} {names_b[i // 20]}" for i in range(200)]
    cw = [1 / (i + 3) ** 0.9 for i in range(200)]
    c24 = alloc(round(R["FY2024"] * 100), [w * j for w, j in zip(cw, jitter(r, 200, 0.1))])
    c25 = alloc(round(R["FY2025"] * 100), [w * j for w, j in zip(cw, jitter(r, 200, 0.1))])
    seg = ["Automotive", "Energy", "Rail", "Aerospace", "Industrial"]
    cust_rows = [["Customer", "Segment", "FY2024 Revenue (Rs crore)", "FY2025 Revenue (Rs crore)"]] + [
        [c, seg[i % 5], f"{c24[i] / 100:.2f}", f"{c25[i] / 100:.2f}"] for i, c in enumerate(custs)]
    mrows = [["Month", "Revenue FY2024", "Revenue FY2025", "EBITDA FY2024", "EBITDA FY2025", "Net Profit FY2024", "Net Profit FY2025"]]
    for i, m in enumerate(MONTHS):
        mrows.append([m] + [f1(F.monthly[fy][k][i]) for k in ("revenue", "ebitda", "net_profit") for fy in ("FY2024", "FY2025")])
    mrows = [mrows[0]] + [[x[0], x[1], x[2], x[3], x[4], x[5], x[6]] for x in mrows[1:]]
    qrev, qeb = q_of(F.monthly, "FY2025")["revenue"] if False else None, None
    qr25 = [round(sum(F.monthly["FY2025"]["revenue"][i * 3:(i + 1) * 3]), 1) for i in range(4)]
    qr24 = [round(sum(F.monthly["FY2024"]["revenue"][i * 3:(i + 1) * 3]), 1) for i in range(4)]
    qe25 = [round(sum(F.monthly["FY2025"]["ebitda"][i * 3:(i + 1) * 3]), 1) for i in range(4)]
    qe24 = [round(sum(F.monthly["FY2024"]["ebitda"][i * 3:(i + 1) * 3]), 1) for i in range(4)]
    ledger_rows = [["Department", "Cost Center"] + MONTHS + ["Total (Rs lakh)"]] + [
        [d, cc] + [str(v) for v in vals] + [str(sum(vals))] for (d, cc), vals in F.ledger.items()]
    dept_rows = [["Department", "FY2025 Actual (Rs crore)", "FY2026 Budget (Rs crore)"]] + [[d, f1(F.dept_actual[d]), f1(F.dept_budget[d])] for d in F.dept_actual]
    dept_rows.append(["Total Operating Expenses", f1(sum(F.dept_actual.values())), f1(sum(F.dept_budget.values()))])
    fam_rows = [["Product Family", "FY2024 Revenue (Rs crore)", "FY2025 Revenue (Rs crore)", "Growth (%)"]] + [
        [n, f1(a), f1(b), pct(a, b)] for n, a, b in zip(F.families, F.family_rev["FY2024"], F.family_rev["FY2025"])]
    build_pdf(out / "Annual_Report_FY2025.pdf", "Annual Report FY2025", [
        ("Chairman's Overview", [
            f"{CO} delivered a strong FY2025 (April 2024 to March 2025). Revenue rose from Rs {R['FY2024']} crore in FY2024 to Rs {R['FY2025']} crore in FY2025, growth of {pct(R['FY2024'], R['FY2025'])} percent, "
            "driven by higher production volumes, a richer product mix and improved pricing on precision components.",
            "The board approved capacity additions on Line B and a stronger quality programme after defect rates increased in the second quarter. The company remains focused on automotive, energy and rail customers."], []),
        ("Management Discussion and Analysis", [
            "Demand from automotive and energy customers remained firm throughout the year. The second shift introduced on Line B in the second quarter lifted output but also coincided with higher defects and machine downtime, which management has addressed through tool-life controls and additional first-article inspection.",
            "Operating expenses grew more slowly than revenue, expanding the EBITDA margin. Management expects continued margin support in FY2026 from fixed-cost absorption, subject to raw-material prices.",
            "The company's FY2026 operating expense budget is Rs 128.0 crore against Rs 112.5 crore of actual expenses in FY2025, reflecting planned growth investments in quality, R&D and IT."], []),
        ("Financial Results", ["All figures are in Rs crore unless stated. FY2024 comparatives are as restated. EBITDA is earnings before interest, tax, depreciation and amortisation."], [
            ("Consolidated Income Statement", [["Metric", "FY2024", "FY2025"], ["Revenue", f1(R["FY2024"]), f1(R["FY2025"])], ["Operating Expenses", f1(O["FY2024"]), f1(O["FY2025"])],
                                               ["EBITDA", f1(E["FY2024"]), f1(E["FY2025"])], ["Net Profit", f1(N["FY2024"]), f1(N["FY2025"])]]),
            ("Quarterly Revenue and EBITDA", [["Metric", "Q1", "Q2", "Q3", "Q4"], ["Revenue FY2024"] + [f1(x) for x in qr24], ["Revenue FY2025"] + [f1(x) for x in qr25],
                                              ["EBITDA FY2024"] + [f1(x) for x in qe24], ["EBITDA FY2025"] + [f1(x) for x in qe25]]),
            ("Monthly Revenue, EBITDA and Net Profit", mrows)]),
        ("Profitability and Margins", [f"EBITDA margin improved from {E['FY2024'] / R['FY2024'] * 100:.2f} percent in FY2024 to {E['FY2025'] / R['FY2025'] * 100:.2f} percent in FY2025 as fixed costs were spread over higher volumes. Net profit grew {pct(N['FY2024'], N['FY2025'])} percent."], [
            ("Key Ratios", [["Ratio", "FY2024", "FY2025"], ["EBITDA Margin (%)", f"{E['FY2024'] / R['FY2024'] * 100:.2f}", f"{E['FY2025'] / R['FY2025'] * 100:.2f}"],
                            ["Net Margin (%)", f"{N['FY2024'] / R['FY2024'] * 100:.2f}", f"{N['FY2025'] / R['FY2025'] * 100:.2f}"]])]),
        ("Segment Performance", ["Revenue by product family is shown below. Precision Shafts remained the largest family. All families grew except where noted."], [("Revenue by Product Family", fam_rev if False else fam_rows)]),
        ("Balance Sheet and Cash Flow", ["Total assets stood at Rs 212.4 crore at the end of FY2025 against Rs 188.9 crore a year earlier. Borrowings were reduced to Rs 31.5 crore."], [
            ("Balance Sheet Highlights", [["Item", "FY2024", "FY2025"], ["Total Assets", "188.9", "212.4"], ["Borrowings", "38.2", "31.5"], ["Shareholders Equity", "96.0", "114.6"]]),
            ("Cash Flow Summary", [["Item", "FY2024", "FY2025"], ["Cash from Operations", "21.7", "29.4"], ["Capital Expenditure", "12.3", "16.8"], ["Free Cash Flow", "9.4", "12.6"]])]),
        ("People and Operations", [f"Employee attrition fell from {F.attrition['FY2024']} percent to {F.attrition['FY2025']} percent. Year-end headcount rose to {F.headcount['FY2025']} from {F.headcount['FY2024']}. "
                                   f"Manufacturing output reached {sum(F.prod_q):,} units across three production lines. See the Manufacturing and HR reports for detail."], []),
        ("Risk Management", ["Key risks include raw-material price volatility, concentration of customers in automotive supply chains, quality escapes and key-person dependency. Management reviews risk registers quarterly and reports to the Audit Committee."], []),
        ("Corporate Governance", ["The Board comprises seven directors, four of them independent. The Audit Committee met six times during FY2025."], [
            ("Board Committees", [["Committee", "Members", "Meetings in FY2025"], ["Audit", "4", "6"], ["Nomination and Remuneration", "3", "4"], ["Risk Management", "4", "4"], ["Stakeholders Relationship", "3", "2"]])]),
        ("Notes to Accounts", [
            "Note 1 Basis of preparation: the financial statements are prepared under the historical cost convention in accordance with applicable accounting standards.",
            "Note 2 Inventories are valued at the lower of cost and net realisable value; cost is determined on a weighted-average basis.",
            "Note 3 Property, plant and equipment are depreciated on a straight-line basis over useful lives of 8 to 25 years; depreciation for FY2025 was Rs 9.3 crore.",
            "Note 4 Revenue is recognised when control of goods passes to the customer, normally on dispatch.",
            "Note 5 Employee benefits: gratuity and leave encashment are provided on actuarial valuation.",
            "Note 6 Related-party transactions during the year were at arm's length and approved by the Audit Committee."], []),
        ("Appendix A: Customer Revenue Register", ["Revenue by customer for the 200 largest customer accounts; the register sums to total revenue."], [("Revenue by Customer", cust_rows)], True),
        ("Appendix B: Operating Expense Ledger by Cost Center", ["Operating expenses by cost center and month for FY2025 in Rs lakh (100 lakh = 1 crore). Totals agree to the department summary below."], [
            ("Department Summary", dept_rows), ("Cost Center Ledger FY2025 (Rs lakh)", ledger_rows)], True),
    ])
    pol_rows = [["Control ID", "Process", "Control Objective", "Owner", "Frequency"]]
    procs = ["Purchase to Pay", "Order to Cash", "Payroll", "Inventory", "Fixed Assets", "Treasury", "Financial Close", "Tax", "IT General", "Expense Claims"]
    objs = ["Authorisation", "Completeness", "Accuracy", "Segregation of duties", "Reconciliation", "Review and approval", "Access control", "Exception reporting", "Cut-off", "Valuation"]
    owners = ["CFO", "Finance Controller", "Head of Procurement", "Head of HR", "IT Head", "Plant Controller"]
    for i in range(100):
        pol_rows.append([f"FC-{i + 1:03d}", procs[i % 10], objs[(i * 3 + i // 10) % 10], owners[i % 6], ["Daily", "Weekly", "Monthly", "Quarterly"][i % 4]])
    doa = [["Item", "Approver", "Limit per Transaction (Rs lakh)", "Annual Limit (Rs crore)"]]
    cats = ["Capital expenditure", "Raw material purchase", "Consumables", "Contract labour", "Travel", "Marketing", "IT software", "Repairs and maintenance", "Professional fees", "Training"]
    appr = [("Department Head", 5, 1), ("Chief Financial Officer", 50, 10), ("Managing Director", 200, 50), ("Board", 1000, 200)]
    for c in cats:
        for a, lim, ann in appr:
            doa.append([c, a, str(lim), str(ann)])
    claims = [["Grade Band", "City Class", "Hotel per Night (Rs)", "Meals per Day (Rs)"]]
    for gb, base in (("G1-G5", 2500), ("G6-G10", 4000), ("G11-G15", 6500), ("G16-G20", 10000)):
        for cc, mul in (("Metro", 1.0), ("Tier-1", 0.8), ("Tier-2", 0.65), ("Other", 0.5)):
            claims.append([gb, cc, str(int(base * mul)), str(int(base * mul * 0.3))])
    build_pdf(out / "Financial_Policies_and_Controls.pdf", "Financial Policies and Internal Controls", [
        ("Purpose and Scope", ["This policy governs expenditure approval, procurement, revenue recognition, expense claims and financial reporting across all departments of the company. It applies to every employee and contractor who commits company funds."], []),
        ("Expenditure Approval Limits", ["Spending must be approved by the authority level shown below. Splitting purchases to avoid a limit is prohibited. The Chief Financial Officer may approve up to Rs 50 lakh per transaction and Rs 10 crore per year."], [("Delegation of Authority", doa)]),
        ("Procurement Policy", ["Purchases above Rs 5 lakh require three written quotations; purchases above Rs 50 lakh require a formal tender. Single-source purchases need CFO approval with written justification. Vendors are re-evaluated annually on quality, delivery and price."], [
            ("Procurement Thresholds", [["Purchase Value (Rs lakh)", "Requirement"], ["Up to 1", "Single quotation"], ["1 to 5", "Two quotations"], ["5 to 50", "Three quotations"], ["Above 50", "Formal tender"]])]),
        ("Travel and Expense Claims", ["Expense claims must be submitted within 15 days of travel with original receipts. Claims above the limits below require Department Head and CFO approval."], [("Travel Entitlements", claims)]),
        ("Internal Controls", ["Segregation of duties is mandatory: the person raising a payment cannot approve it. Bank reconciliations are completed within five working days of month end. Journal entries above Rs 10 lakh require CFO review."], [("Internal Control Matrix", pol_rows)]),
        ("Revenue Recognition", ["Revenue is recognised when control of goods transfers to the customer, normally on dispatch for domestic sales and on bill of lading for exports."], []),
        ("Financial Reporting Calendar", ["Quarterly results are closed on working day 10 after quarter end and reviewed by the Audit Committee within 21 days."], [
            ("Reporting Deadlines", [["Activity", "Deadline"], ["Monthly close", "Working day 7"], ["Quarterly review", "Day 21"], ["Annual audit sign-off", "May 30"]])]),
    ])
    capex = [["Project ID", "Department", "Description", "FY2026 Budget (Rs lakh)"]]
    cap_tot = alloc(2400, jitter(r, 120, 0.8))
    kinds = ["CNC machine replacement", "Tooling upgrade", "Inspection equipment", "Energy efficiency retrofit", "ERP module", "Safety systems", "Warehouse racking", "Test bench", "Network upgrade", "Furnace refurbishment"]
    depts_cx = ["Manufacturing", "Quality & Safety", "Maintenance", "IT", "Facilities", "R&D"]
    for i in range(120):
        capex.append([f"CX-{i + 1:03d}", depts_cx[i % 6], kinds[(i * 7 + i // 6) % 10], str(cap_tot[i])])
    bud_ledger = [["Department", "Cost Center"] + MONTHS + ["Total (Rs lakh)"]] + [[d, cc] + [str(v) for v in vals] + [str(sum(vals))] for (d, cc), vals in F.budget_ledger.items()]
    rev26 = 172.0
    build_pdf(out / "Budget_and_Forecast_Report_FY2026.pdf", "Budget and Forecast Report FY2026", [
        ("Budget Summary", [f"The FY2026 budget assumes revenue of Rs {rev26} crore, EBITDA of Rs 44.0 crore and operating expenses of Rs {F.budget_total} crore. Revenue growth of {pct(R['FY2025'], rev26)} percent over FY2025 is planned from volume and pricing."], [
            ("Headline Budget", [["Metric", "FY2025 Actual", "FY2026 Budget"], ["Revenue", f1(R["FY2025"]), f1(rev26)], ["Operating Expenses", f1(O["FY2025"]), f1(F.budget_total)], ["EBITDA", f1(E["FY2025"]), "44.0"]])]),
        ("Scenarios", ["Three scenarios were modelled. The downside assumes a 6 percent volume shortfall; the upside assumes new rail contracts."], [
            ("Scenario Analysis", [["Scenario", "Revenue (Rs crore)", "EBITDA (Rs crore)"], ["Base", "172.0", "44.0"], ["Upside", "181.5", "48.9"], ["Downside", "161.7", "38.2"]])]),
        ("Department Budgets", ["Budgets by department compared with FY2025 actual expenses."], [("Department Budget vs Actual", dept_rows)]),
        ("Capital Expenditure Plan", ["The capital plan totals Rs 24.0 crore across 120 projects."], [("Capital Projects", capex)], True),
        ("Monthly Budget Ledger", ["Budgeted operating expenses by cost center and month in Rs lakh."], [("Cost Center Budget FY2026 (Rs lakh)", bud_ledger)], True),
    ])

    # ============ HR ============
    leave = [["Leave Type", "Days per Year", "Carry Forward"], ["Earned Leave", "24", "Yes, up to 30 days"], ["Casual Leave", "8", "No"], ["Sick Leave", "10", "No"], ["Maternity Leave", "182", "Not applicable"], ["Paternity Leave", "10", "Not applicable"]]
    hc_rows = [["Month"] + F.hr_depts + ["Total"]] + [[MONTHS[i]] + [str(v) for v in F.hc_month[i]] + [str(sum(F.hc_month[i]))] for i in range(12)]
    lv_rows = [["Month"] + F.hr_depts + ["Total"]] + [[MONTHS[i]] + [str(v) for v in F.leave_month[i]] + [str(sum(F.leave_month[i]))] for i in range(12)]
    lv_rows.append(["FY2025 Total"] + [str(sum(F.leave_month[i][j] for i in range(12))) for j in range(10)] + [str(F.leavers["FY2025"])])
    build_pdf(out / "Employee_Handbook_FY2025.pdf", "Employee Handbook FY2025", [
        ("Welcome", ["This handbook explains the policies, benefits and expectations for every employee of the company."], []),
        ("Leave Policy", ["Employees are entitled to the leave types below per calendar year. Unused earned leave carries forward up to 30 days. Leave must be applied for in the HR portal at least three working days in advance except for sick leave."], [("Leave Entitlements", leave)]),
        ("Attrition and Retention", [f"Attrition fell from {F.attrition['FY2024']} percent in FY2024 to {F.attrition['FY2025']} percent in FY2025, with {F.leavers['FY2025']} leavers on an average headcount of {F.avg_headcount['FY2025']:,}. "
                                     "Retention improved after structured career paths, shift allowances and the mentoring programme. Factors influencing retention include compensation competitiveness, manager quality, shift patterns and learning opportunities."], [
            ("Workforce Metrics", [["Metric", "FY2024", "FY2025"], ["Attrition Rate (%)", str(F.attrition["FY2024"]), str(F.attrition["FY2025"])], ["Headcount", str(F.headcount["FY2024"]), str(F.headcount["FY2025"])],
                                   ["Leavers", str(F.leavers["FY2024"]), str(F.leavers["FY2025"])], ["Average Headcount", str(F.avg_headcount["FY2024"]), str(F.avg_headcount["FY2025"])], ["Training Hours per Employee", "26", "34"]])]),
        ("Performance Management", ["Performance is reviewed twice a year against agreed goals. Ratings are calibrated by department heads and HR. Employees rated below expectations receive a 90-day improvement plan."], []),
        ("Compensation and Benefits", ["Compensation bands are benchmarked annually. Benefits include medical insurance for the employee and family, provident fund and an annual performance bonus."], []),
        ("Workplace Conduct", ["Harassment, discrimination and safety violations are grounds for disciplinary action. Concerns can be raised confidentially with HR or the ethics hotline. The notice period for resignation is 60 days for grades G1 to G10 and 90 days for grades G11 and above."], []),
        ("Headcount by Department", ["Month-end headcount by department for FY2025."], [("Monthly Headcount FY2025", hc_rows), ("Monthly Leavers FY2025", lv_rows)]),
    ])
    reqs = [["Requisition", "Department", "Grade", "Opened Month", "Days to Fill", "Status"]]
    for i in range(500):
        reqs.append([f"REQ-{i + 1:04d}", F.hr_depts[(i * 7) % 10], F.grades[(i * 3) % 20], MONTHS[i % 12], str(18 + (i * 13) % 55), ["Filled", "Filled", "Filled", "Open"][i % 4]])
    disc = [["Offence", "First Occurrence", "Second Occurrence", "Third Occurrence"]]
    for o_, a, b, c in [("Unauthorised absence (1 to 3 days)", "Written warning", "Final warning", "Suspension"), ("Safety rule violation", "Written warning", "Suspension 3 days", "Termination"),
                        ("Falsifying records", "Suspension 7 days", "Termination", "Not applicable"), ("Harassment", "Investigation and termination", "Not applicable", "Not applicable"),
                        ("Misuse of company assets", "Written warning", "Recovery and suspension", "Termination"), ("Repeated late arrival", "Verbal warning", "Written warning", "Final warning")]:
        disc.append([o_, a, b, c])
    build_pdf(out / "HR_Policies_Manual.pdf", "HR Policies Manual", [
        ("Recruitment Policy", ["All vacancies require an approved requisition. The target time to fill is 45 days for grades G1 to G10 and 75 days for grades G11 and above. Offers are valid for 15 days."], [("Recruitment Requisition Register FY2025", reqs)]),
        ("Disciplinary Procedure", ["Disciplinary action follows a documented process: show-cause notice, reply within 5 working days, inquiry and decision by a panel of three."], [("Disciplinary Matrix", disc)]),
        ("Working Hours and Shifts", ["The standard working week is 48 hours. Production employees work three eight-hour shifts. A shift allowance of Rs 220 per night shift is payable. Overtime is paid at twice the ordinary rate."], []),
        ("Grievance Redressal", ["Employees may raise grievances with their manager, HR business partner or the ethics hotline. HR acknowledges grievances within 2 working days and resolves them within 21 days."], []),
        ("Exit and Separation", ["Employees must complete clearance and an exit interview. Full and final settlement is paid within 30 days of the last working day."], []),
    ])
    bands = [["Grade", "Minimum (Rs lakh p.a.)", "Midpoint (Rs lakh p.a.)", "Maximum (Rs lakh p.a.)"]]
    for i, g in enumerate(F.grades):
        mid = 2.4 * (1.16 ** i)
        bands.append([g, f"{mid * 0.8:.2f}", f"{mid:.2f}", f"{mid * 1.2:.2f}"])
    courses = [["Course", "Department", "Month", "Participants", "Hours"]]
    ctitles = ["Safety Induction", "Lean Manufacturing", "GD&T Basics", "Statistical Process Control", "Leadership Essentials", "Excel for Finance", "Customer Escalation Handling", "ISO 9001 Awareness", "First Aid", "Preventive Maintenance Practices"]
    for i in range(600):
        courses.append([ctitles[i % 10] + f" Batch {i // 10 + 1}", F.hr_depts[(i * 3) % 10], MONTHS[i % 12], str(8 + (i * 7) % 28), str(4 + (i % 5) * 4)])
    rate = [["Rating", "Compa-ratio below 0.9 (%)", "Compa-ratio 0.9 to 1.1 (%)", "Compa-ratio above 1.1 (%)"], ["Outstanding", "14", "12", "10"], ["Exceeds", "11", "9", "7"], ["Meets", "8", "6", "4"], ["Partially Meets", "3", "2", "0"], ["Below", "0", "0", "0"]]
    build_pdf(out / "Compensation_and_Performance_Manual.pdf", "Compensation and Performance Manual", [
        ("Compensation Philosophy", ["Pay is positioned at the median of the manufacturing market for each grade, with variable pay linked to company and individual performance. Bands are reviewed every April."], [("Salary Bands by Grade", bands)]),
        ("Annual Increment Matrix", ["Annual increments depend on the performance rating and the employee's position in the salary band (compa-ratio)."], [("Increment Percentage Matrix", rate)]),
        ("Variable Pay", ["The annual performance bonus pool is set at 8 percent of EBITDA growth over the prior year, subject to a floor of 1 month's salary for all eligible employees."], []),
        ("Training and Development", ["Each employee receives a minimum of 24 training hours per year. The training register below records instructor-led sessions delivered in FY2025."], [("Training Register FY2025", courses)]),
    ])

    # ============ MANUFACTURING ============
    mach_types = ["CNC Turning Centre", "Vertical Machining Centre", "Cylindrical Grinder", "Horizontal Boring Machine", "Gear Hobber", "Heat Treatment Furnace", "Wire EDM", "Honing Machine"]
    mach_pages = []
    for ln in LINES:
        for k, m in enumerate(F.machines[ln]):
            mt = mach_types[k % 8]
            cap = 180 + (k * 23 + ord(ln[-1])) % 60
            mach_pages.append((f"Machine {m} ({ln}) {mt}", [
                f"Machine {m} is a {mt} installed on {ln}. Operators must complete the readiness checklist at the start of every shift and record results in the shift logbook. Preventive maintenance is due every {250 + k * 50} running hours."],
                [(f"Specification {m}", [["Parameter", "Value"], ["Machine ID", m], ["Line", ln], ["Type", mt], ["Rated Capacity (units per shift)", str(cap)], ["PM Interval (hours)", str(250 + k * 50)],
                                         ["Coolant Concentration (%)", str(6 + k % 3)], ["Spindle Warm-up (minutes)", str(10 + (k % 3) * 5)]])], True))
    build_pdf(out / "Manufacturing_Operations_Manual.pdf", "Manufacturing Operations Manual", [
        ("Safety Briefing and Readiness", ["Each shift begins with a 10-minute safety briefing and a machine readiness checklist. Changeovers follow the documented SOP and must be signed off by the line supervisor. Guards may never be bypassed."], [
            ("Shift Schedule", [["Shift", "Start", "End"], ["Shift 1", "06:00", "14:00"], ["Shift 2", "14:00", "22:00"], ["Shift 3", "22:00", "06:00"]])]),
        ("Changeover Procedure", ["Changeover steps: stop the machine, isolate energy, remove the previous tooling, clean the fixture, load the new programme, run first-article inspection and obtain supervisor sign-off before releasing production. Target changeover time is 45 minutes."], []),
        ("Production Planning", ["Weekly production plans are issued on Friday for the following week. Line capacity is planned at 85 percent of rated capacity to absorb breakdowns."], []),
    ] + [(h, p, t, pb) for h, p, t, pb in mach_pages])
    # production & maintenance report with shift logs
    quarterly = [["Metric", "Q1", "Q2", "Q3", "Q4"], ["Production Volume (units)"] + [str(x) for x in F.prod_q]]
    by_line_q = [["Production Line", "Units Produced", "Defects", "Defect Rate (%)"]] + [
        [l, str(F.units[l][1]), str(F.defects[l][1]), f"{F.defects[l][1] / F.units[l][1] * 100:.2f}"] for l in LINES]
    annual_line = [["Production Line", "Units Produced", "Defects", "Defect Rate (%)"]] + [
        [l, str(sum(F.units[l])), str(sum(F.defects[l])), f"{sum(F.defects[l]) / sum(F.units[l]) * 100:.2f}"] for l in LINES]
    units_q = [["Line", "Q1 units", "Q2 units", "Q3 units", "Q4 units"]] + [[l] + [str(x) for x in F.units[l]] for l in LINES]
    rate_q = [["Line", "Q1 defect rate (%)", "Q2 defect rate (%)", "Q3 defect rate (%)", "Q4 defect rate (%)"]] + [
        [l] + [f"{F.defects[l][q] / F.units[l][q] * 100:.2f}" for q in range(4)] for l in LINES]
    down_q = [["Line", "Q1 hours", "Q2 hours", "Q3 hours", "Q4 hours"]] + [[l] + [str(x) for x in F.downtime_q[l]] for l in LINES]
    shift_rows = [["Date", "Line", "Shift", "Units", "Defects"]]
    for i in range(364):
        for l in LINES:
            for s in range(3):
                k = i * 3 + s
                shift_rows.append([dstr(i), l, f"Shift {s + 1}", str(F.shift_units[l][k]), str(F.shift_defects[l][k])])
    week_rows = [["Week"] + [f"{l} units" for l in LINES] + [f"{l} defects" for l in LINES]]
    for w in range(52):
        week_rows.append([f"W{w + 1:02d}"] + [str(F.week_units[l][w]) for l in LINES] + [str(F.week_defects[l][w]) for l in LINES])
    wo = [["Work Order", "Machine", "Date", "Type", "Planned Hours", "Cost (Rs thousand)"]]
    wtypes = ["Preventive maintenance", "Lubrication", "Calibration", "Inspection", "Filter replacement"]
    allm = [m for l in LINES for m in F.machines[l]]
    for i in range(900):
        wo.append([f"WO-{i + 1:05d}", allm[(i * 5) % 24], dstr((i * 7) % 364), wtypes[i % 5], str(1 + (i * 3) % 6), str(2 + (i * 11) % 38)])
    wd_secs = []
    for l in LINES:
        wd_secs.append((f"Weekly Unplanned Downtime Hours by Machine {l}", [["Week"] + F.machines[l] + ["Total"]] + [
            [f"W{w + 1:02d}"] + [str(v) for v in F.week_down[l][w]] + [str(sum(F.week_down[l][w]))] for w in range(52)]))
    build_pdf(out / "Production_and_Maintenance_Report_FY2025.pdf", "Production and Maintenance Report FY2025", [
        ("Production Overview", [f"Total production in FY2025 was {sum(F.prod_q):,} units. Production volume peaked in Q4 at {F.prod_q[3]:,} units. The plant-wide defect rate was {F.defect_q[0]} percent in Q1, {F.defect_q[1]} percent in Q2, {F.defect_q[2]} percent in Q3 and {F.defect_q[3]} percent in Q4."], [
            ("Quarterly Production Volume", quarterly), ("Production by Line in Q2", by_line_q), ("Production by Line FY2025", annual_line)]),
        ("Production by Line and Quarter", [f"Production volume rose {pct(F.prod_q[0], F.prod_q[1])} percent between Q1 and Q2 after the second shift was added on Line B."], [("Units by Line and Quarter", units_q), ("Defect Rate by Line and Quarter", rate_q)]),
        ("Machine Downtime", ["Unplanned downtime was highest on Line B in Q2, linked to a spindle bearing failure and accelerated wear following the extra shift."], [("Unplanned Downtime by Line and Quarter", down_q)]),
        ("Weekly Production", ["Weekly units and defects by line, aggregated from the shift log."], [("Weekly Production and Defects", week_rows)]),
        ("Weekly Downtime by Machine", ["Unplanned downtime hours by machine and week. Planned maintenance is recorded separately in the work-order register."], wd_secs),
        ("Planned Maintenance Work Orders", ["Preventive and inspection work orders completed during FY2025."], [("Work Order Register", wo)], True),
        ("Shift Production Log", ["Production and defects for every shift of FY2025 (364 days, three lines, three shifts)."], [("Shift Log", shift_rows)], True),
    ])
    lots = [["Lot", "Product Family", "Line", "Sample Size", "Defects Found", "Result"]]
    for i in range(1000):
        sz = 50 + (i * 17) % 150
        dfc = (i * 29 + i // 7) % 6 if i % 9 else (i % 11)
        lots.append([f"LOT-{i + 1:05d}", F.families[i % 10], LINES[i % 3], str(sz), str(dfc), "Accept" if dfc <= max(2, sz // 60) else "Reject"])
    haz = [["Hazard ID", "Area", "Hazard", "Risk Rating", "Control"]]
    hz = [("Machining", "Rotating spindle entanglement", "High", "Guarding and interlocks"), ("Heat Treatment", "Burns from hot parts", "High", "Heat-resistant PPE and tongs"), ("Warehouse", "Forklift collision", "Medium", "Segregated walkways"),
          ("Assembly", "Manual handling injury", "Medium", "Lifting aids"), ("Grinding", "Abrasive wheel burst", "High", "Wheel inspection and speed limits"), ("Electrical", "Arc flash", "High", "Lockout-tagout")]
    for i in range(60):
        a, b, c, d_ = hz[i % 6]
        haz.append([f"HZ-{i + 1:03d}", a, b, c, d_])
    pareto = [["Root Cause", "Q1 defects", "Q2 defects", "Q3 defects", "Q4 defects"]]
    tot_q = [sum(F.defects[l][q] for l in LINES) for q in range(4)]
    shares = [0.31, 0.24, 0.18, 0.15, 0.12]
    cols = [alloc(t, shares) for t in tot_q]
    for i, cause in enumerate(["Tool wear", "Setup error", "Material variation", "Operator error", "Measurement error"]):
        pareto.append([cause] + [str(cols[q][i]) for q in range(4)])
    build_pdf(out / "Quality_and_Safety_Manual.pdf", "Quality and Safety Manual", [
        ("Quality Policy", ["The company-wide defect rate is defects divided by units produced. The target is below 2.5 percent. Corrective action is raised for any line exceeding 3.0 percent in a quarter."], []),
        ("Quarterly Defect Rate", [f"Defect rate rose from {F.defect_q[0]} percent in Q1 to {F.defect_q[1]} percent in Q2, the highest of the year, coinciding with the Q2 volume increase and Line B downtime."], [
            ("Plant Defect Rate", [["Metric", "Q1", "Q2", "Q3", "Q4"], ["Defect Rate (%)"] + [str(x) for x in F.defect_q]]), ("Defect Causes by Quarter", pareto)]),
        ("Root Cause Analysis", ["The Q2 defect increase was traced to tool wear, operator onboarding on the second shift, and insufficient first-article inspection on Line B. Corrective actions are tracked to closure."], []),
        ("Safety Performance", ["There were 3 recordable incidents in FY2025 versus 7 in FY2024. All employees complete safety induction before floor access."], [
            ("Safety Metrics", [["Metric", "FY2024", "FY2025"], ["Recordable Incidents", "7", "3"], ["Safety Training Completion (%)", "91", "99"]]), ("Hazard Register", haz)]),
        ("Lot Sampling Inspection Records", ["Sampling inspection results for 1,000 lots. Sampling defects are inspection findings and are distinct from the plant defect counts in the production report."], [("Lot Inspection Log", lots)], True),
    ])

    # ============ CUSTOMER SUPPORT ============
    tk = F.tickets
    mo = {m: [t for t in tk if t["month"] == m] for m in MONTHS}
    comp = [["Month", "P1 tickets", "P1 SLA met (%)", "P2 SLA met (%)", "P3 SLA met (%)", "P4 SLA met (%)", "Total tickets"]]
    for m in MONTHS:
        row = [m]
        p1 = [t for t in mo[m] if t["priority"] == "P1"]
        row.append(str(len(p1)))
        for p in ("P1", "P2", "P3", "P4"):
            sub = [t for t in mo[m] if t["priority"] == p]
            row.append(f"{sum(t['sla_met'] == 'Yes' for t in sub) / len(sub) * 100:.1f}" if sub else "NA")
        row.append(str(len(mo[m])))
        comp.append(row)
    overall = [["Priority", "Tickets", "SLA Met (%)", "Avg First Response (min)", "Avg Resolution (hours)"]]
    for p in ("P1", "P2", "P3", "P4"):
        sub = [t for t in tk if t["priority"] == p]
        overall.append([p, str(len(sub)), f"{sum(t['sla_met'] == 'Yes' for t in sub) / len(sub) * 100:.1f}", f"{sum(t['first_response_min'] for t in sub) / len(sub):.1f}", f"{sum(t['resolution_hours'] for t in sub) / len(sub):.1f}"])
    reg = [["Ticket", "Priority", "Month", "Product", "Tier", "First Response (min)", "Resolution (hours)", "SLA Met"]] + [
        [t["ticket_id"], t["priority"], t["month"], t["product"], t["tier"], str(t["first_response_min"]), str(t["resolution_hours"]), t["sla_met"]] for t in tk]
    tier_sla = [["Tier", "P1 First Response", "P2 First Response", "P3 First Response", "P4 First Response"], ["Platinum", "10 minutes", "30 minutes", "2 hours", "4 hours"],
                ["Gold", "15 minutes", "45 minutes", "3 hours", "6 hours"], ["Standard", "15 minutes", "1 hour", "4 hours", "8 hours"]]
    build_pdf(out / "SLA_and_Escalation_Handbook.pdf", "SLA and Escalation Handbook", [
        ("Service Level Agreement", ["Support tickets are prioritised by business impact. The targets below apply to all customers on the standard support plan."], [
            ("Standard SLA Targets", [["Priority", "First Response", "Resolution Target", "Escalation"], ["P1", "15 minutes", "4 hours", "VP Support after 30 minutes"], ["P2", "1 hour", "8 hours", "Support Manager after 2 hours"],
                                      ["P3", "4 hours", "3 business days", "Team Lead after 1 day"], ["P4", "8 hours", "7 business days", "None"]]), ("Tier-Specific First Response Targets", tier_sla)]),
        ("Priority-1 Incident Definition", ["A Priority-1 (P1) incident is a complete outage or safety-critical failure with no workaround. P1 incidents are worked continuously until resolved."], []),
        ("Escalation Policy", ["If a response or resolution target is at risk, the owner must escalate to the next level in the table above. All escalations are logged with a reason code. Major incidents trigger a post-incident review within five business days."], []),
        ("FY2025 SLA Performance", [f"The support desk handled {len(tk):,} tickets in FY2025. SLA compliance by priority and month is below; it is computed from the ticket register in Appendix A."], [("SLA Compliance by Priority", overall), ("Monthly SLA Compliance", comp)]),
        ("Appendix A: FY2025 Ticket Register", ["Complete SLA audit register of FY2025 tickets."], [("Ticket Register", reg)], True),
    ])
    prod_pages = []
    comps = ["encoder", "servo drive", "power supply", "firmware", "coolant pump", "display", "sensor array", "gearbox", "hydraulic valve", "cable harness"]
    syms = ["intermittent shutdown", "error code on display", "abnormal noise", "loss of calibration", "overheating", "no response to controls"]
    for i, p in enumerate(F.products):
        faults = [["Fault Code", "Symptom", "Probable Cause", "Recommended Action", "Priority"]]
        for k in range(6):
            faults.append([f"{p}-E{k + 1:02d}", syms[(i + k) % 6], f"Faulty {comps[(i * 3 + k) % 10]}", f"Replace or reseat {comps[(i * 3 + k) % 10]} and retest", ["P2", "P3", "P3", "P4", "P2", "P3"][k]])
        prod_pages.append((f"Product {p}", [f"Product {p} belongs to the {['Forge Controller', 'Hydraulic Press', 'Servo Module', 'Tooling Line', 'Vision Unit'][i // 6]} series. Warranty is {12 + (i % 3) * 6} months from commissioning."], [
            (f"Specification {p}", [["Parameter", "Value"], ["Model", p], ["Warranty (months)", str(12 + (i % 3) * 6)], ["Rated Voltage (V)", str(230 if i % 2 else 415)], ["Service Interval (months)", str(6 + (i % 4) * 3)]]), (f"Troubleshooting {p}", faults)], i % 2 == 0))
    build_pdf(out / "Product_Support_Manual.pdf", "Product Support Manual", [("Using this Manual", ["Each product section lists its specification and common fault codes. Escalate to the field service desk if a fault persists after the recommended action."], [])] + prod_pages)
    kb = [["KB ID", "Product", "Title", "Category", "Last Reviewed"]]
    kcat = ["Installation", "Troubleshooting", "Firmware", "Warranty", "Safety"]
    for i in range(200):
        kb.append([f"KB-{i + 1:04d}", F.products[i % 30], f"{kcat[i % 5]} guidance for {F.products[i % 30]}", kcat[i % 5], f"{MONTHS[i % 12]} 2024"])
    prod_vol = [["Product"] + MONTHS + ["Total"]]
    for p in F.products:
        row = [sum(1 for t in mo[m] if t["product"] == p) for m in MONTHS]
        prod_vol.append([p] + [str(x) for x in row] + [str(sum(row))])
    build_pdf(out / "Customer_Service_Manual.pdf", "Customer Service Manual", [
        ("Service Principles", ["Every customer contact is acknowledged within the SLA. Agents use plain language, confirm the customer's issue in their own words and never close a ticket without customer confirmation."], []),
        ("Channels and Hours", ["Phone and email support are available 24 hours a day for P1 and P2 tickets and 08:00 to 20:00 for P3 and P4."], [("Channel Targets", [["Channel", "Target Response"], ["Phone", "Answer within 60 seconds"], ["Email", "Acknowledge within 1 hour"], ["Portal", "Acknowledge within 30 minutes"]])]),
        ("Customer Satisfaction", ["CSAT is measured after every closed ticket. The FY2025 target is 90 percent satisfied or very satisfied."], [("CSAT Targets by Tier", [["Tier", "CSAT Target (%)"], ["Platinum", "95"], ["Gold", "92"], ["Standard", "88"]])]),
        ("Ticket Volume by Product", ["Ticket volume by product and month for FY2025."], [("Tickets by Product and Month", prod_vol)]),
        ("Knowledge Base Index", ["Index of knowledge articles maintained by the support team."], [("Knowledge Articles", kb)], True),
    ])
    with open(out / "Support_Tickets_FY2025.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(tk[0].keys()))
        w.writeheader()
        w.writerows(tk)

    # ============ SPREADSHEETS ============
    wb = Workbook(); ws = wb.active; ws.title = "FY2026 Budget"
    ws.append(["Department", "FY2025 Actual (Rs crore)", "FY2026 Budget (Rs crore)"])
    for d in F.dept_actual:
        ws.append([d, F.dept_actual[d], F.dept_budget[d]])
    ws2 = wb.create_sheet("Cost Center Budget")
    ws2.append(["Department", "Cost Center"] + MONTHS + ["Total (Rs lakh)"])
    for (d, cc), vals in F.budget_ledger.items():
        ws2.append([d, cc] + vals + [sum(vals)])
    wb.save(out / "Budget_and_Forecast_FY2026.xlsx")
    wb = Workbook(); ws = wb.active; ws.title = "Downtime"
    ws.append(["Line", "Q1 hours", "Q2 hours", "Q3 hours", "Q4 hours"])
    for l in LINES:
        ws.append([l] + F.downtime_q[l])
    wb.save(out / "Machine_Downtime_FY2025.xlsx")
    wb = Workbook(); ws = wb.active; ws.title = "Weekly Production"
    ws.append(["Week"] + [f"{l} units" for l in LINES])
    for wk in range(52):
        ws.append([f"W{wk + 1:02d}"] + [F.week_units[l][wk] for l in LINES])
    wb.save(out / "Weekly_Production_FY2025.xlsx")
    import json
    dept = {"Annual_Report": "finance", "Financial_Policies": "finance", "Budget_and_Forecast": "finance", "Employee_Handbook": "hr", "HR_Policies": "hr",
            "Compensation": "hr", "Manufacturing_Operations": "manufacturing", "Production_and_Maintenance": "manufacturing", "Quality_and_Safety": "manufacturing",
            "Machine_Downtime": "manufacturing", "Weekly_Production": "manufacturing", "SLA_and_Escalation": "customer_support", "Product_Support": "customer_support",
            "Customer_Service": "customer_support", "Support_Tickets": "customer_support"}
    manifest = {f.name: next(v for k, v in dept.items() if f.name.startswith(k)) for f in sorted(out.iterdir()) if f.suffix in (".pdf", ".xlsx", ".csv")}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    (out / "expected_rows.json").write_text(json.dumps(EXPECTED, indent=1))
    print("wrote", len(manifest), "files to", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "dataset")
