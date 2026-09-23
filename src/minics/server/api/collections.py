"""Collection endpoints, including export."""

from __future__ import annotations

from flask import Blueprint, Response, request

from minics.server.deps import get_ctx, json_body, ok
from minics.services.export import FORMATS

bp = Blueprint("collections", __name__, url_prefix="/api/collections")

MIME = {
    "chatml": "application/json",
    "jsonl": "application/x-ndjson",
    "alpaca": "application/json",
    "sharegpt": "application/json",
    "markdown": "text/markdown",
}
SUFFIX = {
    "chatml": "json",
    "jsonl": "jsonl",
    "alpaca": "json",
    "sharegpt": "json",
    "markdown": "md",
}


@bp.get("")
@bp.get("/")
def list_collections():
    ctx = get_ctx()
    search = request.args.get("search")
    dataset = request.args.get("dataset")
    collections = ctx.collections.list(search=search, dataset=dataset)
    return ok(
        {
            "items": [c.to_dict() for c in collections],
            "total": len(collections),
            "formats": list(FORMATS),
        }
    )


@bp.post("")
@bp.post("/")
def create_collection():
    ctx = get_ctx()
    body = json_body()
    collection = ctx.collections.create(
        body.get("name", "Untitled collection"),
        description=body.get("description", ""),
        dataset=body.get("dataset"),
        tags=body.get("tags"),
        entry_ids=body.get("entry_ids"),
        metadata=body.get("metadata"),
    )
    return ok(collection.to_dict()), 201


@bp.get("/<ref>")
def get_collection(ref: str):
    ctx = get_ctx()
    collection = ctx.collections.get(ref)
    payload = collection.to_dict()
    payload["stats"] = ctx.collections.stats(ref)
    payload["entries"] = [e.to_dict() for e in ctx.collections.entries_for(ref)]
    return ok(payload)


@bp.patch("/<ref>")
def update_collection(ref: str):
    ctx = get_ctx()
    return ok(ctx.collections.update(ref, json_body()).to_dict())


@bp.delete("/<ref>")
def delete_collection(ref: str):
    ctx = get_ctx()
    return ok({"deleted": ctx.collections.delete(ref)})


@bp.post("/<ref>/entries")
def add_entries(ref: str):
    ctx = get_ctx()
    collection = ctx.collections.add_entries(ref, json_body().get("entries", []))
    return ok(collection.to_dict())


@bp.put("/<ref>/entries")
def set_entries(ref: str):
    ctx = get_ctx()
    collection = ctx.collections.set_entries(ref, json_body().get("entries", []))
    return ok(collection.to_dict())


@bp.delete("/<ref>/entries")
def remove_entries(ref: str):
    ctx = get_ctx()
    collection = ctx.collections.remove_entries(ref, json_body().get("entries", []))
    return ok(collection.to_dict())


@bp.get("/<ref>/export")
def export(ref: str):
    ctx = get_ctx()
    fmt = request.args.get("format", "chatml")
    if fmt not in FORMATS:
        return ok({"error": f"Unsupported format '{fmt}'"}), 400
    content = ctx.collections.export(
        ref,
        fmt=fmt,
        include_metadata=request.args.get("include_metadata") == "true",
        only_approved=request.args.get("only_approved") == "true",
    )
    collection = ctx.collections.get(ref)
    filename = f"{collection.slug or 'collection'}.{SUFFIX[fmt]}"
    return Response(
        content,
        mimetype=MIME[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


