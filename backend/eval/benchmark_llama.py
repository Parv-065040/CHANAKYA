import json
from pathlib import Path

from app.config import Settings
from app.embeddings import make_embedder
from app.store import KnowledgeBase
from app.llamaindex_adapter import chunks_to_nodes
from app.llamaindex_index import CHANAKYALlamaIndex


QUESTIONS = Path("eval/questions.json")


def main():
    settings = Settings()
    embedder = make_embedder(settings)

    kb = KnowledgeBase(
        settings,
        embedder,
        {"finance", "hr", "manufacturing", "customer_support"},
    )

    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))

    nodes = chunks_to_nodes(list(kb.chunks.values()))
    llama = CHANAKYALlamaIndex(nodes, embedder)

    llama_hits = 0
    llama_mrr = 0.0

    chan_hits = 0
    chan_mrr = 0.0

    for item in questions:
        q = item["question"]
        expected = item["doc"]

        # LlamaIndex
        results = llama.query(q, top_k=10)
        docs = [
            r.node.metadata.get("document_name")
            for r in results
        ]

        if expected in docs:
            llama_hits += 1
            llama_mrr += 1 / (docs.index(expected) + 1)

        # Existing CHANAKYA vector search
        results = kb.vector_search(
            q,
            10,
            {"finance", "hr", "manufacturing", "customer_support"},
        )

        docs = [
            kb.chunks[cid].document_name
            for cid, _ in results
        ]

        if expected in docs:
            chan_hits += 1
            chan_mrr += 1 / (docs.index(expected) + 1)

    n = len(questions)

    print("=" * 60)
    print("CHANAKYA VECTOR vs LLAMAINDEX VECTOR")
    print("=" * 60)
    print(f"Questions: {n}")
    print()
    print("Existing CHANAKYA vector:")
    print(f"  Hit Rate: {chan_hits / n:.4f}")
    print(f"  MRR:      {chan_mrr / n:.4f}")
    print()
    print("LlamaIndex vector:")
    print(f"  Hit Rate: {llama_hits / n:.4f}")
    print(f"  MRR:      {llama_mrr / n:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
