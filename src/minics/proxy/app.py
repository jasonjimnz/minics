"""FastAPI proxy that exposes MiniCS retrieval-augmented chat as an
OpenAI-compatible API.

Request flow for ``POST /v1/chat/completions``:

    client ──► /v1/chat/completions
                 │ 1. extract the last user message as the query
                 │ 2. hybrid retrieval (vector + graph [+ rerank])  ◄─ MiniCS index
                 │ 3. inject the retrieved context as grounding
                 │ 4. forward to the configured LLM endpoint
                 ▼
              OpenAI-shaped response + ``minics`` metadata block

The ``minics`` metadata block (absent from upstream, added by the proxy)
contains the MiniCS version, the model that answered and everything needed to
trace the answer back to the source documents.

Grounding can be controlled per request with an optional top-level ``minics``
object in the request body::

    {
      "model": "...", "messages": [...],
      "minics": {"use_rag": true, "use_graph": true, "use_grounding": true,
                  "top_k": 5, "document_ids": [1, 2]}
    }
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

from minics import __version__
from minics.llm.client import LLMError, build_openai_client
from minics.proxy.schemas import (
    ChatCompletionRequest,
    MinicsOptions,
    ModelListResponse,
    ModelObject,
)
from minics.services.context import AppContext, get_context

LOGGER = logging.getLogger("minics.proxy")

#: Injected above the caller's messages when grounding is active.
GROUNDING_TEMPLATE = """Use the reference material below to answer.

- Cite sources inline as [n] matching the numbered references.
- If the material does not contain the answer, say so and answer from general knowledge.
- Never contradict the reference material.

