"""Filesystem layout for MiniCS.

Everything the user owns lives inside a single home directory (``~/.minics`` by
default).  Keeping the layout in one place means the rest of the application
never has to build paths by hand and can be pointed at a temporary directory in
tests via the ``MINICS_HOME`` environment variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_HOME = "MINICS_HOME"
DEFAULT_HOME_NAME = ".minics"

#: Sub-directories that are created on first run.
STRUCTURE: tuple[str, ...] = (
    "documents",
    "documents/markdown",
    "documents/originals",
    "vectordb",
    "graphdb",
    "logs",
    "cache",
)


def default_home() -> Path:
    """Return the configured home directory, honouring ``MINICS_HOME``."""
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / DEFAULT_HOME_NAME).resolve()


@dataclass(frozen=True)
class MinicsPaths:
    """Resolved paths for a MiniCS installation."""

    root: Path

    # -- directories -----------------------------------------------------
    @property
    def documents(self) -> Path:
        return self.root / "documents"

    @property
    def markdown_dir(self) -> Path:
        """Converted, LLM-cleaned markdown copies of imported documents."""
        return self.documents / "markdown"

    @property
    def originals_dir(self) -> Path:
        """Untouched uploaded files, kept for provenance/re-extraction."""
        return self.documents / "originals"

    @property
    def vectordb(self) -> Path:
        """ChromaDB persistent directory."""
        return self.root / "vectordb"

    @property
    def graphdb(self) -> Path:
        """Ladybug graph database directory."""
        return self.root / "graphdb"

    @property
    def graph_file(self) -> Path:
        """Ladybug database file (Ladybug expects a file, not a directory)."""
        return self.graphdb / "minics.graph"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    # -- files -----------------------------------------------------------
    @property
    def config_file(self) -> Path:
        return self.root / "config.json"

    @property
    def database(self) -> Path:
        """Main SQLite database file."""
        return self.root / "minics.sqlite3"

    # -- helpers ---------------------------------------------------------
    @property
    def all_dirs(self) -> tuple[Path, ...]:
        return (self.root, *(self.root / name for name in STRUCTURE))

    def ensure(self) -> MinicsPaths:
        """Create the directory structure if it does not exist yet."""
        for directory in self.all_dirs:
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def exists(self) -> bool:
        return self.root.exists() and self.database.exists()

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return str(self.root)


def get_paths(root: str | os.PathLike[str] | None = None) -> MinicsPaths:
    """Build a :class:`MinicsPaths` for ``root`` (defaults to the user home)."""
    if root is None:
        return MinicsPaths(default_home())
    return MinicsPaths(Path(root).expanduser().resolve())
