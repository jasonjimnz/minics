"""Background job manager.

Long-running work (document ingestion, embeddings, LLM evaluation, ...) must not
block a web request.  :class:`JobManager` runs callables on a bounded thread
pool and reports progress through the :class:`~minics.core.events.EventBus`, so
the UI can show exactly what is happening.

Jobs are kept in memory with a small amount of history.  They are intentionally
cheap: a job is a handle, not a durable record.
"""

from __future__ import annotations

import enum
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from minics.core.events import EventBus, get_event_bus


class JobCancelled(RuntimeError):
    """Raised inside a job when cancellation has been requested."""


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in (JobStatus.SUCCESS, JobStatus.ERROR, JobStatus.CANCELLED)


@dataclass
class Job:
    name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source: str = "app"
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    future: Future[Any] | None = field(default=None, repr=False)

    @property
    def duration(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at if self.finished_at is not None else time.time()
        return end - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "status": self.status.value,
            "progress": round(self.progress, 4),
            "message": self.message,
            "error": self.error,
            "result": _jsonable(self.result),
            "metadata": self.metadata,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
        }


class JobContext:
    """Handle passed to job callables for progress and cancellation."""

    def __init__(self, job: Job, bus: EventBus, manager: JobManager) -> None:
        self.job = job
        self.bus = bus
        self.manager = manager

    # -- progress --------------------------------------------------------
    def update(self, progress: float | None = None, message: str | None = None) -> None:
        if self.job.cancel_event.is_set():
            raise JobCancelled("Job cancelled")
        if progress is not None:
            self.job.progress = max(0.0, min(1.0, float(progress)))
        if message is not None:
            self.job.message = message
        self.bus.publish(
            type="job.progress",
            level="info",
            job_id=self.job.id,
            source=self.job.source,
            progress=self.job.progress,
            message=self.job.message or self.job.name,
        )

    def step(self, index: int, total: int, message: str | None = None) -> None:
        total = max(1, total)
        self.update(progress=index / total, message=message)

    def log(self, message: str, level: str = "info", **data: Any) -> None:
        self.bus.publish(
            type="job.log",
            level=level,
            message=message,
            job_id=self.job.id,
            source=self.job.source,
            data=data,
        )

    # -- cancellation ----------------------------------------------------
    @property
    def cancelled(self) -> bool:
        return self.job.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled("Job cancelled")


def _jsonable(value: Any) -> Any:
    """Best-effort conversion of a job result into JSON-friendly data."""
    from pydantic import BaseModel

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    try:
        import json

        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


class JobManager:
    """Runs callables on a thread pool with progress reporting."""

    def __init__(self, *, bus: EventBus | None = None, max_workers: int = 4) -> None:
        self.bus = bus or get_event_bus()
        self.max_workers = max(1, int(max_workers))
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="minics-job"
        )
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._max_history = 200

    # -- submission ------------------------------------------------------
    def submit(
        self,
        name: str,
        fn: Callable[[JobContext], Any],
        *,
        source: str = "app",
        metadata: dict[str, Any] | None = None,
    ) -> Job:
        job = Job(name=name, source=source, metadata=dict(metadata or {}))
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._trim()
        self.bus.publish(
            type="job.queued",
            level="info",
            job_id=job.id,
            source=source,
            message=name,
            data={"metadata": job.metadata},
        )
        job.future = self._executor.submit(self._run, job, fn)
        return job

    def run_background(
        self,
        name: str,
        fn: Callable[[JobContext], Any],
        *,
        source: str = "app",
        metadata: dict[str, Any] | None = None,
    ) -> Job:
        return self.submit(name, fn, source=source, metadata=metadata)

    def call(
        self,
        name: str,
        fn: Callable[[JobContext], Any],
        *,
        source: str = "app",
        metadata: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Job:
        """Submit and wait for completion (useful for CLI / tests)."""
        job = self.submit(name, fn, source=source, metadata=metadata)
        if job.future is not None:
            job.future.result(timeout=timeout)
        return job

    # -- introspection ---------------------------------------------------
    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def jobs(self) -> list[Job]:
        with self._lock:
            return [self._jobs[jid] for jid in self._order if jid in self._jobs]

    def active(self) -> list[Job]:
        return [j for j in self.jobs() if not j.status.terminal]

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.status.terminal:
            return False
        job.cancel_event.set()
        self.bus.publish(
            type="job.cancelling",
            level="warning",
            job_id=job.id,
            source=job.source,
            message=f"Cancelling {job.name}",
        )
        if job.status is JobStatus.QUEUED and job.future is not None:
            job.future.cancel()
        return True

    # -- internals -------------------------------------------------------
    def _run(self, job: Job, fn: Callable[[JobContext], Any]) -> None:
        if job.cancel_event.is_set():
            self._finish(job, JobStatus.CANCELLED, message="Cancelled before start")
            return
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        self.bus.publish(
            type="job.started",
            level="info",
            job_id=job.id,
            source=job.source,
            message=job.name,
        )
        ctx = JobContext(job, self.bus, self)
        try:
            result = fn(ctx)
        except JobCancelled:
            self._finish(job, JobStatus.CANCELLED, message="Cancelled")
        except BaseException as exc:  # noqa: BLE001 - reported to the user
            job.error = f"{type(exc).__name__}: {exc}"
            self.bus.publish(
                type="job.error",
                level="error",
                job_id=job.id,
                source=job.source,
                message=job.error,
                data={"traceback": traceback.format_exc()},
            )
            self._finish(job, JobStatus.ERROR, message=job.error)
        else:
            job.result = result
            self._finish(job, JobStatus.SUCCESS, message=job.message or f"{job.name} finished")

    def _finish(self, job: Job, status: JobStatus, *, message: str) -> None:
        job.status = status
        job.finished_at = time.time()
        if status is JobStatus.SUCCESS:
            job.progress = 1.0
        job.message = message
        self.bus.publish(
            type="job.finished",
            level="error" if status is JobStatus.ERROR else "success",
            job_id=job.id,
            source=job.source,
            progress=job.progress,
            message=message,
            data={"status": status.value},
        )

    def _trim(self) -> None:
        if len(self._order) <= self._max_history:
            return
        for jid in self._order[: -self._max_history]:
            job = self._jobs.get(jid)
            if job is not None and job.status.terminal:
                self._jobs.pop(jid, None)
        self._order = self._order[-self._max_history :]

    def shutdown(self, *, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)


_manager: JobManager | None = None
_manager_lock = threading.Lock()


def get_job_manager(max_workers: int | None = None) -> JobManager:
    """Return the process-wide job manager (created on first use)."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = JobManager(max_workers=max_workers or 4)
    return _manager


def reset_job_manager() -> None:
    """Tear down the global manager (used by tests)."""
    global _manager
    if _manager is not None:
        _manager.shutdown(wait=False)
        _manager = None
