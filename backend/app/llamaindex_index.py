from __future__ import annotations

from typing import Iterable

import numpy as np

from llama_index.core import VectorStoreIndex
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import TextNode


class CHANAKYAEmbeddingAdapter(BaseEmbedding):
    """Expose the existing CHANAKYA embedder to LlamaIndex."""

    model_name: str = "chanakya-embedding"

    def __init__(self, embedder, **kwargs):
        super().__init__(**kwargs)
        self._chanakya_embedder = embedder

    @classmethod
    def class_name(cls) -> str:
        return "CHANAKYAEmbeddingAdapter"

    def _get_query_embedding(self, query: str) -> list[float]:
        vector = self._chanakya_embedder.embed([query])[0]
        return np.asarray(vector, dtype=np.float32).tolist()

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        vector = self._chanakya_embedder.embed([text])[0]
        return np.asarray(vector, dtype=np.float32).tolist()

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        vectors = self._chanakya_embedder.embed(texts)
        return np.asarray(vectors, dtype=np.float32).tolist()


class CHANAKYALlamaIndex:
    """Isolated LlamaIndex index using CHANAKYA's embedding layer."""

    def __init__(self, nodes: Iterable[TextNode], embedder):
        self.nodes = list(nodes)

        self.embed_model = CHANAKYAEmbeddingAdapter(
            embedder=embedder
        )

        self.index = VectorStoreIndex(
            self.nodes,
            embed_model=self.embed_model,
        )

    def query(self, query: str, top_k: int = 5):
        retriever = self.index.as_retriever(
            similarity_top_k=top_k
        )
        return retriever.retrieve(query)