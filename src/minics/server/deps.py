"""Request helpers: context access, JSON helpers and background job wrappers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flask import current_app, jsonify, request

from minics.core.db import DatabaseError
from minics.llm.client import LLMError
from minics.services.base import NotFoundError
from minics.services.context import AppContext

CTX_KEY = "MINICS_CONTEXT"


def get_ctx() -> AppContext:
    return current_app.config[CTX_KEY]


def json_body(default: dict[str, Any] | None = None) -> dict[str, Any]:
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return dict(default or {})


def ok(data: Any = None, **extra: Any):
    payload: dict[str, Any] = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return jsonify(payload)


def fail(message: str, code: int = 400, **extra: Any):
    payload: dict[str, Any] = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), code


def job_response(job) -> Any:
    """Return a job both as ``data`` (canonical) and top-level ``job``."""
    payload = job.to_dict()
    return jsonify({"ok": True, "data": payload, "job": payload})


def submit_job(
    name: str,
    fn: Callable[..., Any],
    *,
    source: str = "api",
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
):
    """Run ``fn(ctx_job, **kwargs)`` on the job manager and return the job."""
    ctx = get_ctx()

    def _run(job_ctx):
        return fn(job_ctx, **kwargs)

    return ctx.jobs.submit(name, _run, source=source, metadata=metadata)


def register_error_handlers(app) -> None:
    @app.errorhandler(NotFoundError)
    def _not_found(exc):  # noqa: ANN001
        return fail(str(exc), 404)

    @app.errorhandler(LLMError)
    def _llm_error(exc):  # noqa: ANN001
        return fail(str(exc), 502)

    @app.errorhandler(DatabaseError)
    def _db_error(exc):  # noqa: ANN001
        return fail(str(exc), 500)

    @app.errorhandler(ValueError)
    def _value_error(exc):  # noqa: ANN001
        return fail(str(exc), 400)

    @app.errorhandler(FileNotFoundError)
    def _file_error(exc):  # noqa: ANN001
        return fail(str(exc), 404)
