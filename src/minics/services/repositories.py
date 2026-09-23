"""Concrete repositories for each domain entity."""

from __future__ import annotations

from typing import Any

from minics.core.repository import ModelRepository
from minics.domain.entities import (
    Collection,
    Conversation,
    ConversationMessage,
    Dataset,
    Document,
    DocumentChunk,
    Entry,
)


class DatasetRepository(ModelRepository[Dataset]):
    table = "datasets"
    model = Dataset
    order_by = "updated_at DESC, id DESC"

    def by_slug(self, slug: str) -> Dataset | None:
        row = self.db.query_one("SELECT * FROM datasets WHERE slug = ?", (slug,))
        return self.from_row(row) if row else None


class EntryRepository(ModelRepository[Entry]):
    table = "entries"
    model = Entry
    order_by = "position ASC, id ASC"

    def list_for_dataset(self, dataset_id: int) -> list[Entry]:
        return self.list(where="dataset_id = ?", params=(dataset_id,))

    def count_for_dataset(self, dataset_id: int) -> int:
        return self.count(where="dataset_id = ?", params=(dataset_id,))

    def next_position(self, dataset_id: int | None) -> int:
        if dataset_id is None:
            value = self.db.scalar("SELECT MAX(position) FROM entries", default=0)
        else:
            value = self.db.scalar(
                "SELECT MAX(position) FROM entries WHERE dataset_id = ?",
                (dataset_id,),
                default=0,
            )
        return int(value or 0) + 1

    def by_public_ids(self, public_ids: list[str]) -> list[Entry]:
        if not public_ids:
            return []
        placeholders = ", ".join("?" for _ in public_ids)
        return [
            self.from_row(row)
            for row in self.db.query(
                f"SELECT * FROM entries WHERE public_id IN ({placeholders})",
                tuple(public_ids),
            )
        ]

    # -- versioning ------------------------------------------------------
    def add_version(self, entry: Entry, *, reason: str = "") -> None:
        from minics.core.utils import json_dumps, utcnow_iso

        if entry.id is None:
            return
        self.db.execute(
            "INSERT OR REPLACE INTO entry_versions (entry_id, version, snapshot, reason, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            (
                entry.id,
                entry.version,
                json_dumps(entry.model_dump(mode="json")),
                reason,
                utcnow_iso(),
            ),
        )

    def versions(self, entry_id: int) -> list[dict[str, Any]]:
        from minics.core.utils import json_loads

        rows = self.db.query(
            "SELECT version, snapshot, reason, created_at FROM entry_versions "
            "WHERE entry_id = ? ORDER BY version DESC",
            (entry_id,),
        )
        return [
            {
                "version": row["version"],
                "snapshot": json_loads(row["snapshot"], default={}),
                "reason": row["reason"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


class CollectionRepository(ModelRepository[Collection]):
    table = "collections"
    model = Collection
    exclude = frozenset({"entry_ids"})
    order_by = "updated_at DESC, id DESC"

    def by_slug(self, slug: str) -> Collection | None:
        row = self.db.query_one("SELECT * FROM collections WHERE slug = ?", (slug,))
        return self.from_row(row) if row else None

    # -- membership ------------------------------------------------------
    def add_entries(self, collection_id: int, entry_ids: list[int]) -> int:
        if not entry_ids:
            return 0
        start = int(
            self.db.scalar(
                "SELECT COALESCE(MAX(position), 0) FROM collection_entries "
                "WHERE collection_id = ?",
                (collection_id,),
                default=0,
            )
        )
        rows = [
            (collection_id, entry_id, start + offset)
            for offset, entry_id in enumerate(entry_ids, start=1)
        ]
        return self.db.execute_many(
            "INSERT OR IGNORE INTO collection_entries (collection_id, entry_id, position) "
            "VALUES (?, ?, ?)",
            rows,
        )

    def remove_entries(self, collection_id: int, entry_ids: list[int]) -> int:
        if not entry_ids:
            return 0
        placeholders = ", ".join("?" for _ in entry_ids)
        return self.db.update(
            f"DELETE FROM collection_entries WHERE collection_id = ? "
            f"AND entry_id IN ({placeholders})",
            (collection_id, *entry_ids),
        )

    def entry_ids(self, collection_id: int) -> list[int]:
        rows = self.db.query(
            "SELECT entry_id FROM collection_entries WHERE collection_id = ? "
            "ORDER BY position ASC",
            (collection_id,),
        )
        return [int(row["entry_id"]) for row in rows]

    def entries_for(self, collection_id: int) -> list[Entry]:
        rows = self.db.query(
            "SELECT e.* FROM entries e JOIN collection_entries ce ON ce.entry_id = e.id "
            "WHERE ce.collection_id = ? ORDER BY ce.position ASC",
            (collection_id,),
        )
        entry_repo = EntryRepository(self.db)
        return [entry_repo.from_row(row) for row in rows]

    def collections_for_entry(self, entry_id: int) -> list[Collection]:
        rows = self.db.query(
            "SELECT c.* FROM collections c JOIN collection_entries ce ON ce.collection_id = c.id "
            "WHERE ce.entry_id = ? ORDER BY c.name ASC",
            (entry_id,),
        )
        return [self.from_row(row) for row in rows]


class DocumentRepository(ModelRepository[Document]):
    table = "documents"
    model = Document
    order_by = "updated_at DESC, id DESC"

    def by_sha256(self, sha256: str) -> Document | None:
        if not sha256:
            return None
        row = self.db.query_one("SELECT * FROM documents WHERE sha256 = ?", (sha256,))
        return self.from_row(row) if row else None

    def set_status(
        self, document_id: int, status: str, *, error: str = "", chunk_count: int | None = None
    ) -> None:
        from minics.core.utils import utcnow_iso

        if chunk_count is None:
            self.db.update(
                "UPDATE documents SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, utcnow_iso(), document_id),
            )
        else:
            self.db.update(
                "UPDATE documents SET status = ?, error = ?, chunk_count = ?, updated_at = ? "
                "WHERE id = ?",
                (status, error, chunk_count, utcnow_iso(), document_id),
            )


class DocumentChunkRepository(ModelRepository[DocumentChunk]):
    table = "document_chunks"
    model = DocumentChunk
    column_map = {"index": "idx"}
    order_by = "idx ASC"

    def list_for_document(self, document_id: int) -> list[DocumentChunk]:
        return self.list(where="document_id = ?", params=(document_id,))

    def clear_for_document(self, document_id: int) -> int:
        return self.db.update("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))

    def by_ids(self, chunk_ids: list[int]) -> list[DocumentChunk]:
        if not chunk_ids:
            return []
        placeholders = ", ".join("?" for _ in chunk_ids)
        return [
            self.from_row(row)
            for row in self.db.query(
                f"SELECT * FROM document_chunks WHERE id IN ({placeholders})",
                tuple(chunk_ids),
            )
        ]

    def by_vector_ids(self, vector_ids: list[str]) -> list[DocumentChunk]:
        if not vector_ids:
            return []
        placeholders = ", ".join("?" for _ in vector_ids)
        return [
            self.from_row(row)
            for row in self.db.query(
                f"SELECT * FROM document_chunks WHERE vector_id IN ({placeholders})",
                tuple(vector_ids),
            )
        ]


class ConversationRepository(ModelRepository[Conversation]):
    table = "conversations"
    model = Conversation
    order_by = "updated_at DESC, id DESC"


class ConversationMessageRepository(ModelRepository[ConversationMessage]):
    table = "conversation_messages"
    model = ConversationMessage
    column_map = {"index": "idx"}
    order_by = "idx ASC"

    def list_for_conversation(self, conversation_id: int) -> list[ConversationMessage]:
        return self.list(where="conversation_id = ?", params=(conversation_id,))

    def next_index(self, conversation_id: int) -> int:
        value = self.db.scalar(
            "SELECT MAX(idx) FROM conversation_messages WHERE conversation_id = ?",
            (conversation_id,),
            default=-1,
        )
        return int(value if value is not None else -1) + 1
