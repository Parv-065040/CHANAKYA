"""HTTP API + static UI (stdlib only; runs anywhere Python 3.11+ with numpy/pypdf/openpyxl/requests).

Endpoints: GET /health /departments /documents /documents/{id} /sources/{chunk_id} /evaluation/summary
           POST /documents/upload?filename=&department=  (raw bytes body)   POST /query   POST /query/stream (SSE)
           DELETE /documents/{id}
"""
from __future__ import annotations

import hmac
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .config import Settings
from .core.router import DEFAULT_DEPARTMENTS
from .embeddings import make_embedder
from .llm import GroqClient
from .parsers import ParseError
from .pipeline import Orchestrator
from .retrieval import HybridRetriever
from .store import KnowledgeBase

log = logging.getLogger("chanakya.api")
STATIC = Path(__file__).parent / "static"
EVAL_SUMMARY = Path(__file__).parent.parent / "eval" / "last_results.json"


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute, self.hits, self.lock = per_minute, defaultdict(deque), threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


class Auth:
    """Optional bearer-token auth. AUTH_MODE=none (default, local demo) | tokens.

    ADMIN_TOKEN: may upload/delete and query every department.
    USER_TOKENS: JSON {"token": ["finance", "hr"] | "*"}: query-only, limited to those departments.
    """

    def __init__(self, s: Settings) -> None:
        self.mode, self.admin = s.auth_mode, s.admin_token
        try:
            self.users: dict[str, object] = json.loads(s.user_tokens or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("USER_TOKENS must be valid JSON") from exc
        if self.mode == "tokens" and not (self.admin or self.users):
            raise ValueError("AUTH_MODE=tokens requires ADMIN_TOKEN and/or USER_TOKENS")

    def identify(self, header: str | None) -> tuple[str, set[str] | None] | None:
        """-> (role, allowed departments or None for all) or None when unauthenticated."""
        if self.mode == "none":
            return "admin", None
        tok = (header or "").removeprefix("Bearer ").strip()
        if not tok:
            return None
        if self.admin and hmac.compare_digest(tok, self.admin):
            return "admin", None
        for t, depts in self.users.items():
            if hmac.compare_digest(tok, t):
                return "user", None if depts == "*" else set(depts)  # type: ignore[arg-type]
        return None


def make_persistence(s: Settings, embedder):  # noqa: ANN001, ANN201
    from .persistence import LocalPersistence, SupabasePersistence
    fp = KnowledgeBase.fingerprint_of(s, embedder)
    if s.storage_backend == "supabase":
        if not (s.supabase_url and s.supabase_service_key):
            raise ValueError("STORAGE_BACKEND=supabase requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
        return SupabasePersistence(s.supabase_url, s.supabase_service_key, s.supabase_bucket, fp)
    if s.storage_backend != "local":
        raise ValueError(f"unknown STORAGE_BACKEND {s.storage_backend!r}")
    return LocalPersistence(s.data_dir, fp)


class App:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        embedder = make_embedder(self.settings)
        self.auth = Auth(self.settings)
        self.seeding = False
        self.kb = KnowledgeBase(self.settings, embedder, set(DEFAULT_DEPARTMENTS), make_persistence(self.settings, embedder))
        self.llm = GroqClient(self.settings)
        self.orch = Orchestrator(self.kb, HybridRetriever(self.kb, self.settings.min_relevance, self.settings.min_coverage, settings=self.settings), self.llm)
        self.limiter = RateLimiter(self.settings.rate_limit_per_minute)


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "CHANAKYA/1.0"

        def log_message(self, fmt: str, *args) -> None:  # structured logging instead of stderr spam
            log.info("%s %s", self.address_string(), fmt % args)

        # -- helpers
        def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", app.settings.cors_origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj: object) -> None:
            self._send(status, json.dumps(obj).encode())

        def _err(self, status: int, code: str, message: str) -> None:
            self._json(status, {"error": {"code": code, "message": message}})

        def _body(self, limit: int) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise ValueError("payload too large")
            return self.rfile.read(n)

        def _who(self, need_admin: bool = False):  # noqa: ANN202
            ident = app.auth.identify(self.headers.get("Authorization"))
            if ident is None:
                self._err(401, "unauthorized", "missing or invalid bearer token")
                return None
            if need_admin and ident[0] != "admin":
                self._err(403, "forbidden", "admin token required")
                return None
            return ident

        def do_OPTIONS(self) -> None:
            self._send(204, b"")

        # -- routing
        def do_GET(self) -> None:
            u = urlparse(self.path)
            try:
                if u.path in ("/", "/index.html"):
                    return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                if u.path == "/health":
                    return self._json(200, {"status": "seeding" if app.seeding else "ok", "auth": app.auth.mode, "storage": app.settings.storage_backend, "documents": len(app.kb.docs), "chunks": len(app.kb.chunks),
                                            "llm": "groq" if app.llm.available else "offline",
                                            "embedding": app.settings.embedding_provider})
                if u.path == "/departments":
                    return self._json(200, [{"name": d.name, "label": d.label} for d in DEFAULT_DEPARTMENTS.values()])
                if u.path == "/documents":
                    if not self._who():
                        return
                    return self._json(200, [asdict(d) for d in app.kb.list_documents()])
                m = re.fullmatch(r"/documents/([a-f0-9]+)", u.path)
                if m:
                    if not self._who():
                        return
                    d = app.kb.docs.get(m.group(1))
                    return self._json(200, asdict(d)) if d else self._err(404, "not_found", "document not found")
                m = re.fullmatch(r"/documents/([a-f0-9]+)/file", u.path)
                if m:
                    ident = self._who()
                    if not ident:
                        return
                    doc = app.kb.docs.get(m.group(1))
                    if not doc:
                        return self._err(404, "not_found", "document not found")
                    if ident[1] is not None and doc.department not in ident[1]:
                        return self._err(403, "forbidden", "no access to department")
                    ctype = {
                        ".pdf": "application/pdf",
                        ".csv": "text/csv; charset=utf-8",
                        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    }.get(Path(doc.name).suffix.lower(), "application/octet-stream")
                    if app.settings.storage_backend == "local":
                        root = Path(app.settings.data_dir).resolve() / "files"
                        matches = list(root.glob(f"{doc.document_id}_{doc.name}"))
                        if not matches:
                            return self._err(404, "not_found", "document file not found")
                        path = matches[0].resolve()
                        if root not in path.parents:
                            return self._err(400, "invalid_path", "invalid document path")
                        data = path.read_bytes()
                    else:
                        # Use the configured persistence instance directly. Avoid a strict
                        # isinstance check here because module reloads/import paths can produce a
                        # different class identity even when the backend is correctly configured.
                        storage = app.kb.persist
                        if not all(hasattr(storage, attr) for attr in ("_req", "bucket")):
                            return self._err(500, "storage_error", "document storage is not configured correctly")
                        object_path = f"{doc.document_id}_{doc.name}"
                        try:
                            # Proxy the private Storage object through the API. This is deliberately
                            # server-side so the Supabase service-role key never reaches the browser.
                            # The upload limit is small enough for this to be practical and it avoids
                            # relying on Storage signed-URL response formats.
                            stored = app.kb.persistence._req(
                                "GET",
                                f"/storage/v1/object/{app.kb.persistence.bucket}/{quote(object_path, safe='/')}",
                            )
                            data = stored.content
                        except Exception as exc:
                            log.exception("document storage read failed for %s (%s): %s", doc.document_id, object_path, exc)
                            return self._err(404, "not_found", "document file is not available in document storage")
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Content-Disposition", f'inline; filename="{doc.name}"')
                    self.send_header("Access-Control-Allow-Origin", app.settings.cors_origin)
                    self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                    self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                m = re.fullmatch(r"/sources/([a-f0-9]+)", u.path)
                if m:
                    ident = self._who()
                    if not ident:
                        return
                    c = app.kb.chunks.get(m.group(1))
                    if c and ident[1] is not None and c.department not in ident[1]:
                        c = None  # do not reveal chunks outside the caller's departments
                    return self._json(200, asdict(c)) if c else self._err(404, "not_found", "source not found")
                if u.path == "/evaluation/summary":
                    if EVAL_SUMMARY.exists():
                        return self._json(200, json.loads(EVAL_SUMMARY.read_text())["summary"])
                    return self._err(404, "no_results", "run `python -m eval.run_eval` first")
                return self._err(404, "not_found", "unknown route")
            except Exception:  # noqa: BLE001
                log.exception("GET failed")
                return self._err(500, "internal_error", "internal server error")

        def do_DELETE(self) -> None:
            m = re.fullmatch(r"/documents/([a-f0-9]+)", urlparse(self.path).path)
            if not m:
                return self._err(404, "not_found", "unknown route")
            if not self._who(need_admin=True):
                return
            ok = app.kb.delete(m.group(1))
            return self._json(200, {"deleted": True}) if ok else self._err(404, "not_found", "document not found")

        def do_POST(self) -> None:
            u = urlparse(self.path)
            try:
                if u.path == "/documents/upload":
                    if not self._who(need_admin=True):
                        return
                    qs = parse_qs(u.query)
                    name, dept = (qs.get("filename") or [""])[0], (qs.get("department") or [""])[0]
                    if not name or not dept:
                        return self._err(422, "validation_error", "filename and department are required")
                    data = self._body(app.settings.max_upload_mb * 1024 * 1024)
                    rec = app.kb.ingest(name, data, dept)
                    return self._json(201, asdict(rec))
                if u.path in ("/query", "/query/stream"):
                    ident = self._who()
                    if not ident:
                        return
                    ip = self.client_address[0]
                    if not app.limiter.allow(ip):
                        return self._err(429, "rate_limited", "Too many requests; please wait a minute.")
                    try:
                        payload = json.loads(self._body(65536) or b"{}")
                    except json.JSONDecodeError:
                        return self._err(400, "bad_json", "request body must be JSON")
                    q = str(payload.get("question", "")).strip()
                    if not (3 <= len(q) <= 1000):
                        return self._err(422, "validation_error", "question must be 3-1000 characters")
                    dept = payload.get("department") or None
                    if dept and dept not in DEFAULT_DEPARTMENTS:
                        return self._err(422, "validation_error", f"unknown department {dept!r}")
                    if dept and ident[1] is not None and dept not in ident[1]:
                        return self._err(403, "forbidden", f"no access to department {dept!r}")
                    res = app.orch.ask(q, department=dept, allowed=ident[1])
                    if u.path == "/query":
                        return self._json(200, asdict(res))
                    return self._stream(res)
                return self._err(404, "not_found", "unknown route")
            except (ParseError, ValueError) as exc:
                return self._err(422 if not isinstance(exc, ValueError) or "large" not in str(exc) else 413, "validation_error", str(exc))
            except Exception:  # noqa: BLE001
                log.exception("POST failed")
                return self._err(500, "internal_error", "internal server error")

        def _stream(self, res) -> None:  # noqa: ANN001
            """SSE: tokens of the *validated* answer, then a final 'done' event with sources/evidence."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", app.settings.cors_origin)
            self.end_headers()
            try:
                for tok in re.findall(r"\S+\s*", res.answer):
                    self.wfile.write(f"event: token\ndata: {json.dumps(tok)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.01)
                self.wfile.write(f"event: done\ndata: {json.dumps(asdict(res))}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


def seed_dataset(app: App) -> int:
    """Ingest the bundled synthetic dataset if the knowledge base is empty."""
    ds = Path(__file__).parent.parent / "data" / "dataset"
    if app.kb.docs or not (ds / "manifest.json").exists():
        return 0
    manifest = json.loads((ds / "manifest.json").read_text())
    n = 0
    for name, dept in manifest.items():
        if (ds / name).exists():
            try:
                app.kb.ingest(name, (ds / name).read_bytes(), dept)
                n += 1
            except Exception:  # noqa: BLE001 - keep seeding the rest
                log.exception("seeding failed for %s", name)
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='{"t":"%(asctime)s","lvl":"%(levelname)s","log":"%(name)s","msg":"%(message)s"}')
    app = App()
    if app.settings.seed_demo_data and not app.kb.docs:
        def _seed() -> None:
            app.seeding = True
            try:
                log.info("seeded %d demo documents (CHANAKYA Demonstration Dataset, synthetic)", seed_dataset(app))
            finally:
                app.seeding = False
        threading.Thread(target=_seed, daemon=True).start()
    srv = ThreadingHTTPServer((app.settings.host, app.settings.port), make_handler(app))
    log.info("CHANAKYA on http://%s:%d (llm=%s storage=%s auth=%s embeddings=%s)", app.settings.host, app.settings.port,
             "groq" if app.llm.available else "offline", app.settings.storage_backend, app.auth.mode, app.settings.embedding_provider)
    srv.serve_forever()


if __name__ == "__main__":
    main()
