"""Markdown-aware chunking.

Chunks are the unit of retrieval.  We split on markdown headings first so that
each chunk stays inside one section, then fall back to a recursive splitter for
sections that are still too large.  The heading trail is kept in metadata so the
graph and the UI can show where a chunk came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_HEADERS: tuple[tuple[str, str], ...] = (
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
    ("####", "h4"),
)


@dataclass
class Chunk:
    index: int
    text: str
    heading: str = ""
    tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """Cheap, model-agnostic token estimate (~4 chars/token)."""
    return max(1, len(text) // 4)


def _heading_trail(metadata: dict[str, Any]) -> str:
    parts = [metadata.get(key) for key in ("h1", "h2", "h3", "h4")]
    return " › ".join(str(p) for p in parts if p)


def split_markdown(
    markdown: str,
    *,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
) -> list[Chunk]:
    """Split markdown into overlapping, heading-aware chunks."""
    text = (markdown or "").strip()
    if not text:
        return []

    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[(symbol, name) for symbol, name in DEFAULT_HEADERS],
        strip_headers=False,
    )
    recursive = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    sections = header_splitter.split_text(text)
    if not sections:
        sections = []

    chunks: list[Chunk] = []
    for section in sections:
        body = getattr(section, "page_content", None) or str(section)
        metadata = dict(getattr(section, "metadata", {}) or {})
        heading = _heading_trail(metadata)
        pieces = recursive.split_text(body) if len(body) > chunk_size else [body]
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=piece,
                    heading=heading,
                    tokens=estimate_tokens(piece),
                    metadata={k: v for k, v in metadata.items() if v},
                )
            )

    if not chunks and text:
        for piece in recursive.split_text(text):
            if piece.strip():
                chunks.append(
                    Chunk(
                        index=len(chunks),
                        text=piece.strip(),
                        tokens=estimate_tokens(piece),
                    )
                )
    return chunks


def split_text(text: str, *, chunk_size: int = 1000, chunk_overlap: int = 150) -> list[Chunk]:
    """Plain-text splitter for non-markdown sources."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return [
        Chunk(index=i, text=piece.strip(), tokens=estimate_tokens(piece))
        for i, piece in enumerate(splitter.split_text(text or ""))
        if piece.strip()
    ]
