"""Supabase adapter against a local PostgREST/Storage stub, plus auth and config behaviour."""
import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.embeddings import HashingEmbedder
from app.persistence import SupabasePersistence
from app.server import App, Auth, make_handler, make_persistence
from app.store import KnowledgeBase

PK = {"documents": "document_id", "chunks": "chunk_id", "app_meta": "key"}


class FakeSupabase(BaseHTTPRequestHandler):
    tables: dict = {}
    storage: dict = {}
    calls: list = []

    def log_message(self, *a):
        pass

    def _reply(self, code, obj=None):
        b = json.dumps(obj if obj is not None else []).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _filter(self, rows, qs):
        for k, v in qs.items():
            if v[0].startswith("eq."):
                rows = [r for r in rows if str(r.get(k)) == v[0][3:]]
        return rows

    def handle_any(self, method):
        u = urlparse(self.path)
        FakeSupabase.calls.append((method, u.path, self.headers.get("apikey")))
        if self.headers.get("apikey") != "svc-key":
            return self._reply(401, {"message": "bad key"})
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        m = re.fullmatch(r"/rest/v1/(\w+)", u.path)
        if m:
            t = m.group(1)
            rows = self.tables.setdefault(t, {})
            qs = parse_qs(u.query)
            if method == "POST":
                for r in json.loads(body):
                    if t == "chunks" and "embedding" in r:
                        assert re.fullmatch(r"\[[-0-9eE.,+]+\]", r["embedding"]), "pgvector literal"
                    rows[r[PK[t]]] = r
                return self._reply(201)
            sel = self._filter(list(rows.values()), {k: v for k, v in qs.items() if k not in ("select", "order", "limit", "offset")})
            if method == "GET":
                off, lim = int(qs.get("offset", ["0"])[0]), int(qs.get("limit", ["1000"])[0])
                return self._reply(200, sel[off:off + lim])
            if method == "PATCH":
                for r in sel:
                    r.update(json.loads(body))
                return self._reply(204)
            if method == "DELETE":
                for r in sel:
                    rows.pop(r[PK[t]], None)
                return self._reply(204)
        m = re.fullmatch(r"/storage/v1/object/([\w-]+)/(.+)", u.path)
        if m and method == "POST":
            self.storage[m.group(2)] = body
            return self._reply(200, {"Key": m.group(2)})
        return self._reply(404, {"message": "not found"})

    do_GET = lambda self: self.handle_any("GET")  # noqa: E731
    do_POST = lambda self: self.handle_any("POST")  # noqa: E731
    do_PATCH = lambda self: self.handle_any("PATCH")  # noqa: E731
    do_DELETE = lambda self: self.handle_any("DELETE")  # noqa: E731


DATASET = Path(__file__).parent.parent / "data" / "dataset"
CSV1 = b"Metric,FY2025\nWidget Output,100\nWidget Scrap,5\n"