References:
{context}
"""


def create_proxy_app(ctx: AppContext | None = None) -> FastAPI:
    """Build the proxy FastAPI application."""
    ctx = ctx or get_context()
    app = FastAPI(
        title="MiniCS Proxy",
        version=__version__,
        description=(
            "OpenAI-compatible endpoint backed by MiniCS hybrid retrieval "
            "(RAG + knowledge graph + optional rerank)."
        ),
    )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _last_user_text(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                content = message.get("content") or ""
                if isinstance(content, list):  # multimodal content parts
                    content = " ".join(
                        part.get("text", "") for part in content if isinstance(part, dict)
                    )
                return str(content).strip()
        return ""

    def _retrieve(query: str, options: MinicsOptions):
        """Run retrieval; returns ``(result, citations)`` — both may be empty."""
        if not query or not options.use_grounding:
            return None, []
        if not ctx.config.is_ready():
            return None, []
        if not (options.use_rag or options.use_graph):
            return None, []
        try:
            result = ctx.retriever.retrieve(
                query,
                top_k=options.top_k,
                use_rag=options.use_rag,
                use_graph=options.use_graph,
                document_ids=options.document_ids or None,
            )
        except Exception as exc:  # noqa: BLE001 - never fail the chat on retrieval
            LOGGER.warning("retrieval failed: %s", exc)
            return None, []
        return result, result.citations()

    def _metadata(result, options: MinicsOptions, model: str) -> dict[str, Any]:
        """Build the ``minics`` block attached to every response."""
        block: dict[str, Any] = {
            "version": __version__,
            "model": model,
            "grounded": bool(result is not None and result.chunks),
        }
        if result is None:
            block["retrieval"] = {"used": False}
            return block
        documents: dict[int, str] = {}
        for chunk in result.chunks:
            if chunk.document_id:
                documents.setdefault(chunk.document_id, chunk.document_title)
        block["retrieval"] = {
            "used": bool(result.chunks),
            "query": result.query,
            "used_rag": result.used_rag,
            "used_graph": result.used_graph,
            "rerank": bool(result.diagnostics.get("rerank")),
            "top_k": options.top_k,
            "chunks": len(result.chunks),
            "documents": [{"id": doc_id, "title": title} for doc_id, title in documents.items()],
            "citations": [c.model_dump() for c in result.citations()],
            "diagnostics": result.diagnostics,
        }
        return block

    def _grounded_messages(
        messages: list[dict[str, Any]], result, options: MinicsOptions
    ) -> list[dict[str, Any]]:
        if result is None or not result.chunks:
            return messages
        context = result.context_text(max_chars=options.max_context_chars)
        grounding = GROUNDING_TEMPLATE.format(context=context)
        forwarded = [dict(m) for m in messages]
        for message in forwarded:
            if message.get("role") == "system":
                message["content"] = f"{grounding}\n\n{message.get('content', '')}".strip()
                break
        else:
            forwarded.insert(0, {"role": "system", "content": grounding})
        return forwarded

    def _upstream_payload(request: ChatCompletionRequest, options: MinicsOptions) -> dict[str, Any]:
        payload = request.model_dump(exclude_none=True, exclude={"minics", "stream", "messages"})
        payload["model"] = payload.get("model") or ctx.config.llm.model
        return payload

    # ------------------------------------------------------------------
    # routes
    # ------------------------------------------------------------------
    @app.get("/health")
    def health() -> dict[str, Any]:
        config = ctx.config
        return {
            "status": "ok" if config.is_ready() else "degraded",
            "service": "minics-proxy",
            "version": __version__,
            "model": config.llm.model,
            "ready": config.is_ready(),
            "rerank": config.rerank_ready,
        }

    @app.get("/v1/models")
    def list_models() -> ModelListResponse:
        return ModelListResponse(
            data=[
                ModelObject(
                    id=ctx.config.llm.model or "minics",
                    owned_by="minics",
                )
            ]
        )

    @app.post("/v1/chat/completions")
    def chat_completions(request: ChatCompletionRequest):
        started = time.time()
        options = request.minics or MinicsOptions()
        messages = [m.model_dump(exclude_none=True) for m in request.messages]
        query = _last_user_text(messages)
        model = request.model or ctx.config.llm.model or "minics"

        # 1-2. retrieval happens first, before anything is sent upstream.
        result, _citations = _retrieve(query, options)
        metadata = _metadata(result, options, model)

        # 3. build the grounded prompt.
        forwarded = _grounded_messages(messages, result, options)

        # 4. call the configured LLM endpoint.
        try:
            client = build_openai_client(ctx.config)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(status_code=502, content={"error": {"message": str(exc)}})

        try:
            if request.stream:
                return StreamingResponse(
                    _stream_response(client, request, forwarded, metadata, model),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            response = client.chat.completions.create(
                **_upstream_payload(request, options), messages=forwarded
            )
            # NOTE: messages intentionally passed after the payload so the
            # grounded version always wins.
        except LLMError as exc:
            return JSONResponse(status_code=502, content={"error": {"message": str(exc)}})
        except Exception as exc:  # noqa: BLE001 - surface upstream errors as OpenAI errors
            return JSONResponse(
                status_code=502,
                content={"error": {"message": f"Upstream LLM request failed: {exc}"}},
            )

        body = response.model_dump(exclude_none=True)
        metadata["latency_ms"] = int((time.time() - started) * 1000)
        body["minics"] = metadata
        return JSONResponse(content=body)

    def _stream_response(client, request: ChatCompletionRequest, forwarded, metadata, model):
        """Yield SSE chunks; the first chunk carries the ``minics`` metadata."""
        try:
            payload = _upstream_payload(request, request.minics or MinicsOptions())
            stream = client.chat.completions.create(**payload, messages=forwarded, stream=True)
            first = True
            for chunk in stream:
                body = chunk.model_dump(exclude_none=True)
                if first:
                    body["minics"] = metadata
                    first = False
                yield f"data: {json.dumps(body, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:  # noqa: BLE001 - best effort mid-stream error
            LOGGER.exception("stream failed")
            error = {"error": {"message": f"Upstream stream failed: {exc}"}}
            yield f"data: {json.dumps(error)}\n\n"

    return app


def run_proxy(
    *,
    host: str = "127.0.0.1",
    port: int = 8766,
    home: str | None = None,
    log_level: str = "info",
) -> None:
    """Run the proxy with uvicorn (blocking — used by ``minics proxy``)."""
    import uvicorn

    ctx = get_context(home)
    app = create_proxy_app(ctx)
    uvicorn.run(app, host=host, port=port, log_level=log_level)
