"""Retrieval stack: vector store, graph store, chunking and fusion."""

from __future__ import annotations

from minics.rag.chunking import Chunk, estimate_tokens, split_markdown, split_text
from minics.rag.fusion import fuse_hit_lists, normalise, reciprocal_rank_fusion
from minics.rag.retriever import (
    HybridRetriever,
    RetrievalResult,
    RetrievedChunk,
    build_grounding_block,
)
from minics.rag.vectorstore import DEFAULT_COLLECTION, VectorStore, VectorStoreError

__all__ = [
    "DEFAULT_COLLECTION",
    "Chunk",
    "HybridRetriever",
    "RetrievalResult",
    "RetrievedChunk",
    "VectorStore",
    "VectorStoreError",
    "build_grounding_block",
    "estimate_tokens",
    "fuse_hit_lists",
    "normalise",
    "reciprocal_rank_fusion",
    "split_markdown",
    "split_text",
]
