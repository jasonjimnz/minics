"""Concurrency-safe SQLite access.

SQLite gives us WAL (many concurrent readers + one writer) but *not* parallel
writers, and a shared connection cannot be handed to arbitrary threads.  MiniCS
therefore funnels **all** writes through a single dedicated writer thread and
lets reads use short-lived connections.

    db = Database(paths.database)
    db.initialize()

    rows = db.query("SELECT * FROM entries WHERE dataset_id = ?", (1,))
    new_id = db.insert("INSERT INTO entries (dataset_id, ...) VALUES (?, ...)", (...))

Writes submitted from any thread are serialised; ``db.busy_timeout`` protects the
rare case of an external process holding the lock.
"""

from __future__ import annotations

import atexit
import queue
import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


class DatabaseError(RuntimeError):
    """Raised for MiniCS-level database failures."""


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...] = field(default_factory=tuple)


def _core_migrations() -> list[Migration]:
    from minics.core.schema import MIGRATIONS

    return list(MIGRATIONS)


# ---------------------------------------------------------------------------
# Writer thread
# ---------------------------------------------------------------------------
class _WriterThread(threading.Thread):
    """Owns the single writable connection and executes jobs in order.

    The connection is created *inside* :meth:`run` so that it lives entirely on
    this thread (``sqlite3`` enforces same-thread usage).
    """

    def __init__(self, factory: Callable[[], sqlite3.Connection]) -> None:
        super().__init__(name="minics-sqlite-writer", daemon=True)
        self._factory = factory
        self.connection: sqlite3.Connection | None = None
        self._jobs: queue.Queue[tuple[Callable[[sqlite3.Connection], Any], Any] | None] = (
            queue.Queue()
        )

    def submit(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        future: _Future[T] = _Future()
        self._jobs.put((fn, future))
        return future.result()

    def stop(self) -> None:
        self._jobs.put(None)

    def run(self) -> None:  # pragma: no cover - thread body
        connection = self._factory()
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        self.connection = connection
        try:
            while True:
                item = self._jobs.get()
                if item is None:
                    break
                fn, future = item
                if not future.claim():
                    continue
                try:
                    result = fn(connection)
                    connection.commit()
                    future.set_result(result)
                except BaseException as exc:  # noqa: BLE001 - propagate faithfully
                    connection.rollback()
                    future.set_exception(exc)
        finally:
            self.connection = None
            connection.close()


class _Future:
    """Minimal future so we do not pay for a thread pool just to block."""

    __slots__ = ("_event", "_result", "_exception", "_claimed")

    def __init__(self) -> None:
        self._event = threading.Event()
        self._result: Any = None
        self._exception: BaseException | None = None
        self._claimed = False

    def claim(self) -> bool:
        if self._claimed:
            return False
        self._claimed = True
        return True

    def set_result(self, value: Any) -> None:
        self._result = value
        self._event.set()

    def set_exception(self, exc: BaseException) -> None:
        self._exception = exc
        self._event.set()

    def result(self, timeout: float | None = None) -> Any:
        if not self._event.wait(timeout):
            raise DatabaseError("Timed out waiting for the SQLite writer.")
        if self._exception is not None:
            raise self._exception
        return self._result


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
class Database:
    """Thin, thread-safe wrapper around a SQLite file."""

    def __init__(self, path: str | Path, *, busy_timeout: float = 5.0) -> None:
        self.path = Path(path)
        self.busy_timeout = busy_timeout
        self._writer: _WriterThread | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._local = threading.local()
        atexit.register(self.close)

    # -- lifecycle -------------------------------------------------------
    def connect(
        self, *, readonly: bool = False, timeout: float | None = None
    ) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if readonly and self.path.exists():
            uri = f"file:{self.path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=timeout or self.busy_timeout)
        else:
            conn = sqlite3.connect(str(self.path), timeout=timeout or self.busy_timeout)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int((timeout or self.busy_timeout) * 1000)}")
        return conn

    def _ensure_writer(self) -> _WriterThread:
        with self._lock:
            if self._writer is None:
                if self._closed:
                    raise DatabaseError("Database is closed.")
                self._writer = _WriterThread(self.connect)
                self._writer.start()
            return self._writer

    def initialize(self) -> None:
        """Open the writer and apply any pending migrations."""
        self._ensure_writer()
        self.migrate()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            writer, self._writer = self._writer, None
        if writer is not None:
            writer.stop()
            writer.join(timeout=5)
        local = getattr(self._local, "conn", None)
        if local is not None:
            local.close()
            self._local.conn = None

    def __enter__(self) -> Database:
        self.initialize()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- migrations ------------------------------------------------------
    @property
    def schema_version(self) -> int:
        try:
            row = self.query_one(
                "SELECT value FROM meta WHERE key = 'schema_version'", ()
            )
        except sqlite3.Error:
            return 0
        return int(row["value"]) if row else 0

    def migrate(self) -> int:
        def _apply(conn: sqlite3.Connection) -> int:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            current = int(row["value"]) if row else 0
            for migration in sorted(_core_migrations(), key=lambda m: m.version):
                if migration.version <= current:
                    continue
                for statement in migration.statements:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(migration.version),),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO schema_log (version, name) VALUES (?, ?)",
                    (migration.version, migration.name),
                )
                current = migration.version
            return current

        return self.run_write(_apply)

    # -- reads -----------------------------------------------------------
    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        """A short-lived read connection (safe to use concurrently)."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self.connect(readonly=True)
            self._local.conn = conn
        yield conn

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self.reader() as conn:
            return list(conn.execute(sql, tuple(params)).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self.reader() as conn:
            return conn.execute(sql, tuple(params)).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return default
        return row[0]

    # -- writes ----------------------------------------------------------
    def run_write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run ``fn(connection)`` on the writer thread and commit."""
        return self._ensure_writer().submit(fn)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Execute a write statement, returning ``lastrowid``."""

        def _run(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(sql, tuple(params))
            return int(cursor.lastrowid or 0)

        return self.run_write(_run)

    def execute_many(self, sql: str, rows: Iterable[Sequence[Any]]) -> int:
        def _run(conn: sqlite3.Connection) -> int:
            cursor = conn.executemany(sql, [tuple(r) for r in rows])
            return int(cursor.rowcount)

        return self.run_write(_run)

    def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        return self.execute(sql, params)

    def update(self, sql: str, params: Sequence[Any] = ()) -> int:
        def _run(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(sql, tuple(params))
            return int(cursor.rowcount)

        return self.run_write(_run)

    def transaction(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run a multi-statement function atomically on the writer thread."""

        def _run(conn: sqlite3.Connection) -> T:
            return fn(conn)

        return self.run_write(_run)

    # -- small key/value state ------------------------------------------
    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value FROM app_state WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO app_state (key, value, updated_at) "
            "VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, value),
        )


def open_database(paths: Any = None) -> Database:
    """Convenience constructor from a :class:`MinicsPaths` (or default)."""
    from minics.core.config import get_config_manager
    from minics.core.paths import get_paths

    resolved = paths or get_paths()
    config = get_config_manager(resolved).load()
    db = Database(resolved.database, busy_timeout=config.app.sqlite_busy_timeout)
    return db
