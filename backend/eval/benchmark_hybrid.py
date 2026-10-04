import json

from app.config import Settings
from app.core.router import route_query
from app.embeddings import make_embedder
from app.retrieval import HybridRetriever
from app.store import KnowledgeBase


DEPARTMENTS = {
    "finance",
    "hr",
    "manufacturing",
    "customer_support",
}


def main():
    settings = Settings()
    embedder = make_embedder(settings)

    kb = KnowledgeBase(
        settings,
        embedder,
        DEPARTMENTS,
    )

    retriever = HybridRetriever(
        kb,
        settings.min_relevance,
        settings.min_coverage,
    )

    questions = json.loads(
        open("eval/questions.json", encoding="utf-8").read()
    )

    hits = 0
    mrr = 0.0
    no_evidence = 0

    for item in questions:
        query = item["question"]
        expected = item["doc"]

        plan = route_query(query)

        results = retriever.retrieve(
            query,
            plan,
            allowed=DEPARTMENTS,
        )

        docs = [
            result.chunk.document_name
            for result in results
        ]

        if not docs:
            no_evidence += 1
            continue

        if expected in docs:
            hits += 1
            mrr += 1 / (docs.index(expected) + 1)

    n = len(questions)

    print("=" * 60)
    print("CHANAKYA PRODUCTION HYBRID RETRIEVER")
    print("=" * 60)
    print(f"Questions:   {n}")
    print(f"Hit Rate:    {hits / n:.4f}")
    print(f"MRR:         {mrr / n:.4f}")
    print(f"No evidence: {no_evidence}")
    print("=" * 60)


if __name__ == "__main__":
    main()
