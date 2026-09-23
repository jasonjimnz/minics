"""ChromaDB-backed vector store.

MiniCS embeds text itself (through the configured OpenAI-compatible endpoint)
and hands the vectors to Chroma.  Doing the embedding outside Chroma means the
embedding model, dimension and batching are all under our control and visible to
the user in Settings.

A single physical directory (``~/.minics/vectordb``) hosts one collection per
logical scope; by default everything lands in the ``minics`` collection.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DEFAULT_COLLECTION = "minics"


class VectorStoreError(RuntimeError):
    """Raised for vector store failures."""


def _sanitize(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Chroma only accepts scalar metadata values."""
    clean: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            clean[key] = value
        elif isinstance(value, (list, tuple, set)):
            clean[key] = ", ".join(str(v) for v in value)
        else:
            clean[key] = str(value)
    return clean


class VectorStore:
    """A thin, thread-safe wrapper around a persistent Chroma collection."""

    def __init__(
        self,
        path: str | Path,
        *,
        collection: str = DEFAULT_COLLECTION,
        dimension: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.collection_name = collection
        self.dimension = dimension
        self._client: Any = None
        self._collection: Any = None
        self._lock = threading.RLock()

    # -- lifecycle -------------------------------------------------------
    @property
    def client(self) -> Any:
        with self._lock:
            if self._client is None:
                import chromadb
                from chromadb.config import Settings

                self.path.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(
                    path=str(self.path),
                    settings=Settings(anonymized_telemetry=False, allow_reset=True),
                )
            return self._client

    @property
    def collection(self) -> Any:
        with self._lock:
            if self._collection is None:
                metadata: dict[str, Any] = {"hnsw:space": "cosine"}
                if self.dimension:
                    metadata["dimension"] = int(self.dimension)
                self._collection = self.client.get_or_create_collection(
                    name=self.collection_name, metadata=metadata
                )
            return self._collection

    def close(self) -> None:
        with self._lock:
            client, self._client = self._client, None
            self._collection = None
        if client is not None:
            stop = getattr(getattr(client, "_system", None), "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:  # noqa: BLE001 - best effort
                    pass

    # -- introspection ---------------------------------------------------
    def count(self) -> int:
        return int(self.collection.count())

    def exists(self, ids: Sequence[str]) -> list[str]:
        if not ids:
            return []
        found = self.collection.get(ids=list(ids))
        return list(found.get("ids") or [])

    def get(self, ids: Sequence[str]) -> dict[str, Any]:
        if not ids:
            return {"ids": [], "documents": [], "metadatas": []}
        return dict(self.collection.get(ids=list(ids)))

    # -- writes ----------------------------------------------------------
    def upsert(
        self,
        ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        documents: Sequence[str] | None = None,
        metadatas: Sequence[dict[str, Any]] | None = None,
    ) -> int:
        if not ids:
            return 0
        if len(ids) != len(embeddings):
            raise VectorStoreError("ids and embeddings must have the same length.")
        payload: dict[str, Any] = {
            "ids": list(ids),
            "embeddings": [list(vector) for vector in embeddings],
        }
        if documents is not None:
            payload["documents"] = list(documents)
        if metadatas is not None:
            payload["metadatas"] = [_sanitize(m) for m in metadatas]
        with self._lock:
            self.collection.upsert(**payload)
        return len(ids)

    def delete(self, ids: Sequence[str] | None = None, where: dict[str, Any] | None = None) -> None:
        if not ids and not where:
            return
        with self._lock:
            self.collection.delete(ids=list(ids) if ids else None, where=where)

    def delete_document(self, document_id: int) -> None:
        self.delete(where={"document_id": int(document_id)})

    def reset(self) -> None:
        """Delete and recreate the collection."""
        with self._lock:
            try:
                self.client.delete_collection(self.collection_name)
            except Exception:  # noqa: BLE001 - may not exist
                pass
            self._collection = None

    # -- reads -----------------------------------------------------------
    def query(
        self,
        embedding: Sequence[float],
        *,
        n_results: int = 8,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self.count() == 0:
            return []
        with self._lock:
            result = self.collection.query(
                query_embeddings=[list(embedding)],
                n_results=max(1, n_results),
                where=where or None,
                include=["documents", "metadatas", "distances"],
            )
        hits: list[dict[str, Any]] = []
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        for index, vector_id in enumerate(ids):
            distance = float(distances[index]) if index < len(distances) else 0.0
            hits.append(
                {
                    "id": vector_id,
                    "document": documents[index] if index < len(documents) else "",
                    "metadata": metadatas[index] if index < len(metadatas) else {},
                    "distance": distance,
                    "score": max(0.0, 1.0 - distance),
                }
            )
        return hits
