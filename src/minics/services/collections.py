"""Collections: curated sets of entries that can be exported."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from minics.domain.entities import Collection, Entry, ExportRequest
from minics.services.base import NotFoundError, Service
from minics.services.export import ExportFormat, export_entries
from minics.services.repositories import CollectionRepository, DatasetRepository, EntryRepository


class CollectionService(Service):
    """Create, curate and export collections of entries."""

    name = "collections"

    def __init__(self, ctx) -> None:  # noqa: D401 - simple
        super().__init__(ctx)
        self.repo = CollectionRepository(ctx.db)
        self.entries = EntryRepository(ctx.db)
        self.datasets = DatasetRepository(ctx.db)

    # -- reads -----------------------------------------------------------
    def list(
        self, *, search: str | None = None, dataset: int | str | None = None
    ) -> list[Collection]:
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            clauses.append("(name LIKE ? OR description LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])
        if dataset is not None:
            clauses.append("dataset_id = ?")
            params.append(self.resolve_id(self.datasets, dataset))
        where = " AND ".join(clauses)
        collections = self.repo.list(where=where, params=tuple(params))
        for collection in collections:
            collection.entry_ids = self.repo.entry_ids(int(collection.id))
        return collections

    def get(self, ref: int | str) -> Collection:
        collection = self.repo.get(self.resolve_id(self.repo, ref))
        if collection is None:
            raise NotFoundError(f"Collection '{ref}' not found")
        collection.entry_ids = self.repo.entry_ids(int(collection.id))
        return collection

    def entry_ids(self, ref: int | str) -> list[int]:
        return self.repo.entry_ids(self.resolve_id(self.repo, ref))

    def entries_for(self, ref: int | str) -> list[Entry]:
        return self.repo.entries_for(self.resolve_id(self.repo, ref))

    def stats(self, ref: int | str) -> dict[str, Any]:
        collection = self.get(ref)
        entries = self.entries_for(ref)
        approved = sum(
            1 for e in entries if getattr(e.status, "value", e.status) == "approved"
        )
        return {
            "collection_id": int(collection.id),
            "entries": len(entries),
            "approved": approved,
            "tags": collection.tags,
        }

    # -- writes ----------------------------------------------------------
    def create(
        self,
        name: str,
        *,
        description: str = "",
        dataset: int | str | None = None,
        tags: Sequence[str] | None = None,
        entry_ids: Sequence[int] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Collection:
        dataset_id = self.resolve_id(self.datasets, dataset) if dataset is not None else None
        collection = Collection(
            name=(name or "").strip() or "Untitled collection",
            slug=self.unique_slug(self.repo, name or "collection"),
            description=description or "",
            dataset_id=dataset_id,
            tags=list(tags or []),
            metadata=dict(metadata or {}),
        )
        self.repo.insert(collection)
        if entry_ids:
            self.repo.add_entries(int(collection.id), list(entry_ids))
        self.emit(
            "collection.created",
            f"Collection '{collection.name}' created",
            collection=collection.public_id,
        )
        return self.get(int(collection.id))

    def update(self, ref: int | str, patch: dict[str, Any]) -> Collection:
        collection = self.get(ref)
        if patch.get("name"):
            collection.name = str(patch["name"]).strip() or collection.name
            collection.slug = self.unique_slug(self.repo, collection.name, exclude_id=collection.id)
        for field in ("description", "tags", "metadata"):
            if field in patch and patch[field] is not None:
                setattr(collection, field, patch[field])
        if "dataset" in patch:
            collection.dataset_id = (
                self.resolve_id(self.datasets, patch["dataset"])
                if patch["dataset"] is not None
                else None
            )
        self.repo.update(collection)
        self.emit(
            "collection.updated", f"Collection '{collection.name}' updated",
            collection=collection.public_id,
        )
        return self.get(int(collection.id))

    def delete(self, ref: int | str) -> bool:
        collection = self.get(ref)
        deleted = self.repo.delete(int(collection.id))
        if deleted:
            self.emit("collection.deleted", f"Collection '{collection.name}' deleted")
        return deleted

    # -- membership ------------------------------------------------------
    def add_entries(self, ref: int | str, entry_refs: Sequence[int | str]) -> Collection:
        collection_id = self.resolve_id(self.repo, ref)
        ids = [self.resolve_id(self.entries, e) for e in entry_refs]
        self.repo.add_entries(collection_id, ids)
        collection = self.get(collection_id)
        self.emit(
            "collection.entries_added",
            f"{len(ids)} entries added to '{collection.name}'",
            collection=collection.public_id,
        )
        return collection

    def remove_entries(self, ref: int | str, entry_refs: Sequence[int | str]) -> Collection:
        collection_id = self.resolve_id(self.repo, ref)
        ids = [self.resolve_id(self.entries, e) for e in entry_refs]
        self.repo.remove_entries(collection_id, ids)
        return self.get(collection_id)

    def set_entries(self, ref: int | str, entry_refs: Sequence[int | str]) -> Collection:
        """Replace the membership wholesale."""
        collection_id = self.resolve_id(self.repo, ref)
        self.repo.remove_entries(collection_id, self.repo.entry_ids(collection_id))
        return self.add_entries(collection_id, entry_refs)

    def collections_for_entry(self, entry_ref: int | str) -> list[Collection]:
        entry_id = self.resolve_id(self.entries, entry_ref)
        return self.repo.collections_for_entry(entry_id)

    # -- export ----------------------------------------------------------
    def export(
        self,
        ref: int | str,
        *,
        fmt: ExportFormat = "chatml",
        include_metadata: bool = False,
        only_approved: bool = False,
    ) -> str:
        entries = self.entries_for(ref)
        if only_approved:
            entries = [
                e for e in entries if getattr(e.status, "value", e.status) == "approved"
            ]
        return export_entries(entries, fmt, include_metadata=include_metadata)

    def export_request(self, ref: int | str, request: ExportRequest) -> str:
        return self.export(
            ref,
            fmt=request.format,
            include_metadata=request.include_metadata,
            only_approved=bool(request.statuses)
            and all(getattr(s, "value", s) == "approved" for s in request.statuses),
        )
