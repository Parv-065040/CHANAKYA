import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app.config import Settings
from app.parsers import ParseError, parse_document
from app.server import App, make_handler, seed_dataset

DATASET = Path(__file__).parent.parent / "data" / "dataset"


class ParserTests(unittest.TestCase):
    def test_pdf_tables_and_pages(self):
        blocks = parse_document("Annual_Report_FY2025.pdf", (DATASET / "Annual_Report_FY2025.pdf").read_bytes())
        tables = [b for b in blocks if b.kind == "table"]
        self.assertGreaterEqual(len(tables), 10)
        rev = next(r for t in tables for r in t.rows if r[0] == "Revenue")
        self.assertEqual(rev, ("Revenue", "125.0", "148.2"))
        self.assertTrue(all(b.page >= 1 for b in blocks))

    def test_csv_xlsx(self):
        self.assertEqual(parse_document("a.csv", b"a,b\n1,2\n3,4\n")[1].rows[0], ("a", "b"))
        x = parse_document("Budget.xlsx", (DATASET / "Budget_and_Forecast_FY2026.xlsx").read_bytes())
        self.assertTrue(any(b.kind == "table" for b in x))

    def test_rejections(self):
        for name, data in [("a.exe", b"x"), ("a.pdf", b"not a pdf"), ("a.pdf", b""), ("a.csv", b"only header\n"), ("a.xlsx", b"junk")]:
            with self.assertRaises(ParseError, msg=name):
                parse_document(name, data)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(Settings(data_dir=Path(tempfile.mkdtemp()), groq_api_key="", rate_limit_per_minute=1000))
        seed_dataset(cls.app)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, method, path, body=None, raw=False):
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, (r.read() if raw else json.loads(r.read()))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_health_and_departments(self):
        s, h = self.call("GET", "/health")
        self.assertEqual((s, h["status"], h["llm"]), (200, "ok", "offline"))
        self.assertGreater(h["chunks"], 40)
        self.assertEqual({d["name"] for d in self.call("GET", "/departments")[1]}, {"finance", "hr", "manufacturing", "customer_support"})

    def test_query_revenue_with_citation_and_calc(self):
        s, r = self.call("POST", "/query", {"question": "What was revenue in FY2025 and how much did it grow from FY2024?"})
        self.assertEqual(s, 200)
        self.assertIn("18.56", r["answer"])
        self.assertTrue(r["grounded"])
        self.assertEqual(r["sources"][0]["document"], "Annual_Report_FY2025.pdf")
        self.assertTrue(any("18.56" in c for c in r["calculations"]))

    def test_unanswerable_refuses(self):
        s, r = self.call("POST", "/query", {"question": "What was the company's stock price on 3 October 2026?"})
        self.assertEqual((r["mode"], r["sources"]), ("refusal", []))
        self.assertIn("could not find sufficient evidence", r["answer"])

    def test_department_filter_blocks_other_departments(self):
        s, r = self.call("POST", "/query", {"question": "What was revenue in FY2025?", "department": "hr"})
        docs = {e["document"] for e in r["evidence"]}
        self.assertNotIn("Annual_Report_FY2025.pdf", docs)

    def test_validation_errors(self):
        self.assertEqual(self.call("POST", "/query", {"question": "x"})[0], 422)
        self.assertEqual(self.call("POST", "/query", {"question": "valid question?", "department": "nope"})[0], 422)
        self.assertEqual(self.call("POST", "/query", b"{bad")[0], 400)
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("POST", "/documents/upload?filename=a.exe&department=hr", b"x")[0], 422)
        self.assertEqual(self.call("POST", "/documents/upload?filename=a.csv", b"a,b\n1,2\n")[0], 422)

    def test_stream_events(self):
        s, raw = self.call("POST", "/query/stream", {"question": "What is the SLA for Priority-1 incidents?"}, raw=True)
        text = raw.decode()
        self.assertIn("event: token", text)
        self.assertIn("event: done", text)
        self.assertIn("15 minutes", text)

    def test_upload_version_delete_cycle(self):
        csv1, csv2 = b"Metric,FY2025\nWidget Output,100\nWidget Scrap,5\n", b"Metric,FY2025\nWidget Output,120\nWidget Scrap,5\n"
        s, d1 = self.call("POST", "/documents/upload?filename=widgets.csv&department=manufacturing", csv1)
        self.assertEqual((s, d1["version"], d1["status"]), (201, 1, "indexed"))
        s, same = self.call("POST", "/documents/upload?filename=widgets.csv&department=manufacturing", csv1)
        self.assertEqual(same["document_id"], d1["document_id"])  # idempotent
        s, d2 = self.call("POST", "/documents/upload?filename=widgets.csv&department=manufacturing", csv2)
        self.assertEqual(d2["version"], 2)
        docs = {d["document_id"]: d for d in self.call("GET", "/documents")[1]}
        self.assertEqual(docs[d1["document_id"]]["status"], "superseded")
        self.assertEqual(self.call("GET", f"/documents/{d2['document_id']}")[0], 200)
        s, r = self.call("POST", "/query", {"question": "What was Widget Output in FY2025?"})
        self.assertIn("120", r["answer"])
        self.assertNotIn("100 in", r["answer"])
        self.assertEqual(self.call("DELETE", f"/documents/{d2['document_id']}")[0], 200)
        self.assertEqual(self.call("DELETE", f"/documents/{d2['document_id']}")[0], 404)

    def test_source_endpoint(self):
        s, r = self.call("POST", "/query", {"question": "Which production line had the highest defect rate?"})
        cid = next(e for e in self.app.kb.chunks.values() if e.document_name.startswith("Manufacturing")).chunk_id
        self.assertEqual(self.call("GET", f"/sources/{cid}")[0], 200)
        self.assertIn("Line B", r["answer"])

    def test_rate_limit_and_persistence(self):
        app = App(Settings(data_dir=Path(tempfile.mkdtemp()), rate_limit_per_minute=2))
        self.assertTrue(app.limiter.allow("ip") and app.limiter.allow("ip"))
        self.assertFalse(app.limiter.allow("ip"))
        d = self.app.settings.data_dir
        reloaded = App(Settings(data_dir=d))
        self.assertEqual(len(reloaded.kb.chunks), len(self.app.kb.chunks))
        self.assertEqual(reloaded.kb.vector_search("revenue", 1, None)[0][0], self.app.kb.vector_search("revenue", 1, None)[0][0])


if __name__ == "__main__":
    unittest.main()
