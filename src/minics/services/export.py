"""Dataset export formats.

A collection (or any set of entries) can be rendered as ChatML, JSONL, Alpaca,
ShareGPT or Markdown.  Keeping this in one module means the UI, the CLI and the
library all produce byte-identical exports.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Literal

from minics.domain.entities import ChatMessage, Entry, Role

ExportFormat = Literal["chatml", "jsonl", "alpaca", "sharegpt", "markdown"]

FORMATS: tuple[str, ...] = ("chatml", "jsonl", "alpaca", "sharegpt", "markdown")


def _messages(entry: Entry) -> list[ChatMessage]:
    return list(entry.messages)


def to_chatml(entry: Entry, *, include_metadata: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = entry.to_chatml()
    if include_metadata:
        payload["metadata"] = {
            "public_id": entry.public_id,
            "tags": entry.tags,
            "status": entry.status.value if hasattr(entry.status, "value") else entry.status,
            "quality": entry.quality,
            "notes": entry.notes,
        }
    return payload


def to_alpaca(entry: Entry) -> dict[str, Any]:
    system = entry.first(Role.SYSTEM)
    user = entry.first(Role.USER)
    assistant = entry.first(Role.ASSISTANT)
    return {
        "system": system.content if system else "",
        "instruction": user.content if user else "",
        "input": "",
        "output": assistant.content if assistant else "",
    }


def to_sharegpt(entry: Entry) -> dict[str, Any]:
    mapping = {"system": "system", "user": "human", "assistant": "gpt", "tool": "tool"}
    conversations = [
        {"from": mapping.get(m.role_name, m.role_name), "value": m.content}
        for m in _messages(entry)
        if m.content.strip()
    ]
    return {"conversations": conversations}


def to_markdown(entry: Entry, *, index: int | None = None) -> str:
    lines: list[str] = []
    title = f"Entry {entry.public_id}"
    if index is not None:
        title = f"#{index} · {entry.public_id}"
    lines.append(f"## {title}")
    status = entry.status.value if hasattr(entry.status, "value") else entry.status
    meta_bits = [f"status: {status}"]
    if entry.tags:
        meta_bits.append("tags: " + ", ".join(entry.tags))
    if entry.quality is not None:
        meta_bits.append(f"quality: {entry.quality:.2f}")
    lines.append(f"*{' · '.join(meta_bits)}*")
    lines.append("")
    for message in _messages(entry):
        lines.append(f"**{message.role_name}**")
        lines.append("")
        lines.append(message.content.strip() or "_(empty)_")
        lines.append("")
    if entry.notes:
        lines.append(f"> {entry.notes}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_entry(
    entry: Entry,
    fmt: ExportFormat = "chatml",
    *,
    include_metadata: bool = False,
    index: int | None = None,
) -> str:
    if fmt == "chatml":
        return json.dumps(to_chatml(entry, include_metadata=include_metadata), ensure_ascii=False)
    if fmt == "jsonl":
        return json.dumps(to_chatml(entry, include_metadata=include_metadata), ensure_ascii=False)
    if fmt == "alpaca":
        return json.dumps(to_alpaca(entry), ensure_ascii=False)
    if fmt == "sharegpt":
        return json.dumps(to_sharegpt(entry), ensure_ascii=False)
    if fmt == "markdown":
        return to_markdown(entry, index=index)
    raise ValueError(f"Unsupported export format: {fmt}")


def export_entries(
    entries: Iterable[Entry],
    fmt: ExportFormat = "chatml",
    *,
    include_metadata: bool = False,
) -> str:
    """Render a sequence of entries to a single string."""
    materialised = list(entries)
    if fmt == "markdown":
        blocks = [to_markdown(e, index=i) for i, e in enumerate(materialised, start=1)]
        return "\n".join(blocks)
    lines = [
        render_entry(e, fmt, include_metadata=include_metadata, index=i)
        for i, e in enumerate(materialised, start=1)
    ]
    return "\n".join(lines) + ("\n" if lines else "")
