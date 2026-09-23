"""The application context: one object that wires everything together.

MiniCS is usable as a library, so there must be a single, explicit place where
paths, configuration, storage, background jobs and (later) the vector/graph
stores are assembled.  :class:`AppContext` is that place.

    from minics.services.context import get_context

    ctx = get_context()
    dataset = ctx.datasets.create(name="Support QA")
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from minics.core.config import Config, ConfigManager
from minics.core.db import Database
from minics.core.events import EventBus, get_event_bus
from minics.core.jobs import JobManager, get_job_manager
from minics.core.paths import MinicsPaths, get_paths

if TYPE_CHECKING:  # pragma: no cover
    pass


class AppContext:
    """Owns the long-lived resources of a MiniCS session."""

    def __init__(
        self,
        home: str | None = None,
        *,
        paths: MinicsPaths | None = None,
        config: Config | None = None,
        database: Database | None = None,
        event_bus: EventBus | None = None,
        job_manager: JobManager | None = None,
    ) -> None:
        self.paths = paths or get_paths(home)
        self.paths.ensure()
        self.config_manager = ConfigManager(self.paths)
        if config is not None:
            self.config_manager._config = config  # seeded (tests / programmatic use)

        self.bus = event_bus or get_event_bus()
        self._database = database
        self._job_manager = job_manager
        self._lock = threading.RLock()
        self._repos: dict[str, object] = {}
        self._services: dict[str, object] = {}
        #: Bumped whenever LLM/embedding settings change so caches can reset.
        self.llm_epoch = 0

    # -- configuration ---------------------------------------------------
    @property
    def config(self) -> Config:
        return self.config_manager.load()

    def reload_config(self, *, force: bool = True) -> Config:
        return self.config_manager.load(force=force)

    def update_config(self, patch: dict) -> Config:
        config = self.config_manager.update(patch)
        self.llm_epoch += 1
        self._services.pop("vectorstore", None)
        return config

    # -- storage ---------------------------------------------------------
    @property
    def db(self) -> Database:
        with self._lock:
            if self._database is None:
                self._database = Database(
                    self.paths.database, busy_timeout=self.config.app.sqlite_busy_timeout
                )
                self._database.initialize()
            return self._database

    # -- background ------------------------------------------------------
    @property
    def jobs(self) -> JobManager:
        if self._job_manager is None:
            self._job_manager = get_job_manager(self.config.app.max_workers)
        return self._job_manager

    # -- repositories ----------------------------------------------------
    def _repo(self, key: str, factory):
        with self._lock:
            if key not in self._repos:
                self._repos[key] = factory(self.db)
            return self._repos[key]

    @property
    def datasets(self):
        from minics.services.datasets import DatasetService

        with self._lock:
            if "datasets" not in self._services:
                self._services["datasets"] = DatasetService(self)
            return self._services["datasets"]

    @property
    def entries(self):
        from minics.services.entries import EntryService

        with self._lock:
            if "entries" not in self._services:
                self._services["entries"] = EntryService(self)
            return self._services["entries"]

    @property
    def collections(self):
        from minics.services.collections import CollectionService

        with self._lock:
            if "collections" not in self._services:
                self._services["collections"] = CollectionService(self)
            return self._services["collections"]

    @property
    def documents(self):
        from minics.services.documents import DocumentService

        with self._lock:
            if "documents" not in self._services:
                self._services["documents"] = DocumentService(self)
            return self._services["documents"]

    # -- retrieval -------------------------------------------------------
    @property
    def vectorstore(self):
        """Persistent Chroma collection (rebuilt when embedding settings change)."""
        from minics.rag.vectorstore import VectorStore

        with self._lock:
            cached = self._services.get("vectorstore")
            if cached is None or self._services.get("_vectorstore_epoch") != self.llm_epoch:
                if cached is not None:
                    try:
                        cached.close()
                    except Exception:  # noqa: BLE001 - best effort
                        pass
                cached = VectorStore(
                    self.paths.vectordb,
                    dimension=self.config.embedding.dimension or None,
                )
                self._services["vectorstore"] = cached
                self._services["_vectorstore_epoch"] = self.llm_epoch
            return cached

    @property
    def indexer(self):
        from minics.rag.indexer import DocumentIndexer

        with self._lock:
            if "indexer" not in self._services:
                self._services["indexer"] = DocumentIndexer(self)
            return self._services["indexer"]

    @property
    def graph(self):
        """Persistent Ladybug graph store."""
        from minics.rag.graph import GraphStore

        with self._lock:
            if "graph" not in self._services:
                self._services["graph"] = GraphStore(self.paths.graph_file)
            return self._services["graph"]

    @property
    def graph_indexer(self):
        from minics.rag.graph import GraphIndexer

        with self._lock:
            if "graph_indexer" not in self._services:
                self._services["graph_indexer"] = GraphIndexer(self)
            return self._services["graph_indexer"]

    @property
    def retriever(self):
        from minics.rag.retriever import HybridRetriever

        with self._lock:
            if "retriever" not in self._services:
                self._services["retriever"] = HybridRetriever(self)
            return self._services["retriever"]

    @property
    def authoring(self):
        from minics.services.authoring import AuthoringService

        with self._lock:
            if "authoring" not in self._services:
                self._services["authoring"] = AuthoringService(self)
            return self._services["authoring"]

    @property
    def chat(self):
        from minics.services.chat import ChatService

        with self._lock:
            if "chat" not in self._services:
                self._services["chat"] = ChatService(self)
            return self._services["chat"]

    # -- lifecycle -------------------------------------------------------
    def ensure_ready(self) -> None:
        """Touch the database so migrations run and the home is initialised."""
        _ = self.db

    @property
    def ready(self) -> bool:
        return self.config.is_ready()

    def close(self) -> None:
        for key in ("vectorstore", "graph"):
            resource = self._services.pop(key, None)
            closer = getattr(resource, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:  # noqa: BLE001 - best effort
                    pass
        if self._database is not None:
            self._database.close()
            self._database = None


_context: AppContext | None = None
_context_lock = threading.Lock()


def get_context(home: str | None = None, **kwargs) -> AppContext:
    """Return the process-wide :class:`AppContext` (created on first use)."""
    global _context
    if _context is None or home is not None or kwargs:
        with _context_lock:
            if _context is None or home is not None or kwargs:
                _context = AppContext(home, **kwargs)
    return _context


def set_context(context: AppContext | None) -> None:
    """Replace the global context (used by tests and alternate entry points)."""
    global _context
    with _context_lock:
        _context = context


def reset_context() -> None:
    if _context is not None:
        _context.close()
    set_context(None)
