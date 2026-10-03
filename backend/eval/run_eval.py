"""Evaluation: retrieval Hit@k / MRR, answer correctness (substring match), grounding, refusal accuracy.

Usage:  python -m eval.run_eval          (uses the bundled synthetic dataset, offline mode)
Writes eval/last_results.json (served by GET /evaluation/summary).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.config import Settings
from app.core.router import DEFAULT_DEPARTMENTS, route_query
from app.embeddings import make_embedder
from app.llm import GroqClient
from app.pipeline import Orchestrator
from app.retrieval import HybridRetriever
from app.server import App, seed_dataset

def load_questions() -> list[tuple[str, str, list[str], str]]:
    path = Path(__file__).with_name("questions.json")
    return [(q["question"], q["doc"], q["must"], q["category"]) for q in json.loads(path.read_text())]


_NUM = __import__("re").compile(r"\d[\d,]*\.?\d*")


def _contains(answer: str, token: str) -> bool:
    """Substring match; numeric tokens also match by value (8 == 8.0)."""
    if token.lower() in answer.lower():
        return True
    try:
        want = float(token.replace(",", ""))
    except ValueError:
        return False
    return any(abs(float(n.replace(",", "").rstrip(".")) - want) < 1e-9 for n in _NUM.findall(answer) if n.rstrip(".").replace(",", "").replace(".", "", 1).isdigit())


def run() -> dict:
    tmp = Path(tempfile.mkdtemp())
    app = App(Settings(data_dir=tmp, groq_api_key=""))  # offline for reproducibility
    seed_dataset(app)
    rows, hits, rr, correct, refusal_ok, grounded, n_ans, n_ref = [], 0, 0.0, 0, 0, 0, 0, 0
    Q = load_questions()
    for q, doc, must, cat in Q:
        res = app.orch.ask(q)
        refused = res.mode == "refusal"
        row = {"question": q, "category": cat, "mode": res.mode, "answer": res.answer, "grounded": res.grounded}
        if cat == "unanswerable":
            n_ref += 1
            row["pass"] = refused
            refusal_ok += refused
        else:
            n_ans += 1
            docs = [e["document"] for e in res.evidence]
            rank = docs.index(doc) + 1 if doc in docs else 0
            hit = rank > 0
            hits += hit
            rr += 1 / rank if rank else 0
            ok = (not refused) and all(_contains(res.answer, m) for m in must)
            correct += ok
            grounded += res.grounded
            row.update({"retrieval_hit": hit, "rank": rank, "pass": ok})
        rows.append(row)
    summary = {
        "by_category": {c: round(sum(r["pass"] for r in rows if r["category"] == c) / sum(r["category"] == c for r in rows), 3) for c in sorted({r["category"] for r in rows})},
        "n_questions": len(Q), "answerable": n_ans, "unanswerable": n_ref,
        "retrieval_hit_rate": round(hits / n_ans, 3), "retrieval_mrr": round(rr / n_ans, 3),
        "answer_accuracy": round(correct / n_ans, 3), "grounded_rate": round(grounded / n_ans, 3),
        "refusal_accuracy": round(refusal_ok / n_ref, 3),
        "mode": "offline-deterministic (no LLM); embeddings=hashing",
    }
    return {"summary": summary, "results": rows}


if __name__ == "__main__":
    out = run()
    Path(__file__).with_name("last_results.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out["summary"], indent=1))
    for r in out["results"]:
        if not r["pass"]:
            print("FAIL:", r["question"], "->", r["answer"][:140])
