"""Entry (ChatML) endpoints, including LLM authoring actions."""

from __future__ import annotations

from flask import Blueprint, request

from minics.server.deps import get_ctx, job_response, json_body, ok, submit_job

bp = Blueprint("entries", __name__, url_prefix="/api/entries")


@bp.get("")
@bp.get("/")
def list_entries():
    ctx = get_ctx()
    dataset = request.args.get("dataset")
    status = request.args.get("status")
    search = request.args.get("search")
    tag = request.args.get("tag")
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", type=int) or 0
    entries = ctx.entries.list(
        dataset=dataset, status=status, search=search, tag=tag, limit=limit, offset=offset
    )
    return ok(
        {
            "items": [e.to_dict() for e in entries],
            "total": ctx.entries.count(dataset=dataset, status=status, search=search, tag=tag),
        }
    )


@bp.post("")
@bp.post("/")
def create_entry():
    ctx = get_ctx()
    body = json_body()
    entry = ctx.entries.create(
        body.get("dataset"),
        messages=body.get("messages"),
        system=body.get("system"),
        user=body.get("user"),
        assistant=body.get("assistant"),
        tags=body.get("tags"),
        status=body.get("status", "draft"),
        notes=body.get("notes", ""),
        source=body.get("source", "manual"),
        metadata=body.get("metadata"),
    )
    return ok(entry.to_dict()), 201


@bp.post("/bulk")
def bulk_create():
    ctx = get_ctx()
    body = json_body()
    created = ctx.entries.bulk_create(
        body.get("entries", []),
        dataset=body.get("dataset"),
        status=body.get("status", "draft"),
    )
    return ok({"created": len(created), "items": [e.to_dict() for e in created]}), 201


@bp.get("/<ref>")
def get_entry(ref: str):
    ctx = get_ctx()
    entry = ctx.entries.get(ref)
    return ok(
        {
            "entry": entry.to_dict(),
            "validation": ctx.entries.validate(entry.id),
            "collections": [c.public_id for c in ctx.collections.collections_for_entry(entry.id)],
        }
    )


@bp.patch("/<ref>")
def update_entry(ref: str):
    ctx = get_ctx()
    body = json_body()
    reason = body.pop("reason", "edited")
    entry = ctx.entries.update(ref, body, reason=reason)
    return ok(entry.to_dict())


@bp.delete("/<ref>")
def delete_entry(ref: str):
    ctx = get_ctx()
    return ok({"deleted": ctx.entries.delete(ref)})


@bp.get("/<ref>/versions")
def versions(ref: str):
    ctx = get_ctx()
    return ok({"items": ctx.entries.versions(ref)})


@bp.get("/<ref>/validate")
def validate(ref: str):
    ctx = get_ctx()
    return ok(ctx.entries.validate(ref))


@bp.post("/<ref>/status")
def set_status(ref: str):
    ctx = get_ctx()
    entry = ctx.entries.set_status(ref, json_body().get("status", "draft"))
    return ok(entry.to_dict())


@bp.post("/<ref>/tags")
def add_tags(ref: str):
    ctx = get_ctx()
    entry = ctx.entries.add_tags(ref, json_body().get("tags", []))
    return ok(entry.to_dict())


# -- LLM authoring (background) --------------------------------------------
@bp.post("/<ref>/evaluate")
def evaluate(ref: str):
    ctx = get_ctx()
    body = json_body()
    job = submit_job(
        f"Evaluate entry {ref}",
        lambda job_ctx, **kw: ctx.authoring.evaluate_entry(**kw).model_dump(),
        source="authoring",
        metadata={"entry": ref},
        ref=ref,
        use_grounding=bool(body.get("use_grounding")),
        model=body.get("model"),
    )
    return job_response(job), 202


@bp.post("/<ref>/enhance")
def enhance(ref: str):
    ctx = get_ctx()
    body = json_body()
    job = submit_job(
        f"Enhance entry {ref}",
        lambda job_ctx, **kw: ctx.authoring.enhance_entry_fields(**kw),
        source="authoring",
        metadata={"entry": ref},
        ref=ref,
        fields=body.get("fields") or ["assistant"],
        instruction=body.get("instruction", ""),
        use_grounding=bool(body.get("use_grounding")),
        persist=bool(body.get("persist")),
        model=body.get("model"),
    )
    return job_response(job), 202


@bp.post("/<ref>/suggest-tags")
def suggest_tags(ref: str):
    ctx = get_ctx()
    body = json_body()
    job = submit_job(
        f"Suggest tags for {ref}",
        lambda job_ctx, **kw: ctx.authoring.suggest_tags(**kw),
        source="authoring",
        metadata={"entry": ref},
        ref=ref,
        max_tags=int(body.get("max_tags", 6)),
        add=bool(body.get("add")),
        model=body.get("model"),
    )
    return job_response(job), 202


@bp.post("/generate")
def generate():
    ctx = get_ctx()
    body = json_body()
    job = submit_job(
        f"Generate entry: {body.get('topic', '')[:40]}",
        lambda job_ctx, **kw: _generate(ctx, **kw),
        source="authoring",
        metadata={"topic": body.get("topic", "")},
        body=body,
    )
    return job_response(job), 202


def _generate(ctx, *, body: dict):
    result = ctx.authoring.generate_entry(
        topic=body.get("topic", ""),
        dataset=body.get("dataset"),
        system_hint=body.get("system_hint", ""),
        use_grounding=bool(body.get("use_grounding", True)),
        persist=True,
        tags=body.get("tags"),
        model=body.get("model"),
    )
    return result.to_dict() if hasattr(result, "to_dict") else result


# -- grounding preview -----------------------------------------------------
@bp.post("/<ref>/grounding")
def grounding(ref: str):
    ctx = get_ctx()
    entry = ctx.entries.get(ref)
    body = json_body()
    query = body.get("query") or " ".join(p for p in (entry.system, entry.user) if p)
    result = ctx.retriever.retrieve(
        query,
        use_rag=body.get("use_rag"),
        use_graph=body.get("use_graph"),
        top_k=body.get("top_k"),
    )
    return ok(result.to_dict())


