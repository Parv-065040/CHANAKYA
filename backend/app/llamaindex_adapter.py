from __future__ import annotations

from typing import Iterable

from llama_index.core.schema import Document, TextNode


def chunk_to_llama_document(chunk) -> Document:
    """Convert a CHANAKYA Chunk into a LlamaIndex Document."""
    metadata = {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "document_name": chunk.document_name,
        "department": chunk.department,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "section": chunk.section,
        "content_type": chunk.content_type,
    }

    if getattr(chunk, "table_id", None):
        metadata["table_id"] = chunk.table_id

    if getattr(chunk, "table_rows", None) is not None:
        metadata["table_rows"] = chunk.table_rows

    return Document(
        text=chunk.text,
        metadata=metadata,
        doc_id=chunk.document_id,
    )


def chunk_to_text_node(chunk) -> TextNode:
    """Convert a CHANAKYA Chunk into a metadata-rich LlamaIndex TextNode."""
    metadata = {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "document_name": chunk.document_name,
        "department": chunk.department,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "section": chunk.section,
        "content_type": chunk.content_type,
    }

    if getattr(chunk, "table_id", None):
        metadata["table_id"] = chunk.table_id

    if getattr(chunk, "table_rows", None) is not None:
        metadata["table_rows"] = chunk.table_rows

    return TextNode(
        text=chunk.text,
        metadata=metadata,
        id_=chunk.chunk_id,
    )


def chunks_to_nodes(chunks: Iterable) -> list[TextNode]:
    """Convert multiple CHANAKYA chunks to LlamaIndex nodes."""
    return [chunk_to_text_node(chunk) for chunk in chunks]