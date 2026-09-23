"""Generic SQLite repository for pydantic entities.

Writing the same CRUD boilerplate for datasets, entries, collections, documents
and conversations would be tedious and error prone.  :class:`ModelRepository`
derives the column layout from the pydantic model itself:

* scalars → native columns,
* ``bool`` → ``0``/``1``,
* enums → their string value,
* lists/dicts/nested models → compact JSON text.

Subclasses only declare ``table``, ``model`` and (rarely) ``exclude``.
"""

from __future__ import annotations

import types
from collections.abc import Sequence
from typing import Any, ClassVar, Generic, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel

from minics.core.db import Database
from minics.core.utils import json_dumps, json_loads

M = TypeVar("M", bound=BaseModel)


def _unwrap(annotation: Any) -> Any:
    """Peel ``Optional[...]`` / ``Union[..., None]`` down to the real type."""
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _unwrap(args[0])
    return annotation


def _is_json(annotation: Any) -> bool:
    inner = _unwrap(annotation)
    if isinstance(inner, type) and issubclass(inner, BaseModel):
        return True
    origin = get_origin(inner)
    return origin in (list, dict, tuple, set)


def _is_bool(annotation: Any) -> bool:
    return _unwrap(annotation) is bool


class ModelRepository(Generic[M]):
    """CRUD helpers backed by a :class:`~minics.core.db.Database`."""

    table: ClassVar[str] = ""
    model: ClassVar[type[BaseModel]]
    exclude: ClassVar[frozenset[str]] = frozenset()
    #: Optional field name → database column renames (e.g. ``index`` → ``idx``).
    column_map: ClassVar[dict[str, str]] = {}
    order_by: ClassVar[str] = "id ASC"

    json_columns: ClassVar[frozenset[str]] = frozenset()
    bool_columns: ClassVar[frozenset[str]] = frozenset()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        model = getattr(cls, "model", None)
        if model is None:
            return
        json_cols, bool_cols = set(), set()
        for name, field in model.model_fields.items():
            if name in cls.exclude or name == "id":
                continue
            if _is_json(field.annotation):
                json_cols.add(name)
            elif _is_bool(field.annotation):
                bool_cols.add(name)
        cls.json_columns = frozenset(json_cols)
        cls.bool_columns = frozenset(bool_cols)

    def __init__(self, db: Database) -> None:
        self.db = db

    # -- mapping ---------------------------------------------------------
    def db_column(self, field: str) -> str:
        return self.column_map.get(field, field)

    def field_columns(self) -> list[tuple[str, str]]:
        """``(field_name, db_column)`` pairs persisted for this entity."""
        return [
            (name, self.db_column(name))
            for name in self.model.model_fields
            if name != "id" and name not in self.exclude
        ]

    def columns(self) -> list[str]:
        """Database column names for this entity (``id`` excluded)."""
        return [column for _field, column in self.field_columns()]

    def to_row(self, entity: M) -> dict[str, Any]:
        data = entity.model_dump(mode="json")
        row: dict[str, Any] = {}
        for field, column in self.field_columns():
            value = data.get(field)
            if field in self.json_columns:
                row[column] = None if value is None else json_dumps(value)
            elif field in self.bool_columns:
                row[column] = 1 if value else 0
            else:
                row[column] = value
        return row

    def from_row(self, row: Any) -> M:
        data = dict(row)
        mapped: dict[str, Any] = {"id": data.get("id")}
        for field, column in self.field_columns():
            if column not in data:
                continue
            value = data[column]
            annotation = self.model.model_fields[field].annotation
            if field in self.json_columns:
                value = json_loads(value, default=None)
                if value is None:
                    value = _json_fallback(annotation)
            elif field in self.bool_columns:
                value = bool(value)
            mapped[field] = value
        return self.model.model_validate(mapped)

    # -- reads -----------------------------------------------------------
    def get(self, entity_id: int) -> M | None:
        row = self.db.query_one(f"SELECT * FROM {self.table} WHERE id = ?", (entity_id,))
        return self.from_row(row) if row else None

    def get_by_public_id(self, public_id: str) -> M | None:
        row = self.db.query_one(
            f"SELECT * FROM {self.table} WHERE public_id = ?", (public_id,)
        )
        return self.from_row(row) if row else None

    def list(
        self,
        *,
        where: str = "",
        params: Sequence[Any] = (),
        limit: int | None = None,
        offset: int = 0,
    ) -> list[M]:
        sql = f"SELECT * FROM {self.table}"
        if where:
            sql += f" WHERE {where}"
        sql += f" ORDER BY {self.order_by}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = (*params, limit, offset)
        return [self.from_row(row) for row in self.db.query(sql, tuple(params))]

    def count(self, *, where: str = "", params: Sequence[Any] = ()) -> int:
        sql = f"SELECT COUNT(*) FROM {self.table}"
        if where:
            sql += f" WHERE {where}"
        return int(self.db.scalar(sql, tuple(params), default=0))

    def exists(self, **filters: Any) -> bool:
        if not filters:
            return False
        clause = " AND ".join(f"{key} = ?" for key in filters)
        return self.count(where=clause, params=tuple(filters.values())) > 0

    # -- writes ----------------------------------------------------------
    def insert(self, entity: M) -> M:
        row = self.to_row(entity)
        columns = list(row)
        placeholders = ", ".join("?" for _ in columns)
        sql = (
            f"INSERT INTO {self.table} ({', '.join(columns)}) VALUES ({placeholders})"
        )
        new_id = self.db.insert(sql, tuple(row[column] for column in columns))
        if new_id and getattr(entity, "id", None) is None:
            entity.id = new_id  # type: ignore[attr-defined]
        return entity

    def update(self, entity: M) -> M:
        entity_id = getattr(entity, "id", None)
        if entity_id is None:
            raise ValueError("Cannot update an entity without an id.")
        touch = getattr(entity, "touch", None)
        if callable(touch):
            touch()
        row = self.to_row(entity)
        assignments = ", ".join(f"{column} = ?" for column in row)
        sql = f"UPDATE {self.table} SET {assignments} WHERE id = ?"
        self.db.update(sql, (*row.values(), entity_id))
        return entity

    def save(self, entity: M) -> M:
        if getattr(entity, "id", None) is None:
            return self.insert(entity)
        return self.update(entity)

    def delete(self, entity_id: int) -> bool:
        changed = self.db.update(f"DELETE FROM {self.table} WHERE id = ?", (entity_id,))
        return changed > 0

    def delete_by_public_id(self, public_id: str) -> bool:
        changed = self.db.update(
            f"DELETE FROM {self.table} WHERE public_id = ?", (public_id,)
        )
        return changed > 0

    # -- transactions ----------------------------------------------------
    def transaction(self, fn: Any) -> Any:
        return self.db.transaction(fn)


def _is_listish(annotation: Any) -> bool:
    return get_origin(_unwrap(annotation)) in (list, tuple, set)


def _is_mapping(annotation: Any) -> bool:
    return _unwrap(annotation) is dict or get_origin(_unwrap(annotation)) is dict


def _json_fallback(annotation: Any) -> Any:
    """Value to use when a JSON column is NULL."""
    if _is_listish(annotation):
        return []
    if _is_mapping(annotation):
        return {}
    return None
