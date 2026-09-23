"""Retrieval and graph inspection endpoints."""

from __future__ import annotations

from flask import Blueprint, request

from minics.server.deps import get_ctx, job_response, json_body, ok, submit_job

bp = Blueprint("retrieval", __name__, url_prefix="/api")


@bp.post("retrieval/search")
def search():
    ctx = get_ctx()
    body = json_body()
    result = ctx.retriever.retrieve(
        body.get("query", ""),
        top_k=body.get("top_k"),
        use_rag=body.get("use_rag"),
        use_graph=body.get("use_graph"),
        candidates=body.get("candidates"),
        document_ids=body.get("document_ids"),
    )
    return ok(result.to_dict())


@bp.get("retrieval/status")
def status():
    ctx = get_ctx()
    available = False
    try:
        available = ctx.graph.is_available()
    except Exception:  # noqa: BLE001
        available = False
    return ok(
        {
            "vector": ctx.retriever.index_summary(),
            "graph_available": available,
            "graph": ctx.graph.stats() if available else {},
            "settings": ctx.config.retrieval.model_dump(),
        }
    )


@bp.get("graph/subgraph")
def subgraph():
    ctx = get_ctx()
    query = request.args.get("q", "")
    limit = request.args.get("limit", type=int) or 40
    if not ctx.graph.is_available():
        return ok({"nodes": [], "edges": [], "entities": [], "error": "Graph unavailable"})
    return ok(ctx.graph.subgraph(query.split(), limit=limit))


@bp.get("graph/entities")
def entities():
    ctx = get_ctx()
    query = request.args.get("q", "")
    limit = request.args.get("limit", type=int) or 50
    if not ctx.graph.is_available():
        return ok({"items": []})
    return ok({"items": ctx.graph.find_entities(query.split() or [query], limit=limit)})


@bp.post("graph/rebuild")
def rebuild():
    ctx = get_ctx()
    job = submit_job(
        "Rebuild graph",
        lambda job_ctx, **kw: _rebuild(ctx, job_ctx),
        source="graph",
    )
    return job_response(job), 202


def _rebuild(ctx, job_ctx):
    ctx.graph.clear()
    return ctx.graph_indexer.reindex_all(
        progress=lambda fraction, message: job_ctx.update(fraction, message)
    )



