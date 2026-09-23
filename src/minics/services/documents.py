"""Document library: import, convert, store and edit source documents."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from minics.core.utils import sha256_bytes, utcnow_iso
from minics.documents.convert import (
    SUPPORTED_EXTENSIONS,
    clean_markdown,
    convert_file,
    detect_kind,
    is_supported,
)
from minics.domain.entities import Document, DocumentStatus
from minics.services.base import NotFoundError, Service
from minics.services.repositories import DocumentChunkRepository, DocumentRepository

#: A cleaner receives ``(markdown, title)`` and returns improved markdown.
Cleaner = Callable[[str, str], str]

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", Path(name).name).strip("._")
    return cleaned or "document"


class DocumentService(Service):
    """Import documents and keep their cleaned markdown in sync."""

    name = "documents"

    def __init__(self, ctx) -> None:  # noqa: D401 - simple
        super().__init__(ctx)
        self.repo = DocumentRepository(ctx.db)
        self.chunks = DocumentChunkRepository(ctx.db)
        self.cleaner: Cleaner | None = None

    # -- reads -----------------------------------------------------------
    def list(
        self,
        *,
        search: str | None = None,
        status: DocumentStatus | str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            clauses.append("(title LIKE ? OR source LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])
        if status is not None:
            clauses.append("status = ?")
            params.append(getattr(status, "value", status))
        return self.repo.list(
            where=" AND ".join(clauses), params=tuple(params), limit=limit, offset=offset
        )

    def get(self, ref: int | str) -> Document:
        document = self.repo.get(self.resolve_id(self.repo, ref))
        if document is None:
            raise NotFoundError(f"Document '{ref}' not found")
        return document

    def read_markdown(self, ref: int | str) -> str:
        document = self.get(ref)
        path = Path(document.markdown_path)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def stats(self) -> dict[str, Any]:
        total = self.repo.count()
        ready = self.repo.count(
            where="status = ?", params=(DocumentStatus.READY.value,)
        )
        return {
            "documents": total,
            "ready": ready,
            "chunks": int(
                self.db.scalar("SELECT COUNT(*) FROM document_chunks", default=0)
            ),
            "bytes": int(
                self.db.scalar(
                    "SELECT COALESCE(SUM(size_bytes), 0) FROM documents", default=0
                )
            ),
        }

    # -- import ----------------------------------------------------------
    def import_file(
        self,
        path: str | Path,
        *,
        title: str | None = None,
        tags: Sequence[str] | None = None,
        source: str = "upload",
        run_cleaner: bool | None = None,
        progress: Callable[[float, str], None] | None = None,
    ) -> Document:
        source_path = Path(path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        if not is_supported(source_path):
            raise ValueError(
                f"Unsupported file type '{source_path.suffix}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )
        return self.import_bytes(
            source_path.read_bytes(),
            filename=source_path.name,
            title=title or source_path.stem,
            tags=tags,
            source=source,
            run_cleaner=run_cleaner,
            progress=progress,
        )

    def import_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        title: str | None = None,
        tags: Sequence[str] | None = None,
        source: str = "upload",
        run_cleaner: bool | None = None,
        progress: Callable[[float, str], None] | None = None,
    ) -> Document:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type '{suffix}'.")
        kind = detect_kind(filename)
        digest = sha256_bytes(data)
        existing = self.repo.by_sha256(digest)
        if existing is not None and Path(existing.markdown_path).exists():
            return existing

        _report(progress, 0.05, "Storing original")
        document = Document(
            title=(title or Path(filename).stem).strip() or Path(filename).stem,
            source=source,
            kind=kind,
            size_bytes=len(data),
            sha256=digest,
            status=DocumentStatus.CONVERTING,
            tags=list(tags or []),
            metadata={"filename": safe_filename(filename)},
        )
        self.repo.insert(document)

        original_path = self._original_path(int(document.id), document.public_id, suffix)
        original_path.write_bytes(data)
        document.original_path = str(original_path)

        markdown, meta = self._convert(original_path, document)
        document.metadata.update(meta)

        _report(progress, 0.5, "Cleaning markdown")
        markdown = self._maybe_clean(markdown, document, run_cleaner)

        markdown_path = self._markdown_path(document.public_id)
        markdown_path.write_text(markdown, encoding="utf-8")
        document.markdown_path = str(markdown_path)
        document.status = DocumentStatus.READY
        document.updated_at = utcnow_iso()
        self.repo.update(document)
        _report(progress, 1.0, "Converted to markdown")
        self.emit(
            "document.converted",
            f"'{document.title}' converted to markdown",
            document=document.public_id,
        )
        return document

    def import_files(
        self,
        paths: Iterable[str | Path],
        *,
        tags: Sequence[str] | None = None,
        source: str = "upload",
    ) -> list[Document]:
        return [self.import_file(p, tags=tags, source=source) for p in paths]

    def add_text(
        self,
        text: str,
        *,
        title: str = "Note",
        tags: Sequence[str] | None = None,
        source: str = "manual",
    ) -> Document:
        """Create a document directly from markdown text (no conversion)."""
        data = text.encode("utf-8")
        document = Document(
            title=title,
            source=source,
            kind="markdown",
            size_bytes=len(data),
            sha256=sha256_bytes(data),
            status=DocumentStatus.READY,
            tags=list(tags or []),
        )
        self.repo.insert(document)
        markdown_path = self._markdown_path(document.public_id)
        markdown_path.write_text(clean_markdown(text), encoding="utf-8")
        document.markdown_path = str(markdown_path)
        self.repo.update(document)
        self.emit("document.created", f"Document '{title}' created", document=document.public_id)
        return document

    # -- editing ---------------------------------------------------------
    def write_markdown(self, ref: int | str, markdown: str) -> Document:
        document = self.get(ref)
        path = Path(document.markdown_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        document.metadata["edited"] = True
        document.updated_at = utcnow_iso()
        self.repo.update(document)
        self.emit("document.edited", f"'{document.title}' markdown updated")
        return document

    def reconvert(self, ref: int | str, *, run_cleaner: bool | None = None) -> Document:
        """Re-derive markdown from the stored original file."""
        document = self.get(ref)
        original = Path(document.original_path)
        if not original.exists():
            raise FileNotFoundError(original)
        markdown, meta = self._convert(original, document)
        document.metadata.update(meta)
        markdown = self._maybe_clean(markdown, document, run_cleaner)
        Path(document.markdown_path).write_text(markdown, encoding="utf-8")
        document.status = DocumentStatus.READY
        document.error = ""
        document.updated_at = utcnow_iso()
        self.repo.update(document)
        self.emit("document.reconverted", f"'{document.title}' reconverted")
        return document

    def delete(self, ref: int | str) -> bool:
        document = self.get(ref)
        for path in (document.original_path, document.markdown_path):
            if path and Path(path).exists():
                Path(path).unlink()
        deleted = self.repo.delete(int(document.id))
        if deleted:
            self.emit("document.deleted", f"'{document.title}' deleted")
        return deleted

    def set_status(self, ref: int | str, status: DocumentStatus | str, *, error: str = "") -> None:
        document = self.get(ref)
        self.repo.set_status(int(document.id), getattr(status, "value", status), error=error)

    # -- internals -------------------------------------------------------
    def _original_path(self, document_id: int, public_id: str, suffix: str) -> Path:
        directory = self.ctx.paths.originals_dir
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{document_id}-{public_id}{suffix}"

    def _markdown_path(self, public_id: str) -> Path:
        directory = self.ctx.paths.markdown_dir
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{public_id}.md"

    def _convert(self, original: Path, document: Document) -> tuple[str, dict]:
        try:
            if document.kind == "markdown":
                text = original.read_text(encoding="utf-8", errors="replace")
                return clean_markdown(text), {}
            converted = convert_file(original)
            return converted.markdown, dict(converted.metadata)
        except Exception as exc:  # noqa: BLE001 - recorded on the document
            self.repo.set_status(int(document.id), DocumentStatus.ERROR.value, error=str(exc))
            raise

    def _maybe_clean(
        self, markdown: str, document: Document, run_cleaner: bool | None
    ) -> str:
        enabled = self.config.app.clean_imports_with_llm if run_cleaner is None else run_cleaner
        cleaner = self.cleaner or _default_cleaner(self.ctx)
        if not enabled or cleaner is None:
            return clean_markdown(markdown)
        try:
            cleaned = cleaner(markdown, document.title)
            return clean_markdown(cleaned) if cleaned else clean_markdown(markdown)
        except Exception as exc:  # noqa: BLE001 - cleaning is best-effort
            self.emit(
                "document.clean_failed",
                f"LLM cleanup failed, using heuristic cleanup: {exc}",
                level="warning",
            )
            return clean_markdown(markdown)


def _default_cleaner(ctx) -> Cleaner | None:
    """Look up the LLM markdown cleaner lazily (available from v0.0.14)."""
    if not ctx.config.is_ready():
        return None
    try:
        from minics.llm.enhance import clean_markdown as llm_clean
    except Exception:  # noqa: BLE001 - cleaner is optional
        return None
    return lambda markdown, title: llm_clean(markdown, title=title, config=ctx.config)


def _report(progress: Callable[[float, str], None] | None, value: float, message: str) -> None:
    if progress is not None:
        progress(value, message)
