"""Cross-document consistency checks on the generated dataset (parsed back from the PDFs)."""
import json
import unittest
from pathlib import Path

from app.parsers import parse_document

DS = Path(__file__).parent.parent / "data" / "dataset"


def tables(name):
    return [b for b in parse_document(name, (DS / name).read_bytes()) if b.kind == "table"]


def find(name, first_cell, header0=None):
    for t in tables(name):
        if header0 and t.rows[0][0] != header0:
            continue
        for r in t.rows:
            if r[0] == first_cell:
                return r
    raise AssertionError(f"{first_cell} not found in {name}")


class DatasetTests(unittest.TestCase):
    def test_all_generated_table_rows_were_parsed(self):
        exp = json.loads((DS / "expected_rows.json").read_text())
        for name, n in exp.items():
            got = sum(len(t.rows) - 1 for t in tables(name))
            self.assertGreaterEqual(got, n, name)

    def test_quarterly_production_and_defects_agree_across_documents(self):
        pm = find("Production_and_Maintenance_Report_FY2025.pdf", "Production Volume (units)")
        self.assertEqual(pm[1:], ("41200", "47800", "49500", "52300"))
        qs = find("Quality_and_Safety_Manual.pdf", "Defect Rate (%)")
        self.assertEqual(qs[1:], ("2.4", "3.1", "2.8", "2.5"))

    def test_shift_log_sums_to_quarterly_totals(self):
        t = [t for t in tables("Production_and_Maintenance_Report_FY2025.pdf") if t.rows[0] == ("Date", "Line", "Shift", "Units", "Defects")]
        rows = [r for tb in t for r in tb.rows if r[0] != "Date"]
        self.assertEqual(len(rows), 364 * 9)
        self.assertEqual(sum(int(r[3]) for r in rows), 190800)
        self.assertEqual(sum(int(r[3]) for r in rows if r[1] == "Line B"), 63000)

    def test_cost_center_ledger_ties_to_opex(self):
        t = [t for t in tables("Annual_Report_FY2025.pdf") if t.rows[0][:2] == ("Department", "Cost Center")]
        total_lakh = sum(int(r[-1]) for tb in t for r in tb.rows if r[0] != "Department")
        self.assertEqual(total_lakh, 11250)  # Rs 112.5 crore
        self.assertEqual(find("Annual_Report_FY2025.pdf", "Operating Expenses")[2], "112.5")

    def test_customer_register_sums_to_revenue(self):
        t = [t for t in tables("Annual_Report_FY2025.pdf") if t.rows[0][0] == "Customer"]
        rows = [r for tb in t for r in tb.rows if r[0] != "Customer"]
        self.assertEqual(len(rows), 200)
        self.assertAlmostEqual(sum(float(r[3]) for r in rows), 148.2, places=1)
        self.assertAlmostEqual(sum(float(r[2]) for r in rows), 125.0, places=1)

    def test_attrition_consistent_between_handbook_and_annual_report(self):
        hb = find("Employee_Handbook_FY2025.pdf", "Attrition Rate (%)")
        self.assertEqual(hb[1:], ("14.8", "11.2"))
        self.assertEqual(find("Employee_Handbook_FY2025.pdf", "FY2025 Total")[-1], "211")

    def test_ticket_register_matches_csv_and_compliance(self):
        csv_rows = (DS / "Support_Tickets_FY2025.csv").read_text().strip().splitlines()
        self.assertEqual(len(csv_rows) - 1, 3000)
        reg = [r for tb in tables("SLA_and_Escalation_Handbook.pdf") if tb.rows[0][0] == "Ticket" for r in tb.rows if r[0] != "Ticket"]
        self.assertEqual(len(reg), 3000)
        p1 = [r for r in reg if r[1] == "P1"]
        pct = sum(r[7] == "Yes" for r in p1) / len(p1) * 100
        comp = next(t for t in tables("SLA_and_Escalation_Handbook.pdf") if t.rows[0][:2] == ("Priority", "Tickets"))
        stated = float(next(r for r in comp.rows if r[0] == "P1")[2])
        self.assertAlmostEqual(pct, stated, places=1)

    def test_page_count_reported(self):
        from pypdf import PdfReader
        pages = sum(len(PdfReader(str(p)).pages) for p in DS.glob("*.pdf"))
        self.assertGreaterEqual(pages, 300)


if __name__ == "__main__":
    unittest.main()
