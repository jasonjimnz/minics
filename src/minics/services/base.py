"""Shared service plumbing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from minics.services.context import AppContext


class NotFoundError(LookupError):
    """Raised when an entity referenced by id/public_id does not exist."""


class Service:
    """Base class for the service layer.

    A service is a thin, stateless façade over one or more repositories; it owns
    business rules and publishes events, but never touches SQLite directly.
    """

    name: str = "service"

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    # -- shortcuts -------------------------------------------------------
    @property
    def db(self):
        return self.ctx.db

    @property
    def config(self):
        return self.ctx.config

    def emit(self, type: str, message: str = "", level: str = "info", **data: Any):
        return self.ctx.bus.publish(
            type=type, message=message, level=level, source=self.name, data=data
        )

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def resolve_id(repo, ref: int | str) -> int:
        """Turn an ``int`` id or ``str`` public id into a numeric id."""
        if isinstance(ref, int):
            return ref
        if isinstance(ref, str) and ref.isdigit():
            return int(ref)
        entity = repo.get_by_public_id(str(ref))
        if entity is None or getattr(entity, "id", None) is None:
            raise NotFoundError(f"{repo.table}: no entity with id '{ref}'")
        return int(entity.id)

    @classmethod
    def unique_slug(cls, repo, base: str, *, exclude_id: int | None = None) -> str:
        from minics.core.utils import slugify

        slug = slugify(base, fallback="item")
        candidate = slug
        counter = 1
        while True:
            existing = repo.by_slug(candidate)
            if existing is None or getattr(existing, "id", None) == exclude_id:
                return candidate
            counter += 1
            candidate = f"{slug}-{counter}"
