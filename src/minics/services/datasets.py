"""Dataset library operations."""

from __future__ import annotations

from typing import Any

from minics.domain.entities import Dataset, EntryStatus, SourceKind
from minics.services.base import NotFoundError, Service
from minics.services.repositories import DatasetRepository, EntryRepository


class DatasetService(Service):
    """Create, browse, update and delete datasets."""

    name = "datasets"

    def __init__(self, ctx) -> None:  # noqa: D401 - simple
        super().__init__(ctx)
        self.repo = DatasetRepository(ctx.db)
        self.entries = EntryRepository(ctx.db)

    # -- reads -----------------------------------------------------------
    def list(
        self,
        *,
        search: str | None = None,
        tag: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Dataset]:
        where, params = self._filters(search, tag)
        return self.repo.list(where=where, params=params, limit=limit, offset=offset)

    def count(self, *, search: str | None = None, tag: str | None = None) -> int:
        where, params = self._filters(search, tag)
        return self.repo.count(where=where, params=params)

    def get(self, ref: int | str) -> Dataset:
        dataset = self.repo.get(self.resolve_id(self.repo, ref))
        if dataset is None:
            raise NotFoundError(f"Dataset '{ref}' not found")
        return dataset

    def stats(self, ref: int | str) -> dict[str, Any]:
        dataset_id = self.resolve_id(self.repo, ref)
        total = self.entries.count_for_dataset(dataset_id)
        by_status = {
            status.value: self.entries.count(
                where="dataset_id = ? AND status = ?", params=(dataset_id, status.value)
            )
            for status in EntryStatus
        }
        return {
            "dataset_id": dataset_id,
            "entries": total,
            "by_status": by_status,
            "approved": by_status[EntryStatus.APPROVED.value],
        }

    # -- writes ----------------------------------------------------------
    def create(
        self,
        name: str,
        *,
        description: str = "",
        tags: list[str] | None = None,
        source: SourceKind | str = SourceKind.MANUAL,
        metadata: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Dataset:
        name = (name or "").strip() or "Untitled dataset"
        dataset = Dataset(
            name=name,
            slug=self.unique_slug(self.repo, name),
            description=description or "",
            tags=list(tags or []),
            source=SourceKind(source),
            metadata=dict(metadata or {}),
            settings=dict(settings or {}),
        )
        self.repo.insert(dataset)
        self.emit("dataset.created", f"Dataset '{dataset.name}' created", dataset=dataset.public_id)
        return dataset

    def update(self, ref: int | str, patch: dict[str, Any]) -> Dataset:
        dataset = self.get(ref)
        if "name" in patch and patch["name"]:
            dataset.name = str(patch["name"]).strip() or dataset.name
            dataset.slug = self.unique_slug(self.repo, dataset.name, exclude_id=dataset.id)
        for field in ("description", "tags", "metadata", "settings"):
            if field in patch and patch[field] is not None:
                setattr(dataset, field, patch[field])
        if "source" in patch and patch["source"]:
            dataset.source = SourceKind(patch["source"])
        self.repo.update(dataset)
        self.emit("dataset.updated", f"Dataset '{dataset.name}' updated", dataset=dataset.public_id)
        return dataset

    def delete(self, ref: int | str) -> bool:
        dataset = self.get(ref)
        deleted = self.repo.delete(int(dataset.id))
        if deleted:
            self.emit("dataset.deleted", f"Dataset '{dataset.name}' deleted")
        return deleted

    # -- internals -------------------------------------------------------
    @staticmethod
    def _filters(search: str | None, tag: str | None) -> tuple[str, tuple]:
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            clauses.append("(name LIKE ? OR description LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])
        if tag:
            clauses.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        return " AND ".join(clauses), tuple(params)
