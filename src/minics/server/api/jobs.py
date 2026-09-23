"""Job introspection and the global event stream."""

from __future__ import annotations

from flask import Blueprint, request

from minics.server.deps import fail, get_ctx, ok
from minics.server.sse import sse_response

bp = Blueprint("jobs", __name__, url_prefix="/api")


@bp.get("jobs")
def list_jobs():
    ctx = get_ctx()
    jobs = ctx.jobs.jobs()
    return ok({"items": [job.to_dict() for job in jobs], "active": len(ctx.jobs.active())})


@bp.get("jobs/<job_id>")
def get_job(job_id: str):
    ctx = get_ctx()
    job = ctx.jobs.get(job_id)
    if job is None:
        return fail(f"Job '{job_id}' not found", 404)
    return ok(job.to_dict())


@bp.post("jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    ctx = get_ctx()
    return ok({"cancelled": ctx.jobs.cancel(job_id)})


@bp.post("jobs/cancel-all")
def cancel_all():
    ctx = get_ctx()
    cancelled = [job.id for job in ctx.jobs.active() if ctx.jobs.cancel(job.id)]
    return ok({"cancelled": cancelled})


@bp.get("events")
def events():
    ctx = get_ctx()
    after_id = request.args.get("after", type=int) or 0
    job_id = request.args.get("job")
    stream = ctx.bus.stream(after_id=after_id)

    def filtered():
        for event in stream:
            if event is None:
                yield None
                continue
            if job_id and event.job_id != job_id:
                continue
            yield event.to_dict()

    return sse_response(filtered())


@bp.get("events/history")
def event_history():
    ctx = get_ctx()
    after_id = request.args.get("after", type=int) or 0
    limit = request.args.get("limit", type=int) or 100
    return ok({"items": [e.to_dict() for e in ctx.bus.history(limit=limit, after_id=after_id)]})



