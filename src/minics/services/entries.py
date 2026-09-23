"""ChatML entry operations: authoring, review, versioning."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from minics.domain.entities import (
    ChatMessage,
    Entry,
    EntryStatus,
    Evaluation,
    Role,
    SourceKind,
)
from minics.services.base import NotFoundError, Service
from minics.services.repositories import DatasetRepository, EntryRepository


def _coerce_messages(value: Any) -> list[ChatMessage]:
    if value is None:
        return []
    messages: list[ChatMessage] = []
    for item in value:
        if isinstance(item, ChatMessage):
            messages.append(item)
        elif isinstance(item, dict):
            messages.append(ChatMessage.model_validate(item))
        else:  # pragma: no cover - defensive
            raise TypeError(f"Cannot build a ChatMessage from {type(item)!r}")
    return messages


def build_messages(
    *,
    messages: Iterable[Any] | None = None,
    system: str | None = None,
    user: str | None = None,
    assistant: str | None = None,
) -> list[ChatMessage]:
    """Normalise the many ways an entry can be described into ChatML."""
    if messages:
        return _coerce_messages(messages)
    built: list[ChatMessage] = []
    if system:
        built.append(ChatMessage(role=Role.SYSTEM, content=system))
    if user:
        built.append(ChatMessage(role=Role.USER, content=user))
    if assistant:
        built.append(ChatMessage(role=Role.ASSISTANT, content=assistant))
    return built


class EntryService(Service):
    """Create, review, edit and version dataset entries."""

    name = "entries"

    def __init__(self, ctx) -> None:  # noqa: D401 - simple
        super().__init__(ctx)
        self.repo = EntryRepository(ctx.db)
        self.datasets = DatasetRepository(ctx.db)

    # -- reads -----------------------------------------------------------
    def list(
        self,
        *,
        dataset: int | str | None = None,
        status: EntryStatus | str | None = None,
        search: str | None = None,
        tag: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Entry]:
        where, params = self._filters(dataset, status, search, tag)
        return self.repo.list(where=where, params=params, limit=limit, offset=offset)

    def count(
        self,
        *,
        dataset: int | str | None = None,
        status: EntryStatus | str | None = None,
        search: str | None = None,
        tag: str | None = None,
    ) -> int:
        where, params = self._filters(dataset, status, search, tag)
        return self.repo.count(where=where, params=params)

    def get(self, ref: int | str) -> Entry:
        entry = self.repo.get(self.resolve_id(self.repo, ref))
        if entry is None:
            raise NotFoundError(f"Entry '{ref}' not found")
        return entry

    def versions(self, ref: int | str) -> list[dict[str, Any]]:
        return self.repo.versions(self.resolve_id(self.repo, ref))

    def validate(self, ref: int | str) -> dict[str, Any]:
        entry = self.get(ref)
        problems = entry.validate_chatml()
        return {"valid": not problems, "problems": problems}

    # -- writes ----------------------------------------------------------
    def create(
        self,
        dataset: int | str | None = None,
        *,
        messages: Iterable[Any] | None = None,
        system: str | None = None,
        user: str | None = None,
        assistant: str | None = None,
        tags: Sequence[str] | None = None,
        status: EntryStatus | str = EntryStatus.DRAFT,
        notes: str = "",
        source: SourceKind | str = SourceKind.MANUAL,
        metadata: dict[str, Any] | None = None,
        position: int | None = None,
    ) -> Entry:
        dataset_id = None
        if dataset is not None:
            dataset_id = self.resolve_id(self.datasets, dataset)
        entry = Entry(
            dataset_id=dataset_id,
            messages=build_messages(
                messages=messages, system=system, user=user, assistant=assistant
            ),
            tags=list(tags or []),
            status=EntryStatus(status),
            notes=notes or "",
            source=SourceKind(source),
            metadata=dict(metadata or {}),
            position=position if position is not None else self.repo.next_position(dataset_id),
        )
        self.repo.insert(entry)
        self.repo.add_version(entry, reason="created")
        self.emit(
            "entry.created",
            f"Entry #{entry.position} created",
            dataset=dataset_id,
            entry=entry.public_id,
        )
        return entry

    def create_from_chatml(self, payload: dict[str, Any], **kwargs: Any) -> Entry:
        """Create an entry from a ChatML dict (``{"messages": [...]}``)."""
        messages = payload.get("messages") if isinstance(payload, dict) else None
        return self.create(messages=messages, **kwargs)

    def update(
        self,
        ref: int | str,
        patch: dict[str, Any],
        *,
        reason: str = "edited",
    ) -> Entry:
        entry = self.get(ref)
        previous = entry.model_copy(deep=True)
        messages_changed = False

        if "messages" in patch and patch["messages"] is not None:
            new_messages = _coerce_messages(patch["messages"])
            if [m.model_dump() for m in new_messages] != [
                m.model_dump() for m in entry.messages
            ]:
                messages_changed = True
            entry.messages = new_messages
        for field in ("tags", "notes", "metadata"):
            if field in patch and patch[field] is not None:
                setattr(entry, field, patch[field])
        if patch.get("status") is not None:
            entry.status = EntryStatus(patch["status"])
        if patch.get("quality") is not None:
            entry.quality = float(patch["quality"])
        if patch.get("evaluation") is not None:
            entry.evaluation = (
                patch["evaluation"]
                if isinstance(patch["evaluation"], Evaluation)
                else Evaluation.model_validate(patch["evaluation"])
            )
        if patch.get("position") is not None:
            entry.position = int(patch["position"])
        if patch.get("source") is not None:
            entry.source = SourceKind(patch["source"])

        if messages_changed:
            entry.version = previous.version + 1

        self.repo.update(entry)
        if messages_changed:
            self.repo.add_version(entry, reason=reason)
        self.emit("entry.updated", f"Entry '{entry.public_id}' updated", entry=entry.public_id)
        return entry

    def set_status(self, ref: int | str, status: EntryStatus | str) -> Entry:
        return self.update(ref, {"status": status}, reason="status change")

    def set_evaluation(self, ref: int | str, evaluation: Evaluation | dict[str, Any]) -> Entry:
        value = (
            evaluation
            if isinstance(evaluation, Evaluation)
            else Evaluation.model_validate(evaluation)
        )
        return self.update(
            ref,
            {"evaluation": value, "quality": value.score},
            reason="evaluation",
        )

    def add_tags(self, ref: int | str, tags: Sequence[str]) -> Entry:
        entry = self.get(ref)
        merged = list(dict.fromkeys([*entry.tags, *[t.strip() for t in tags if t and t.strip()]]))
        return self.update(ref, {"tags": merged}, reason="tags")

    def delete(self, ref: int | str) -> bool:
        entry = self.get(ref)
        deleted = self.repo.delete(int(entry.id))
        if deleted:
            self.emit("entry.deleted", f"Entry '{entry.public_id}' deleted")
        return deleted

    def bulk_create(
        self,
        entries: Iterable[Any],
        *,
        dataset: int | str | None = None,
        status: EntryStatus | str = EntryStatus.DRAFT,
        source: SourceKind | str = SourceKind.IMPORT,
    ) -> list[Entry]:
        """Create many entries from ChatML dicts or raw message lists."""
        created: list[Entry] = []
        for payload in entries:
            if isinstance(payload, dict) and "messages" in payload:
                data = {k: v for k, v in payload.items() if k != "messages"}
                created.append(
                    self.create(
                        dataset=data.pop("dataset", dataset),
                        messages=payload["messages"],
                        status=data.pop("status", status),
                        source=data.pop("source", source),
                        **data,
                    )
                )
            else:
                created.append(
                    self.create(dataset=dataset, messages=payload, status=status, source=source)
                )
        return created

    # -- internals -------------------------------------------------------
    def _filters(
        self,
        dataset: int | str | None,
        status: EntryStatus | str | None,
        search: str | None,
        tag: str | None,
    ) -> tuple[str, tuple]:
        clauses: list[str] = []
        params: list[Any] = []
        if dataset is not None:
            clauses.append("dataset_id = ?")
            params.append(self.resolve_id(self.datasets, dataset))
        if status is not None:
            clauses.append("status = ?")
            params.append(EntryStatus(status).value)
        if search:
            clauses.append("(messages LIKE ? OR notes LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])
        if tag:
            clauses.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        return " AND ".join(clauses), tuple(params)
