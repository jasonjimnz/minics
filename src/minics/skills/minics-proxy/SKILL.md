---
name: minics-proxy
description: Run the MiniCS OpenAI-compatible RAG proxy — `minics proxy` launches a FastAPI server exposing /v1/chat/completions with retrieval grounding injected automatically and a `minics` metadata block (version, model, documents used, citations) on every response. Use when other services need grounded LLM answers through an OpenAI client, or when exposing the knowledge base as an API.
---

# MiniCS proxy

The proxy is a second server (FastAPI + uvicorn, separate from the Flask UI
server) that speaks the **OpenAI protocol** on top of the MiniCS index. Point
any OpenAI client at it and every answer is grounded in your documents.

## Launch

```bash
minics proxy                          # http://127.0.0.1:8766/v1
minics proxy --host 0.0.0.0 --port 9000
```

Uses the same `~/.minics/config.json` as everything else (override with
`MINICS_HOME` or the global `--home PATH`), so the chat model, embedding
endpoint, retrieval defaults and reranker are shared with the studio.

## Endpoints

| Route | Purpose |
| --- | --- |
| `POST /v1/chat/completions` | OpenAI chat completions with automatic grounding. |
| `GET /v1/models` | The configured chat model (so clients can discover it). |
| `GET /health` | Status, version, readiness, rerank availability. |

## Request flow

1. The last user message becomes the retrieval query.
2. Hybrid retrieval runs **first** (vector + graph, rerank when enabled).
3. The retrieved context is injected as a system message (`References:` block
   with `[n]` citation markers).
4. The enhanced prompt is sent to the configured LLM.
5. The OpenAI-shaped response gains a `minics` metadata block.

## The `minics` metadata block

Every response (and the first SSE chunk when streaming) carries:

```json
{
  "minics": {
    "version": "0.5.0",
    "model": "llm-base",
    "grounded": true,
    "latency_ms": 7354,
    "retrieval": {
      "used": true, "used_rag": true, "used_graph": true, "rerank": false,
      "top_k": 8, "chunks": 5,
      "documents": [{"id": 2, "title": "tyness"}],
      "citations": [{"kind": "vector", "ref": "doc-2-chunk-1", "title": "tyness", "score": 0.032}],
      "diagnostics": {"vector_hits": 5, "graph_hits": 5}
    }
  }
}
```

- `documents` — the files that fed the answer (unique document ids + titles).
- `citations` — traceable `[n]` references back to source chunks.
- `diagnostics` — retriever counters (vector/graph hits, rerank applied).

## Per-request grounding options

Pass an optional top-level `minics` object in the request body:

```json
{
  "model": "llm-base",
  "messages": [{"role": "user", "content": "How does Tyness score replies?"}],
  "minics": {
    "use_rag": true, "use_graph": true, "use_grounding": true,
    "top_k": 5, "document_ids": [2], "max_context_chars": 8000
  }
}
```

`"use_grounding": false` answers without retrieval (metadata reports
`grounded: false`).

## Usage from any OpenAI client

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8766/v1", api_key="none")
reply = client.chat.completions.create(
    model="llm-base",                                   # any name works
    messages=[{"role": "user", "content": "How does Tyness score replies?"}],
)
print(reply.choices[0].message.content)
print(reply.model_extra["minics"]["retrieval"]["documents"])  # files used
```

Streaming works with the standard SDK (`stream=True`); the metadata rides on
the first chunk and `[DONE]` terminates the stream.

## Notes

- Retrieval failures never break the chat: the request degrades to an
  ungrounded call and the metadata reports it.
- No authentication — bind to `127.0.0.1` unless the network is trusted, and
  put authentication in front if you expose it (same guidance as `minics serve`).
- The UI server (`minics serve`) and the proxy are independent processes; run
  both at once if you need the studio and the API.
