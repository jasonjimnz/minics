"""Hybrid retrieval: dense vectors + graph topology, fused with RRF.

    query ──┬────────────────► Chroma  (semantic)   ──┐
            │                                          ├─► RRF ─► chunks ─► grounding
            └────────────────► Ladybug (topology)     ──┘

Everything degrades gracefully: if the graph is unavailable the vector side
still answers, and vice-versa.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from minics.domain.entities import Citation
from minics.llm.client import LLMError, embed_texts
from minics.rag.fusion import fuse_hit_lists
from minics.services.base import Service
from minics.services.repositories import DocumentChunkRepository, DocumentRepository


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: int
    document_title: str = ""
    index: int = 0
    heading: str = ""
    text: str = ""
    vector_score: float = 0.0
    graph_score: float = 0.0
    fused_score: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "index": self.index,
            "heading": self.heading,
            "text": self.text,
            "vector_score": round(self.vector_score, 4),
            "graph_score": round(self.graph_score, 4),
            "fused_score": round(self.fused_score, 6),
            "ranks": self.ranks,
            "sources": self.sources,
            "entities": self.entities,
        }

    def citation(self) -> Citation:
        return Citation(
            kind="vector" if "vector" in self.sources else "graph",
            ref=self.chunk_id,
            title=self.document_title,
            snippet=self.text[:280],
            score=self.fused_score,
            document_id=self.document_id,
            metadata={"heading": self.heading, "index": self.index},
        )


@dataclass
class RetrievalResult:
    query: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    used_rag: bool = False
    used_graph: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "used_rag": self.used_rag,
            "used_graph": self.used_graph,
            "diagnostics": self.diagnostics,
            "citations": [c.model_dump() for c in self.citations()],
        }

    def citations(self) -> list[Citation]:
        return [chunk.citation() for chunk in self.chunks]

    def context_text(self, *, max_chars: int = 8000, max_chunks: int | None = None) -> str:
        """Render chunks into a citation-friendly grounding block."""
        limit = max_chunks or len(self.chunks)
        blocks: list[str] = []
        used = 0
        for position, chunk in enumerate(self.chunks[:limit], start=1):
            label = chunk.heading or f"chunk {chunk.index}"
            body = chunk.text.strip()
            block = f"[{position}] {chunk.document_title} — {label}\n{body}"
            if used + len(block) > max_chars:
                break
            blocks.append(block)
            used += len(block)
        return "\n\n".join(blocks)


class HybridRetriever(Service):
    """Dense + graph retrieval fused with RRF."""

    name = "retrieval"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.chunks = DocumentChunkRepository(ctx.db)
        self.documents = DocumentRepository(ctx.db)

    # -- public API ------------------------------------------------------
    def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        use_rag: bool | None = None,
        use_graph: bool | None = None,
        document_ids: Sequence[int] | None = None,
        candidates: int | None = None,
    ) -> RetrievalResult:
        settings = self.config.retrieval
        use_rag = settings.use_rag if use_rag is None else use_rag
        use_graph = settings.use_graph if use_graph is None else use_graph
        top_k = top_k or settings.top_k
        candidates = candidates or settings.candidates
        allowed = set(document_ids or []) or None

        result = RetrievalResult(query=query, used_rag=use_rag, used_graph=use_graph)
        rankings: dict[str, list[dict[str, Any]]] = {}

        if use_rag:
            vector_hits = self._vector_search(query, candidates, allowed)
            if vector_hits:
                rankings["vector"] = vector_hits
            result.diagnostics["vector_hits"] = len(vector_hits)

        if use_graph:
            graph_hits = self._graph_search(query, candidates, allowed)
            if graph_hits:
                rankings["graph"] = graph_hits
            result.diagnostics["graph_hits"] = len(graph_hits)

        if not rankings:
            return result

        fused = fuse_hit_lists(
            rankings,
            k=settings.rrf_k,
            weights={"vector": settings.vector_weight, "graph": settings.graph_weight},
        )[:top_k]

        result.chunks = self._enrich(fused)
        result.diagnostics["fused"] = len(result.chunks)
        return result

    def index_summary(self) -> dict[str, int]:
        return {
            "chunks": int(self.db.scalar("SELECT COUNT(*) FROM document_chunks", default=0)),
            "documents": self.documents.count(),
        }

    # -- retrievers ------------------------------------------------------
    def _vector_search(
        self, query: str, limit: int, allowed: set[int] | None
    ) -> list[dict[str, Any]]:
        try:
            vector = embed_texts([query], self.config)[0]
        except LLMError as exc:
            self.emit("retrieval.vector_failed", str(exc), level="warning")
            return []
        where = None
        if allowed:
            where = {"document_id": {"$in": sorted(allowed)}}
        try:
            hits = self.ctx.vectorstore.query(vector, n_results=limit, where=where)
        except Exception as exc:  # noqa: BLE001 - degrade to graph-only
            self.emit("retrieval.vector_failed", str(exc), level="warning")
            return []
        for hit in hits:
            metadata = hit.get("metadata") or {}
            hit["document_id"] = int(metadata.get("document_id") or 0)
            hit["heading"] = metadata.get("heading") or ""
            hit["vector_score"] = hit.pop("score", 0.0)
        return hits

    def _graph_search(
        self, query: str, limit: int, allowed: set[int] | None
    ) -> list[dict[str, Any]]:
        try:
            if not self.ctx.graph.is_available():
                return []
            hits = self.ctx.graph_indexer.search(query, limit=limit)
        except Exception as exc:  # noqa: BLE001 - degrade to vector-only
            self.emit("retrieval.graph_failed", str(exc), level="warning")
            return []
        for hit in hits:
            hit["graph_score"] = hit.pop("score", 0.0)
        if allowed:
            hits = [h for h in hits if int(h.get("document_id") or 0) in allowed]
        return hits

    # -- enrichment ------------------------------------------------------
    def _enrich(self, fused: list[dict[str, Any]]) -> list[RetrievedChunk]:
        if not fused:
            return []
        ids = [str(hit.get("chunk_id") or hit.get("id")) for hit in fused]
        rows = {chunk.vector_id: chunk for chunk in self.chunks.by_vector_ids(ids)}
        document_ids = {int(hit.get("document_id") or 0) for hit in fused}
        titles = {
            int(doc.id): doc.title
            for doc in (self.documents.get(doc_id) for doc_id in document_ids if doc_id)
            if doc is not None
        }
        chunks: list[RetrievedChunk] = []
        for hit in fused:
            chunk_id = str(hit.get("chunk_id") or hit.get("id"))
            row = rows.get(chunk_id)
            document_id = int(hit.get("document_id") or (row.document_id if row else 0))
            chunks.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    document_title=titles.get(document_id, ""),
                    index=int(row.index if row else hit.get("index") or 0),
                    heading=str(row.heading if row else hit.get("heading") or ""),
                    text=row.text if row else str(hit.get("document") or ""),
                    vector_score=float(hit.get("vector_score") or 0.0),
                    graph_score=float(hit.get("graph_score") or 0.0),
                    fused_score=float(hit.get("fused_score") or 0.0),
                    ranks=dict(hit.get("ranks") or {}),
                    sources=list(hit.get("sources") or []),
                    entities=[e for e in (hit.get("entities") or []) if e],
                )
            )
        return chunks


def build_grounding_block(
    result: RetrievalResult, *, max_chars: int = 8000
) -> tuple[str, list[Citation]]:
    """Return the grounding text plus the citations it refers to."""
    context = result.context_text(max_chars=max_chars)
    return context, result.citations()
