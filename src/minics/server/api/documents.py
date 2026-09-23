"""Document endpoints: import, markdown editing and indexing."""

from __future__ import annotations

from flask import Blueprint, Response, request

from minics.documents.convert import SUPPORTED_EXTENSIONS
from minics.server.deps import fail, get_ctx, job_response, json_body, ok, submit_job

bp = Blueprint("documents", __name__, url_prefix="/api/documents")


@bp.get("/supported")
def supported():
    kinds = sorted(set(SUPPORTED_EXTENSIONS.values()))
    return ok({"extensions": sorted(SUPPORTED_EXTENSIONS), "kinds": kinds})


@bp.get("")
@bp.get("/")
def list_documents():
    ctx = get_ctx()
    documents = ctx.documents.list(
        search=request.args.get("search"),
        status=request.args.get("status"),
        limit=request.args.get("limit", type=int),
        offset=request.args.get("offset", type=int) or 0,
    )
    return ok({"items": [d.to_dict() for d in documents], "stats": ctx.documents.stats()})


@bp.post("")
@bp.post("/")
def create_document():
    """Upload files and/or a raw markdown note.

    Returns a job because conversion and indexing are both slow.
    """
    ctx = get_ctx()
    files = request.files.getlist("files") or request.files.getlist("file")
    tags = request.form.getlist("tags") or None
    index = request.form.get("index", "true").lower() != "false"

    if files:
        payload = [(f.filename, f.read()) for f in files if f.filename]
        if not payload:
            return fail("No usable files in the request.")
        job = submit_job(
            f"Import {len(payload)} document(s)",
            lambda job_ctx, **kw: _import_files(ctx, job_ctx, **kw),
            source="documents",
            files=payload,
            tags=tags,
            index=index,
        )
        return job_response(job), 202

    body = json_body()
    markdown = body.get("markdown")
    if not markdown:
        return fail("Provide files or a 'markdown' field.")
    document = ctx.documents.add_text(
        markdown,
        title=body.get("title", "Note"),
        tags=body.get("tags"),
        source=body.get("source", "manual"),
    )
    job = _submit_index(ctx, document, index=index)
    return ok({"document": document.to_dict(), "job": job.to_dict() if job else None}), 202


@bp.get("/<ref>")
def get_document(ref: str):
    ctx = get_ctx()
    document = ctx.documents.get(ref)
    payload = document.to_dict()
    payload["markdown"] = ctx.documents.read_markdown(document.id)
    payload["chunks"] = [
        c.to_dict() for c in ctx.indexer.chunks.list_for_document(int(document.id))
    ]
    return ok(payload)


@bp.delete("/<ref>")
def delete_document(ref: str):
    ctx = get_ctx()
    try:
        ctx.indexer.remove_document(ref)
    except Exception:  # noqa: BLE001 - index may not exist yet
        pass
    try:
        if ctx.graph.is_available():
            ctx.graph_indexer.remove_document(ref)
    except Exception:  # noqa: BLE001 - graph may not exist yet
        pass
    return ok({"deleted": ctx.documents.delete(ref)})


@bp.get("/<ref>/markdown")
def get_markdown(ref: str):
    ctx = get_ctx()
    document = ctx.documents.get(ref)
    return Response(ctx.documents.read_markdown(document.id), mimetype="text/markdown")


@bp.put("/<ref>/markdown")
def put_markdown(ref: str):
    ctx = get_ctx()
    body = json_body()
    document = ctx.documents.write_markdown(ref, body.get("markdown", ""))
    job = _submit_index(ctx, document, index=bool(body.get("reindex", False)))
    return ok({"document": document.to_dict(), "job": job.to_dict() if job else None})


@bp.post("/<ref>/index")
def index_document(ref: str):
    ctx = get_ctx()
    document = ctx.documents.get(ref)
    job = _submit_index(ctx, document, index=True)
    return job_response(job), 202


@bp.post("/<ref>/clean")
def clean_document(ref: str):
    ctx = get_ctx()
    job = submit_job(
        f"Clean markdown for {ref}",
        lambda job_ctx, **kw: ctx.authoring.clean_document(**kw),
        source="documents",
        metadata={"document": ref},
        ref=ref,
        model=json_body().get("model"),
    )
    return job_response(job), 202


@bp.post("/<ref>/enrich-graph")
def enrich_graph(ref: str):
    ctx = get_ctx()
    body = json_body()
    job = submit_job(
        f"Enrich graph for {ref}",
        lambda job_ctx, **kw: ctx.authoring.enrich_graph(**kw),
        source="documents",
        metadata={"document": ref},
        ref=ref,
        max_entities=int(body.get("max_entities", 12)),
        model=body.get("model"),
    )
    return job_response(job), 202


@bp.post("/reindex")
def reindex_all():
    ctx = get_ctx()
    job = submit_job(
        "Reindex all documents",
        lambda job_ctx, **kw: _reindex_all(ctx, job_ctx, **kw),
        source="documents",
        graph=bool(json_body().get("graph", True)),
    )
    return job_response(job), 202


# -- job bodies ------------------------------------------------------------
def _submit_index(ctx, document, *, index: bool):
    if not index:
        return None
    return submit_job(
        f"Index '{document.title}'",
        lambda job_ctx, **kw: _index_document(ctx, job_ctx, **kw),
        source="documents",
        metadata={"document": document.public_id},
        ref=document.id,
        graph=True,
    )


def _index_document(ctx, job_ctx, *, ref, graph=True):
    job_ctx.update(0.05, "Splitting and embedding")
    result = ctx.indexer.index_document(
        ref,
        progress=lambda fraction, message: job_ctx.update(0.05 + 0.75 * fraction, message),
        job_ctx=job_ctx,
    )
    if graph:
        try:
            if ctx.graph.is_available():
                job_ctx.update(0.85, "Updating graph")
                result["graph"] = ctx.graph_indexer.index_document(ref, job_ctx=job_ctx)
        except Exception as exc:  # noqa: BLE001 - graph is optional
            job_ctx.log(f"Graph indexing failed: {exc}", level="warning")
    job_ctx.update(1.0, "Indexed")
    return result


def _import_files(ctx, job_ctx, *, files, tags=None, index=True):
    created: list[dict] = []
    total = max(1, len(files))
    for position, (name, data) in enumerate(files, start=1):
        job_ctx.check_cancelled()
        base = (position - 1) / total
        span = 1 / total
        job_ctx.update(base, f"Importing {name}")

        def _progress(fraction, message, base=base, span=span, name=name):
            job_ctx.update(base + span * 0.4 * fraction, f"{name}: {message}")

        document = ctx.documents.import_bytes(
            data, filename=name, tags=tags, progress=_progress
        )
        if index:
            try:
                _index_document(ctx, job_ctx, ref=document.id, graph=True)
            except Exception as exc:  # noqa: BLE001 - keep importing the rest
                job_ctx.log(f"Indexing failed for {document.title}: {exc}", level="warning")
        created.append(document.to_dict())
    job_ctx.update(1.0, f"Imported {len(created)} document(s)")
    return {"documents": created}


def _reindex_all(ctx, job_ctx, *, graph=True):
    vector_result = ctx.indexer.reindex_all(
        progress=lambda fraction, message: job_ctx.update(0.6 * fraction, message)
    )
    graph_result = {}
    if graph and ctx.graph.is_available():
        graph_result = ctx.graph_indexer.reindex_all(
            progress=lambda fraction, message: job_ctx.update(0.6 + 0.4 * fraction, message)
        )
    return {"vector": vector_result, "graph": graph_result}


