"""System endpoints: health, config, setup and dashboard overview."""

from __future__ import annotations

from flask import Blueprint, request

from minics import __version__
from minics.core.config import SECRET_MASK
from minics.llm.client import (
    LLMError,
    list_models,
    probe_embedding_dimension,
    split_models,
    test_connection,
)
from minics.server.deps import fail, get_ctx, json_body, ok

bp = Blueprint("system", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    ctx = get_ctx()
    return ok(
        {
            "version": __version__,
            "home": str(ctx.paths.root),
            "ready": ctx.ready,
            "setup_complete": ctx.config.setup_complete,
            "missing": ctx.config.missing_requirements(),
        }
    )


@bp.get("/config")
def get_config():
    ctx = get_ctx()
    return ok(ctx.config.public_dict())


@bp.put("/config")
def put_config():
    ctx = get_ctx()
    patch = json_body()
    config = ctx.update_config(patch)
    return ok(config.public_dict())


@bp.post("/config/setup")
def setup():
    """Validate the endpoint, persist settings and flag setup complete."""
    ctx = get_ctx()
    patch = json_body()
    if patch:
        ctx.update_config(patch)
    report = test_connection(ctx.config)
    if report["ok"]:
        ctx.config_manager.mark_setup_complete()
    else:
        ctx.reload_config()
    return ok({"report": report, "config": ctx.config.public_dict()})


@bp.post("/config/test")
def test():
    ctx = get_ctx()
    patch = json_body()
    if patch:
        ctx.update_config(patch)
    return ok(test_connection(ctx.config))


@bp.get("/config/models")
def models():
    ctx = get_ctx()
    kind = request.args.get("kind", "chat")
    if kind == "embedding":
        default_url = ctx.config.embedding_base_url
        default_key = ctx.config.embedding_api_key
    else:
        default_url = ctx.config.llm.base_url
        default_key = ctx.config.llm.api_key

    base_url = request.args.get("base_url") or default_url
    api_key = request.args.get("api_key") or default_key
    if api_key == SECRET_MASK:
        api_key = default_key
    try:
        found = split_models(list_models(base_url=base_url, api_key=api_key))
    except LLMError as exc:
        return fail(str(exc), 502, chat=[], embedding=[], base_url=base_url)
    return ok({**found, "base_url": base_url})


@bp.post("/config/embedding-dimension")
def embedding_dimension():
    ctx = get_ctx()
    patch = json_body()
    if patch:
        ctx.update_config(patch)
    try:
        dimension = probe_embedding_dimension(config=ctx.config)
    except LLMError as exc:
        return fail(str(exc), 502)
    ctx.update_config({"embedding": {"dimension": dimension}})
    return ok({"dimension": dimension})


@bp.get("/overview")
def overview():
    ctx = get_ctx()
    datasets = ctx.datasets.count()
    entries = ctx.entries.count()
    approved = ctx.entries.count(status="approved")
    documents = ctx.documents.stats()
    graph_stats = {}
    try:
        if ctx.graph.is_available():
            graph_stats = ctx.graph.stats()
    except Exception:  # noqa: BLE001 - graph is optional
        graph_stats = {}
    return ok(
        {
            "datasets": datasets,
            "entries": entries,
            "approved": approved,
            "drafts": ctx.entries.count(status="draft"),
            "in_review": ctx.entries.count(status="in_review"),
            "documents": documents,
            "graph": graph_stats,
            "chunks": ctx.retriever.index_summary(),
            "ready": ctx.ready,
        }
    )


