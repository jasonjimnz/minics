"""Ladybug graph store + document topology indexing.

The graph is not trying to be a full knowledge base.  Its job is to give
retrieval a *structural* signal: which entities a chunk mentions, which chunks
are adjacent, and which entities travel together.  That signal is fused with the
vector signal through RRF.

Topology:

    (Document)-[:HAS_CHUNK]->(Chunk)-[:NEXT]->(Chunk)
    (Chunk)-[:MENTIONS]->(Entity)
    (Entity)-[:CO_OCCURS]->(Entity)
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from minics.rag.chunking import split_markdown
from minics.rag.entities import Entity, extract_cooccurrence, extract_entities
from minics.rag.indexer import vector_id_for
from minics.services.base import NotFoundError, Service
from minics.services.repositories import DocumentRepository

Progress = Callable[[float, str], None]

SCHEMA: tuple[str, ...] = (
    "CREATE NODE TABLE IF NOT EXISTS Document("
    "id INT64, public_id STRING, title STRING, kind STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Chunk("
    "id STRING, document_id INT64, idx INT64, heading STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Entity("
    "name STRING, kind STRING, mentions INT64, PRIMARY KEY(name))",
    "CREATE REL TABLE IF NOT EXISTS HAS_CHUNK(FROM Document TO Chunk, position INT64)",
    "CREATE REL TABLE IF NOT EXISTS NEXT(FROM Chunk TO Chunk)",
    "CREATE REL TABLE IF NOT EXISTS MENTIONS(FROM Chunk TO Entity, weight DOUBLE)",
    "CREATE REL TABLE IF NOT EXISTS CO_OCCURS(FROM Entity TO Entity, weight DOUBLE)",
)


class GraphStoreError(RuntimeError):
    """Raised when the Ladybug graph cannot be opened or queried."""


class GraphStore:
    """Thread-safe wrapper around a Ladybug database."""

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path is not None else None
        self._db: Any = None
        self._conn: Any = None
        self._lock = threading.RLock()
        self._ready = False

    # -- lifecycle -------------------------------------------------------
    def _connect(self) -> Any:
        if self._conn is None:
            if self.path is None:
                raise GraphStoreError("No graph path configured.")
            import ladybug

            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = ladybug.Database(str(self.path))
            self._conn = ladybug.Connection(self._db)
            for statement in SCHEMA:
                self._conn.execute(statement)
            self._ready = True
        return self._conn

    def close(self) -> None:
        with self._lock:
            conn, self._conn = self._conn, None
            db, self._db = self._db, None
            self._ready = False
        try:
            if conn is not None:
                conn.close()
            if db is not None:
                db.close()
        except Exception:  # noqa: BLE001 - best effort
            pass

    def is_available(self) -> bool:
        try:
            self._connect()
            return True
        except Exception:  # noqa: BLE001
            return False

    # -- low level -------------------------------------------------------
    @staticmethod
    def _unwrap(result: Any) -> Any:
        if isinstance(result, list):
            return result[-1] if result else None
        return result

    def execute(self, query: str, params: dict[str, Any] | None = None) -> Any:
        with self._lock:
            conn = self._connect()
            return self._unwrap(conn.execute(query, dict(params or {})))

    def rows(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = self.execute(query, params)
        if result is None:
            return []
        names = list(result.get_column_names())
        output: list[dict[str, Any]] = []
        while result.has_next():
            output.append(dict(zip(names, result.get_next(), strict=True)))
        return output

    def clear(self) -> None:
        with self._lock:
            self._connect()
            for table in ("CO_OCCURS", "MENTIONS", "NEXT", "HAS_CHUNK"):
                try:
                    self._conn.execute(f"MATCH ()-[r:{table}]->() DELETE r")
                except Exception:  # noqa: BLE001 - may be empty
                    pass
            for table in ("Chunk", "Document", "Entity"):
                try:
                    self._conn.execute(f"MATCH (n:{table}) DETACH DELETE n")
                except Exception:  # noqa: BLE001 - may be empty
                    pass

    # -- writes ----------------------------------------------------------
    def upsert_document(self, document_id: int, public_id: str, title: str, kind: str) -> None:
        self.execute(
            "MERGE (d:Document {id: $id}) SET d.public_id = $pid, d.title = $title, d.kind = $kind",
            {"id": int(document_id), "pid": public_id, "title": title, "kind": kind},
        )

    def delete_document(self, document_id: int) -> None:
        self.execute("MATCH (d:Document {id: $id}) DETACH DELETE d", {"id": int(document_id)})
        self.execute(
            "MATCH (c:Chunk) WHERE c.document_id = $id DETACH DELETE c", {"id": int(document_id)}
        )

    def clear_document_chunks(self, document_id: int) -> None:
        self.execute(
            "MATCH (c:Chunk) WHERE c.document_id = $id DETACH DELETE c", {"id": int(document_id)}
        )

    def add_chunk(
        self, chunk_id: str, document_id: int, index: int, heading: str, position: int
    ) -> None:
        self.execute(
            "MERGE (c:Chunk {id: $cid}) SET c.document_id = $did, c.idx = $idx, c.heading = $h",
            {"cid": chunk_id, "did": int(document_id), "idx": int(index), "h": heading},
        )
        self.execute(
            "MATCH (d:Document {id: $did}), (c:Chunk {id: $cid}) "
            "MERGE (d)-[r:HAS_CHUNK]->(c) SET r.position = $pos",
            {"did": int(document_id), "cid": chunk_id, "pos": int(position)},
        )

    def link_next(self, previous_id: str, next_id: str) -> None:
        self.execute(
            "MATCH (a:Chunk {id: $a}), (b:Chunk {id: $b}) MERGE (a)-[:NEXT]->(b)",
            {"a": previous_id, "b": next_id},
        )

    def add_mention(self, chunk_id: str, entity: Entity) -> None:
        self.execute(
            "MERGE (e:Entity {name: $name}) "
            "SET e.kind = coalesce(e.kind, $kind), e.mentions = coalesce(e.mentions, 0) + 1",
            {"name": entity.name, "kind": entity.kind},
        )
        self.execute(
            "MATCH (c:Chunk {id: $cid}), (e:Entity {name: $name}) "
            "MERGE (c)-[r:MENTIONS]->(e) SET r.weight = coalesce(r.weight, 0.0) + $w",
            {"cid": chunk_id, "name": entity.name, "w": float(entity.weight)},
        )

    def add_cooccurrence(self, left: str, right: str, weight: float = 1.0) -> None:
        self.execute(
            "MATCH (a:Entity {name: $a}), (b:Entity {name: $b}) "
            "MERGE (a)-[r:CO_OCCURS]->(b) SET r.weight = coalesce(r.weight, 0.0) + $w",
            {"a": left, "b": right, "w": float(weight)},
        )

    # -- reads -----------------------------------------------------------
    def find_entities(self, terms: Sequence[str], *, limit: int = 24) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for term in terms:
            term = (term or "").strip()
            if len(term) < 2:
                continue
            rows = self.rows(
                "MATCH (e:Entity) WHERE toLower(e.name) CONTAINS toLower($t) "
                "RETURN e.name, e.kind, e.mentions LIMIT $lim",
                {"t": term, "lim": limit},
            )
            for row in rows:
                name = row["e.name"]
                existing = found.get(name)
                if existing is None or row["e.mentions"] > existing["mentions"]:
                    found[name] = {
                        "name": name,
                        "kind": row["e.kind"],
                        "mentions": row["e.mentions"],
                    }
        return sorted(found.values(), key=lambda r: -r["mentions"])[:limit]

    def chunks_for_entities(
        self, names: Sequence[str], *, limit: int = 32
    ) -> list[dict[str, Any]]:
        if not names:
            return []
        rows = self.rows(
            "MATCH (c:Chunk)-[m:MENTIONS]->(e:Entity) WHERE e.name IN $names "
            "RETURN c.id, c.document_id, c.idx, c.heading, m.weight, e.name",
            {"names": list(names)},
        )
        scores: dict[str, dict[str, Any]] = {}
        for row in rows:
            chunk_id = row["c.id"]
            entry = scores.setdefault(
                chunk_id,
                {
                    "chunk_id": chunk_id,
                    "document_id": row["c.document_id"],
                    "index": row["c.idx"],
                    "heading": row["c.heading"],
                    "score": 0.0,
                    "entities": [],
                },
            )
            entry["score"] += float(row["m.weight"] or 0.0)
            entry["entities"].append(row.get("e.name"))
        return sorted(scores.values(), key=lambda r: -r["score"])[:limit]

    def neighbors(self, name: str, *, hops: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        hops = max(1, min(3, int(hops)))
        rows = self.rows(
            f"MATCH (a:Entity {{name: $name}})-[:CO_OCCURS*1..{hops}]-(b:Entity) "
            "RETURN DISTINCT b.name, b.kind, b.mentions LIMIT $lim",
            {"name": name, "lim": limit},
        )
        return [
            {"name": row["b.name"], "kind": row["b.kind"], "mentions": row["b.mentions"]}
            for row in rows
        ]

    def expand_chunks(self, chunk_ids: Sequence[str], *, limit: int = 16) -> list[dict[str, Any]]:
        """Follow the chunk topology one step (previous/next neighbours)."""
        if not chunk_ids:
            return []
        rows = self.rows(
            "MATCH (a:Chunk)-[:NEXT]-(b:Chunk) WHERE a.id IN $ids "
            "RETURN DISTINCT b.id, b.document_id, b.idx, b.heading LIMIT $lim",
            {"ids": list(chunk_ids), "lim": limit},
        )
        return [
            {
                "chunk_id": row["b.id"],
                "document_id": row["b.document_id"],
                "index": row["b.idx"],
                "heading": row["b.heading"],
                "score": 0.1,
                "entities": [],
            }
            for row in rows
        ]

    def subgraph(self, terms: Sequence[str], *, limit: int = 40) -> dict[str, Any]:
        """Return a small nodes/edges view around entities matching ``terms``."""
        entities = self.find_entities(terms, limit=limit)
        names = [e["name"] for e in entities]
        nodes = [
            {"id": e["name"], "label": e["name"], "kind": e["kind"], "weight": e["mentions"]}
            for e in entities
        ]
        edges: list[dict[str, Any]] = []
        if names:
            rows = self.rows(
                "MATCH (a:Entity)-[r:CO_OCCURS]->(b:Entity) "
                "WHERE a.name IN $names AND b.name IN $names "
                "RETURN a.name, b.name, r.weight",
                {"names": names},
            )
            for row in rows:
                edges.append(
                    {"source": row["a.name"], "target": row["b.name"], "weight": row["r.weight"]}
                )
        return {"nodes": nodes, "edges": edges, "entities": names}

    def stats(self) -> dict[str, int]:
        def _count(label: str) -> int:
            rows = self.rows(f"MATCH (n:{label}) RETURN count(*) AS c")
            return int(rows[0]["c"]) if rows else 0

        def _rel_count(table: str) -> int:
            rows = self.rows(f"MATCH ()-[r:{table}]->() RETURN count(*) AS c")
            return int(rows[0]["c"]) if rows else 0

        try:
            return {
                "documents": _count("Document"),
                "chunks": _count("Chunk"),
                "entities": _count("Entity"),
                "mentions": _rel_count("MENTIONS"),
                "cooccurrences": _rel_count("CO_OCCURS"),
            }
        except Exception:  # noqa: BLE001
            return {}


class GraphIndexer(Service):
    """Builds and queries the document topology graph."""

    name = "graph"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.documents = DocumentRepository(ctx.db)
        self.store = ctx.graph

    # -- indexing --------------------------------------------------------
    def index_document(
        self,
        ref: int | str,
        *,
        progress: Progress | None = None,
        job_ctx=None,
        max_entities: int = 12,
    ) -> dict:
        document = self._document(ref)
        markdown = self._markdown(document)
        if not markdown.strip():
            raise ValueError(f"Document '{document.title}' has no text to index.")

        settings = self.ctx.config.embedding
        chunks = split_markdown(
            markdown, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
        )
        self.store.upsert_document(
            int(document.id), document.public_id, document.title, document.kind
        )
        self.store.clear_document_chunks(int(document.id))

        previous_id: str | None = None
        total = max(1, len(chunks))
        entity_count = 0
        for chunk in chunks:
            if job_ctx is not None:
                job_ctx.check_cancelled()
            chunk_id = vector_id_for(int(document.id), chunk.index)
            self.store.add_chunk(
                chunk_id, int(document.id), chunk.index, chunk.heading, chunk.index
            )
            if previous_id is not None:
                self.store.link_next(previous_id, chunk_id)
            previous_id = chunk_id

            entities = extract_entities(chunk.text, max_entities=max_entities)
            for entity in entities:
                self.store.add_mention(chunk_id, entity)
            for left, right, weight in extract_cooccurrence(entities):
                self.store.add_cooccurrence(left, right, weight)
            entity_count += len(entities)
            _report(
                progress,
                0.1 + 0.9 * ((chunk.index + 1) / total),
                f"Graph {chunk.index + 1}/{total}",
            )

        self.ctx.bus.publish(
            type="graph.indexed",
            level="success",
            source=self.name,
            message=f"Graph updated for '{document.title}' ({entity_count} entity mentions)",
            data={"document": document.public_id, "entities": entity_count},
        )
        return {"document_id": int(document.id), "chunks": len(chunks), "entities": entity_count}

    def remove_document(self, ref: int | str) -> None:
        document = self._document(ref)
        self.store.delete_document(int(document.id))

    def reindex_all(self, *, progress: Progress | None = None) -> dict:
        documents = self.documents.list()
        for position, document in enumerate(documents, start=1):
            _report(progress, (position - 1) / max(1, len(documents)), f"Graph: {document.title}")
            try:
                self.index_document(int(document.id))
            except Exception as exc:  # noqa: BLE001 - keep going
                self.ctx.bus.publish(
                    type="graph.index_failed",
                    level="warning",
                    source=self.name,
                    message=f"Graph indexing failed for '{document.title}': {exc}",
                )
        _report(progress, 1.0, "Graph done")
        return {"documents": len(documents)}

    # -- retrieval -------------------------------------------------------
    def search(
        self, query: str, *, limit: int = 24, hops: int | None = None
    ) -> list[dict[str, Any]]:
        """Rank chunks by how strongly they connect to the query's entities."""
        terms = _query_terms(query)
        if not terms:
            return []
        entities = self.store.find_entities(terms, limit=limit)
        if not entities:
            return []
        names = [e["name"] for e in entities]
        if hops is None:
            hops = self.ctx.config.retrieval.graph_hops
        if hops > 1:
            expanded: set[str] = set(names)
            for name in names[:8]:
                for neighbour in self.store.neighbors(name, hops=hops - 1, limit=8):
                    expanded.add(neighbour["name"])
            names = list(expanded)
        hits = self.store.chunks_for_entities(names, limit=limit)
        if len(hits) < limit:
            expansion = self.store.expand_chunks(
                [h["chunk_id"] for h in hits], limit=limit * 2
            )
            merged: dict[str, dict[str, Any]] = {h["chunk_id"]: h for h in hits}
            for hit in expansion:
                existing = merged.get(hit["chunk_id"])
                if existing is None:
                    merged[hit["chunk_id"]] = hit
                else:
                    existing["score"] = existing["score"] + hit["score"]
            hits = sorted(merged.values(), key=lambda r: -r["score"])[:limit]
        for hit in hits:
            hit.setdefault("source", "graph")
        return hits

    # -- internals -------------------------------------------------------
    def _document(self, ref: int | str):
        document_id = Service.resolve_id(self.documents, ref)
        document = self.documents.get(document_id)
        if document is None:
            raise NotFoundError(f"Document '{ref}' not found")
        return document

    def _markdown(self, document) -> str:
        path = Path(document.markdown_path)
        return path.read_text(encoding="utf-8") if path.exists() else ""


def _query_terms(query: str, *, limit: int = 12) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", query or "")
    seen: list[str] = []
    for word in words:
        if word.lower() not in {w.lower() for w in seen}:
            seen.append(word)
    seen.sort(key=len, reverse=True)
    return seen[:limit]


def _report(progress: Progress | None, value: float, message: str) -> None:
    if progress is not None:
        progress(value, message)
