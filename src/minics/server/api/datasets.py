"""Dataset endpoints."""

from __future__ import annotations

from flask import Blueprint, request

from minics.server.deps import get_ctx, json_body, ok

bp = Blueprint("datasets", __name__, url_prefix="/api/datasets")


def _with_stats(ctx, dataset) -> dict:
    data = dataset.to_dict()
    data["stats"] = ctx.datasets.stats(int(dataset.id))
    return data


@bp.get("")
@bp.get("/")
def list_datasets():
    ctx = get_ctx()
    search = request.args.get("search")
    tag = request.args.get("tag")
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", type=int) or 0
    datasets = ctx.datasets.list(search=search, tag=tag, limit=limit, offset=offset)
    return ok(
        {
            "items": [_with_stats(ctx, d) for d in datasets],
            "total": ctx.datasets.count(search=search, tag=tag),
        }
    )


@bp.post("")
@bp.post("/")
def create_dataset():
    ctx = get_ctx()
    body = json_body()
    dataset = ctx.datasets.create(
        body.get("name", "Untitled dataset"),
        description=body.get("description", ""),
        tags=body.get("tags"),
        source=body.get("source", "manual"),
        metadata=body.get("metadata"),
        settings=body.get("settings"),
    )
    return ok(_with_stats(ctx, dataset)), 201


@bp.get("/<ref>")
def get_dataset(ref: str):
    ctx = get_ctx()
    return ok(_with_stats(ctx, ctx.datasets.get(ref)))


@bp.patch("/<ref>")
def update_dataset(ref: str):
    ctx = get_ctx()
    return ok(_with_stats(ctx, ctx.datasets.update(ref, json_body())))


@bp.delete("/<ref>")
def delete_dataset(ref: str):
    ctx = get_ctx()
    return ok({"deleted": ctx.datasets.delete(ref)})


@bp.get("/<ref>/stats")
def dataset_stats(ref: str):
    ctx = get_ctx()
    return ok(ctx.datasets.stats(ref))


@bp.get("/<ref>/entries")
def dataset_entries(ref: str):
    ctx = get_ctx()
    status = request.args.get("status")
    search = request.args.get("search")
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", type=int) or 0
    entries = ctx.entries.list(
        dataset=ref, status=status, search=search, limit=limit, offset=offset
    )
    return ok(
        {
            "items": [e.to_dict() for e in entries],
            "total": ctx.entries.count(dataset=ref, status=status, search=search),
        }
    )