class SupabaseTests(unittest.TestCase):
    def setUp(self):
        FakeSupabase.tables, FakeSupabase.storage, FakeSupabase.calls = {}, {}, []
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeSupabase)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.settings = Settings(data_dir=Path(tempfile.mkdtemp()), storage_backend="supabase", supabase_url=self.url,
                                 supabase_service_key="svc-key", supabase_bucket="b", groq_api_key="")

    def tearDown(self):
        self.srv.shutdown()

    def kb(self):
        emb = HashingEmbedder(1024)
        return KnowledgeBase(self.settings, emb, {"manufacturing", "hr"}, make_persistence(self.settings, emb))

    def test_roundtrip_ingest_restart_delete(self):
        kb = self.kb()
        rec = kb.ingest("w.csv", CSV1, "manufacturing")
        self.assertEqual(len(FakeSupabase.tables["chunks"]), rec.n_chunks)
        self.assertEqual(len(FakeSupabase.storage), 1)
        kb2 = self.kb()  # fresh process reads everything back from Supabase
        self.assertEqual(len(kb2.chunks), rec.n_chunks)
        self.assertEqual(kb2.vector_search("widget output", 1, None)[0][0], kb.vector_search("widget output", 1, None)[0][0])
        v2 = kb2.ingest("w.csv", CSV1.replace(b"100", b"120"), "manufacturing")
        self.assertEqual(v2.version, 2)
        self.assertEqual(FakeSupabase.tables["documents"][rec.document_id]["status"], "superseded")
        self.assertTrue(kb2.delete(v2.document_id))
        self.assertNotIn(v2.document_id, FakeSupabase.tables["documents"])
        self.assertEqual(FakeSupabase.tables["chunks"], {})

    def test_bad_key_surfaces_clear_error_and_rolls_back(self):
        self.settings = Settings(**{**self.settings.__dict__, "supabase_service_key": "wrong"})
        emb = HashingEmbedder(1024)
        with self.assertRaises(RuntimeError):
            KnowledgeBase(self.settings, emb, {"manufacturing"}, make_persistence(self.settings, emb))

    def test_failed_write_rolls_back_memory(self):
        kb = self.kb()
        kb.persist.h["apikey"] = "wrong"
        with self.assertRaises(RuntimeError):
            kb.ingest("w.csv", CSV1, "manufacturing")
        self.assertEqual((len(kb.docs), len(kb.chunks), len(kb.bm25)), (0, 0, 0))

    def test_pagination_over_500_rows(self):
        kb = self.kb()
        rows = "\n".join(f"Item {i},{i}" for i in range(1, 3000))
        kb.ingest("big.csv", f"Metric,FY2025\n{rows}\n".encode(), "manufacturing")
        n = len(kb.chunks)
        self.assertGreater(n, 5)
        self.assertEqual(len(self.kb().chunks), n)

    def test_config_errors(self):
        with self.assertRaises(ValueError):
            make_persistence(Settings(storage_backend="supabase", supabase_url="", supabase_service_key=""), HashingEmbedder(8))
        with self.assertRaises(ValueError):
            make_persistence(Settings(storage_backend="s3"), HashingEmbedder(8))

    def test_embedding_model_change_triggers_reembed(self):
        kb = self.kb()
        kb.ingest("w.csv", CSV1, "manufacturing")
        s2 = Settings(**{**self.settings.__dict__, "embedding_model": "other-model"})
        emb = HashingEmbedder(1024)
        kb2 = KnowledgeBase(s2, emb, {"manufacturing"}, make_persistence(s2, emb))
        self.assertEqual(len(kb2.chunks), len(kb.chunks))
        self.assertTrue(any(r.get("embedding") for r in FakeSupabase.tables["chunks"].values()))
        fp = FakeSupabase.tables["app_meta"]["fingerprint"]["value"]
        self.assertIn("other-model", fp)


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = Settings(data_dir=Path(tempfile.mkdtemp()), groq_api_key="", auth_mode="tokens", admin_token="adm",
                     user_tokens=json.dumps({"fin": ["finance"], "all": "*"}), rate_limit_per_minute=1000)
        cls.app = App(s)
        cls.app.kb.ingest("rev.csv", b"Metric,FY2025\nRevenue,148.2\nOther,1\n", "finance")
        cls.app.kb.ingest("leave.csv", b"Leave Type,Days\nEarned Leave,24\nSick Leave,10\n", "hr")
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, method, path, body=None, token=None):
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + path, data=data, method=method, headers=h)) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_unauthenticated_rejected_health_open(self):
        self.assertEqual(self.call("GET", "/health")[0], 200)
        self.assertEqual(self.call("POST", "/query", {"question": "What was Revenue?"})[0], 401)
        self.assertEqual(self.call("GET", "/documents")[0], 401)
        self.assertEqual(self.call("GET", "/documents", token="nope")[0], 401)

    def test_user_limited_to_departments(self):
        s, r = self.call("POST", "/query", {"question": "How many days of earned leave?"}, "fin")
        self.assertEqual(s, 200)
        self.assertEqual(r["mode"], "refusal")  # hr data is invisible to the finance user
        s, r = self.call("POST", "/query", {"question": "How many days of earned leave?", "department": "hr"}, "fin")
        self.assertEqual(s, 403)
        s, r = self.call("POST", "/query", {"question": "How many days of earned leave?"}, "all")
        self.assertIn("24", r["answer"])

    def test_upload_delete_need_admin(self):
        self.assertEqual(self.call("POST", "/documents/upload?filename=a.csv&department=hr", b"a,b\n1,2\n", "all")[0], 403)
        s, d = self.call("POST", "/documents/upload?filename=a.csv&department=hr", b"Item,Val\nAlpha,1\nBeta,2\n", "adm")
        self.assertEqual(s, 201)
        self.assertEqual(self.call("DELETE", f"/documents/{d['document_id']}", token="fin")[0], 403)
        self.assertEqual(self.call("DELETE", f"/documents/{d['document_id']}", token="adm")[0], 200)

    def test_sources_hidden_across_departments(self):
        hr_chunk = next(c for c in self.app.kb.chunks.values() if c.department == "hr").chunk_id
        self.assertEqual(self.call("GET", f"/sources/{hr_chunk}", token="fin")[0], 404)
        self.assertEqual(self.call("GET", f"/sources/{hr_chunk}", token="adm")[0], 200)

    def test_auth_config_validation(self):
        with self.assertRaises(ValueError):
            Auth(Settings(auth_mode="tokens", admin_token="", user_tokens="{}"))
        with self.assertRaises(ValueError):
            Auth(Settings(auth_mode="tokens", admin_token="x", user_tokens="not json"))


if __name__ == "__main__":
    unittest.main()
