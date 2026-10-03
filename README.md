# CHANAKYA: Agentic Enterprise Knowledge Platform

Turn enterprise documents into cited, numerically-correct answers. Four departments (Finance, HR, Manufacturing, Customer Support),
hybrid retrieval, a deterministic numerical engine, a citation/grounding validator, and refusal when evidence is missing.

Course: Agentic AI for Business Automation. Professor: Ashok Harnal. Team: Parv Jhamb (065040), Awantika Kholia (065060), Aman Malhi (065010).

## Quick start (works with zero keys, offline)
```
cd backend
pip install -r requirements.txt
python -m app.server            # http://localhost:8000
```
First start indexes the bundled synthetic knowledge base in the background (about 20 seconds; the page shows progress). Later starts load from disk.

## Plug in your keys (copy `.env.example` to `.env`, or set variables in your host)
| What | Variables | Notes |
|---|---|---|
| LLM | `GROQ_API_KEY`, `GROQ_MODEL=openai/gpt-oss-120b` | Without a key the app answers deterministically from the evidence. |
| Database | `STORAGE_BACKEND=supabase`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_BUCKET` | Run `backend/sql/schema.sql` in the Supabase SQL editor; create a private bucket. Service-role key stays server-side. |
| Embeddings | `EMBEDDING_PROVIDER=sentence-transformers` (local BGE-M3) or `hf-inference` + `HF_API_TOKEN` + `HF_EMBED_URL` | Changing model re-embeds automatically at start-up. `EMBEDDING_DIMENSION` must match `vector(N)` in the schema. |
| Access control | `AUTH_MODE=tokens`, `ADMIN_TOKEN`, `USER_TOKENS={"tok":["finance"],"exec":"*"}` | Admin uploads/deletes; users query only their departments. Enter the token in the UI. |

Docker: `docker compose up --build` (reads `.env`). `render.yaml` is a ready blueprint for Render's free tier.

## What is verified vs. not (read this before you present)
Verified in this build (run in a sandbox with no internet): 76 automated tests pass; end-to-end server smoke test with restart persistence;
Supabase adapter tested against a local PostgREST/Storage **stub**; evaluation on 130 questions.

**Never run against real services, because the sandbox had no network or keys:**
- Groq / GPT-OSS 120B calls (client tested with mocks; confirm the model id and rate limits in Groq's console).
- Real Supabase (request shapes follow the documented REST API; stub-tested only). pgvector search happens in memory after loading vectors at start-up. The HNSW index in the schema is not used by queries.
- BGE-M3 via sentence-transformers or Hugging Face Inference (adapters written; HF endpoint URL is yours to supply).
- Docker build, Render deployment, OCR for scanned PDFs (needs `pytesseract`, untested).

**Deliberate deviations from the original spec:** stdlib HTTP server + single HTML page instead of FastAPI + Next.js (same endpoints; avoids
dependencies that could not be installed here); keyword/IDF reranker instead of a cross-encoder; token auth instead of Supabase Auth/RLS.

## Knowledge base (synthetic, fictional "Veritas Forge Industries Ltd")
16 files: 12 PDFs (**321 pages**), 3 XLSX, 1 CSV (3,000 tickets). Not the 500+ pages originally targeted: reaching that would have required filler,
which would only inflate page count without adding testable content. About 70% of pages are data tables and registers (customer revenue,
cost-center ledger, shift production log, work orders, ticket register); manuals mix hand-written policy text with parameter-generated
per-machine / per-product sections, so they are repetitive in style. All numbers come from one model (`backend/data/facts.py`); sums tie across documents and are asserted in `tests/test_dataset.py`.
Regenerate: `python data/generate_dataset.py`.

## Evaluation (`python -m eval.run_eval`, results in `eval/last_results.json`, served at `/evaluation/summary`)
130 questions (118 answerable, 12 unanswerable), generated from the same fact model, offline mode, hashing embeddings:
retrieval hit rate 100%, answer accuracy 100%, grounded 99%, refusal accuracy 92% (11/12).
**Caveat:** I iterated on the retriever/table agent while looking at failures on these same questions, so these are development-set numbers, not held-out.
Known failure: "What is the salary of the managing director?" is answered with an unrelated bonus sentence instead of refusing; a coverage threshold that
rejects it would also reject valid questions, so I left it.
Offline answers are templated ("X was A in FY2024 and B in FY2025"); LLM mode gives more natural prose but is validated against the same evidence.

## API
GET `/health` `/departments` `/documents` `/documents/{id}` `/sources/{chunk_id}` `/evaluation/summary`;
POST `/documents/upload?filename=&department=` (raw body), `/query`, `/query/stream` (SSE); DELETE `/documents/{id}`.
Streaming sends the already-validated answer word by word (validation needs the full text).

## Architecture
`core/router.py` (department + question type, access allow-list) -> `retrieval.py` (vector + BM25 -> RRF -> rerank -> sufficiency gate)
-> `tables.py` + `core/numerics.py` (table facts, Decimal math with formulas) -> `llm.py` or offline composer -> `core/citations.py`
(rejects fabricated sources, uncited numbers, unsupported figures; a failing LLM answer is replaced by the verified answer).
Add a department: one `DepartmentConfig` in `core/router.py`, plus a manifest entry.

## Limits and honest notes
Free tiers (Groq, Supabase, hosts) have quotas; the app rate-limits per IP and falls back to offline answers when the LLM is unavailable.
Everything is held in memory at runtime (fine for tens of thousands of chunks). Scanned PDFs without OCR are rejected with a clear message. Dataset is synthetic; do not present it as real company data.
