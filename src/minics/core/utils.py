"""Small shared helpers used across layers."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    """RFC-3339-ish UTC timestamp, second precision, ``Z`` suffix."""
    return utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id() -> str:
    """Short, URL-safe public identifier."""
    return uuid.uuid4().hex[:16]


def slugify(value: str, *, fallback: str = "item") -> str:
    normalized = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    slug = _SLUG_RE.sub("-", normalized.lower()).strip("-")
    return slug or fallback


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Any, *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def json_dumps(value: Any) -> str:
    """Compact, stable JSON for storing structured columns."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def json_loads(value: str | bytes | None, default: Any = None) -> Any:
    if value in (None, "", b""):
        return default
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def truncate(text: str, length: int = 200, suffix: str = "...") -> str:
    text = text or ""
    return text if len(text) <= length else text[: max(0, length - len(suffix))] + suffix


def coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
