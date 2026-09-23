"""Document ingestion helpers (conversion to markdown, file handling)."""

from __future__ import annotations

from minics.documents.convert import (
    SUPPORTED_EXTENSIONS,
    ConvertedDocument,
    UnsupportedDocumentError,
    clean_markdown,
    convert_file,
    detect_kind,
    is_supported,
    read_text,
)

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "ConvertedDocument",
    "UnsupportedDocumentError",
    "clean_markdown",
    "convert_file",
    "detect_kind",
    "is_supported",
    "read_text",
]
