"""Document indexing: markdown → chunks → embeddings → Chroma + SQLite.

The SQLite ``document_chunks`` table keeps the canonical chunk text (needed for
RRF ordering, for the graph extractor and for showing sources), while Chroma
holds the vectors.  Both are written together so they can never drift far apart:
re-indexing always clears the previous chunks for a document first.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from minics.core.utils import utcnow_iso
from minics.domain.entities import DocumentChunk, DocumentStatus
from minics.llm.client import embed_texts
from minics.rag.chunking import Chunk, split_markdown
from minics.services.base import NotFoundError, Service
from minics.services.repositories import DocumentChunkRepository, DocumentRepository

Progress = Callable[[float, str], None]


def _noop(progress: Progress | None, value: float, message: str) -> None:
    if progress is not None:
        progress(value, message)


def vector_id_for(document_id: int, index: int) -> str:
    return f"doc-{document_id}-chunk-{index}"


class DocumentIndexer(Service):
    """Turns documents into retrievable chunks."""

    name = "indexer"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.documents = DocumentRepository(ctx.db)
        self.chunks = DocumentChunkRepository(ctx.db)
        self.store = ctx.vectorstore

    # -- indexing --------------------------------------------------------
    def index_document(
        self,
        ref: int | str,
        *,
        progress: Progress | None = None,
        job_ctx=None,
    ) -> dict:
        document = self._document(ref)
        markdown = self._markdown(document)
        if not markdown.strip():
            self.documents.set_status(
                int(document.id), DocumentStatus.ERROR.value, error="Document has no text"
            )
            raise ValueError(f"Document '{document.title}' has no text to index.")

        settings = self.ctx.config.embedding
        _noop(progress, 0.05, "Splitting markdown")
        chunks: list[Chunk] = split_markdown(
            markdown, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
        )
        if not chunks:
            self.documents.set_status(
                int(document.id), DocumentStatus.ERROR.value, error="No chunks produced"
            )
            raise ValueError(f"Document '{document.title}' produced no chunks.")

        _noop(progress, 0.1, f"Embedding {len(chunks)} chunks")
        vectors = self._embed(chunks, progress=progress, job_ctx=job_ctx)

        _noop(progress, 0.85, "Writing index")
        ids = [vector_id_for(int(document.id), chunk.index) for chunk in chunks]
        metadatas = [
            {
                "document_id": int(document.id),
                "document_public_id": document.public_id,
                "title": document.title,
                "chunk_index": chunk.index,
                "heading": chunk.heading,
                "kind": document.kind,
                "tags": ", ".join(document.tags),
            }
            for chunk in chunks
        ]

        self.store.delete_document(int(document.id))
        self.store.upsert(
            ids=ids,
            embeddings=vectors,
            documents=[chunk.text for chunk in chunks],
            metadatas=metadatas,
        )

        self._persist_chunks(document, chunks, ids)
        self.documents.set_status(
            int(document.id), DocumentStatus.READY.value, error="", chunk_count=len(chunks)
        )
        self.ctx.bus.publish(
            type="document.indexed",
            level="success",
            source=self.name,
            message=f"Indexed '{document.title}' ({len(chunks)} chunks)",
            data={"document": document.public_id, "chunks": len(chunks)},
        )
        _noop(progress, 1.0, "Indexed")
        return {"document_id": int(document.id), "chunks": len(chunks)}

    def remove_document(self, ref: int | str) -> None:
        document = self._document(ref)
        self.store.delete_document(int(document.id))
        self.chunks.clear_for_document(int(document.id))
        self.documents.set_status(int(document.id), DocumentStatus.READY.value, chunk_count=0)

    def reindex_all(self, *, progress: Progress | None = None) -> dict:
        documents = self.documents.list()
        indexed = 0
        for position, document in enumerate(documents, start=1):
            _noop(progress, (position - 1) / max(1, len(documents)), f"Indexing {document.title}")
            try:
                self.index_document(int(document.id))
                indexed += 1
            except Exception as exc:  # noqa: BLE001 - report and continue
                self.ctx.bus.publish(
                    type="document.index_failed",
                    level="warning",
                    source=self.name,
                    message=f"Could not index '{document.title}': {exc}",
                )
        _noop(progress, 1.0, "Done")
        return {"documents": len(documents), "indexed": indexed}

    # -- internals -------------------------------------------------------
    def _embed(
        self,
        chunks: list[Chunk],
        *,
        progress: Progress | None,
        job_ctx=None,
    ) -> list[list[float]]:
        settings = self.ctx.config.embedding
        batch_size = max(1, settings.batch_size)
        vectors: list[list[float]] = []
        total = len(chunks)
        for start in range(0, total, batch_size):
            if job_ctx is not None:
                job_ctx.check_cancelled()
            batch = chunks[start : start + batch_size]
            vectors.extend(embed_texts([chunk.text for chunk in batch], self.ctx.config))
            done = min(total, start + len(batch))
            # Embedding occupies 10% → 85% of the progress bar.
            fraction = 0.1 + 0.75 * (done / total)
            _noop(progress, fraction, f"Embedded {done}/{total} chunks")

        if vectors and settings.dimension:
            actual = len(vectors[0])
            if actual != settings.dimension:
                self.ctx.bus.publish(
                    type="embedding.dimension_mismatch",
                    level="warning",
                    source=self.name,
                    message=(
                        f"Embedding size is {actual} but settings say {settings.dimension}. "
                        "Update the embedding dimension in Settings."
                    ),
                    data={"expected": settings.dimension, "actual": actual},
                )
        return vectors

    def _persist_chunks(self, document, chunks: list[Chunk], ids: list[str]) -> None:
        self.chunks.clear_for_document(int(document.id))
        entities = [
            DocumentChunk(
                document_id=int(document.id),
                index=chunk.index,
                text=chunk.text,
                tokens=chunk.tokens,
                heading=chunk.heading,
                vector_id=ids[chunk.index],
                metadata=chunk.metadata,
                created_at=utcnow_iso(),
                updated_at=utcnow_iso(),
            )
            for chunk in chunks
        ]

        def _write(conn):
            for entity in entities:
                row = self.chunks.to_row(entity)
                columns = list(row)
                placeholders = ", ".join("?" for _ in columns)
                conn.execute(
                    f"INSERT INTO document_chunks ({', '.join(columns)}) "
                    f"VALUES ({placeholders})",
                    tuple(row[column] for column in columns),
                )

        self.db.transaction(_write)

    def _document(self, ref: int | str):
        document_id = Service.resolve_id(self.documents, ref)
        document = self.documents.get(document_id)
        if document is None:
            raise NotFoundError(f"Document '{ref}' not found")
        return document

    def _markdown(self, document) -> str:
        path = Path(document.markdown_path)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
