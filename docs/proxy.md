# Proxy API (OpenAI-compatible)

The proxy is MiniCS's second server — a **FastAPI/uvicorn** process, separate
from the Flask studio UI — that exposes your knowledge base through the
**OpenAI protocol**. Point any OpenAI client (Python SDK, JavaScript SDK,
LangChain, Cursor, Open WebUI, `curl`, …) at it and every answer is
automatically grounded in your documents.

```
client ──► POST /v1/chat/completions
              │ 1. last user message becomes the retrieval query
              │ 2. hybrid retrieval: ChromaDB vectors + Ladybug graph
              │ 3. optional cross-encoder rerank (retrieval.rerank config)
              │ 4. context injected as a system message ("References: [n]…")
              │ 5. enhanced prompt forwarded to the configured LLM
              ▼
           OpenAI-shaped response + "minics" metadata block
```

Retrieval runs **first**; nothing is sent to the LLM until the context has
been injected. Every response carries a `minics` metadata block so callers can
trace the answer back to the exact documents and chunks that produced it.

---

## 1. Launching

```bash
minics proxy                            # http://127.0.0.1:8766/v1
minics proxy --host 0.0.0.0 --port 9000 # bind for LAN/containers
minics --home /data proxy               # explicit store (same as other commands)
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Bind address. Use `0.0.0.0` in containers/remote hosts. |
| `--port` | `8766` | HTTP port. |
| `--log-level` | `info` | uvicorn log level (`debug`, `info`, `warning`, `error`). |

It reads the same `~/.minics/config.json` as the studio (override with the
global `--home` flag or `MINICS_HOME`), so the chat model, embedding endpoint,
retrieval defaults, top-k and reranker are shared with everything else.

The proxy is also a library API:

```python
from minics.proxy.app import create_proxy_app, run_proxy
from minics.services.context import get_context

app = create_proxy_app(get_context())   # ASGI app — test with httpx, serve with uvicorn…
run_proxy(host="127.0.0.1", port=8766)  # blocking convenience launcher
```

The Docker image runs the studio server; for a proxy container use
`command: minics proxy --host 0.0.0.0` in your compose service.

---

## 2. Endpoints

| Route | Method | Purpose |
| --- | --- | --- |
| `/v1/chat/completions` | POST | Chat completions with automatic retrieval grounding. OpenAI-compatible, streaming supported. |
| `/v1/models` | GET | OpenAI model list containing the configured chat model. |
| `/health` | GET | Service status, version, readiness, rerank availability. |

### 2.1 `GET /health`

```json
{
  "status": "ok",
  "service": "minics-proxy",
  "version": "0.5.1",
  "model": "llm-base",
  "ready": true,
  "rerank": true
}
```

`status` is `"degraded"` when the store is not set up yet (the proxy will
still answer, just ungrounded); `rerank` mirrors `Config.rerank_ready`.

### 2.2 `GET /v1/models`

```json
{
  "object": "list",
  "data": [{"id": "llm-base", "object": "model", "created": 0, "owned_by": "minics"}]
}
```

The single advertised model is the chat model configured in the studio. The
proxy accepts **any** model name in requests — the configured one always
answers (OpenAI clients that validate the model id against this list work out
of the box).

---

## 3. `POST /v1/chat/completions`

### 3.1 Request

A standard OpenAI chat completion request, **plus one MiniCS extension**: the
optional top-level `"minics"` object.

```json
{
  "model": "llm-base",
  "messages": [
    {"role": "system", "content": "Answer briefly."},
    {"role": "user", "content": "Which UDP port does the Atlas WireGuard VPN use?"}
  ],
  "temperature": 0.7,
  "max_tokens": 1024,
  "stream": false,
  "minics": {
    "use_rag": true,
    "use_graph": true,
    "use_grounding": true,
    "top_k": 5,
    "document_ids": [2],
    "max_context_chars": 8000
  }
}
```

Standard OpenAI fields (`temperature`, `top_p`, `max_tokens`, `stop`, `user`,
`stream`, …) are forwarded to the LLM endpoint. Unknown future OpenAI fields
are tolerated and forwarded, so clients never break.

**The `minics` options object** (every field optional):

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `use_rag` | bool | `true` | Include vector (semantic) retrieval. |
| `use_graph` | bool | `true` | Include the entity-graph retrieval side. |
| `use_grounding` | bool | `true` | Master switch — `false` skips retrieval entirely and answers ungrounded. |
| `top_k` | int | config `retrieval.top_k` | Max chunks retrieved/injected for this request. |
| `document_ids` | int[] | *(all)* | Restrict grounding to specific documents. |
| `max_context_chars` | int | `8000` | Cap for the injected context block. |

Omit `"minics"` entirely to use the studio's defaults for everything.

### 3.2 How the prompt is built

The numbered references are generated from the retrieved chunks and injected
as a **system message** (merged above the caller's own system message):

```
Use the reference material below to answer.

- Cite sources inline as [n] matching the numbered references.
- If the material does not contain the answer, say so and answer from general knowledge.
- Never contradict the reference material.

References:
[1] Atlas FAQ — VPN
WireGuard uses UDP 51820. IPsec uses UDP 500 and 4500.

[2] Atlas Router Guide — VPN
Atlas supports WireGuard and IPsec…
```

### 3.3 Response (non-streaming)

The upstream OpenAI response, enriched with the `minics` metadata block:

```json
{
  "id": "chatcmpl-…",
  "object": "chat.completion",
  "model": "llm-base",
  "choices": [
    {
      "index": 0,
      "finish_reason": "stop",
      "message": {
        "role": "assistant",
        "content": "The Atlas WireGuard VPN uses UDP port 51820 [1]."
      }
    }
  ],
  "usage": {"prompt_tokens": 412, "completion_tokens": 23, "total_tokens": 435},
  "minics": {
    "version": "0.5.1",
    "model": "llm-base",
    "grounded": true,
    "latency_ms": 7354,
    "retrieval": {
      "used": true,
      "query": "Which UDP port does the Atlas WireGuard VPN use?",
      "used_rag": true,
      "used_graph": true,
      "rerank": false,
      "top_k": 5,
      "chunks": 2,
      "documents": [{"id": 2, "title": "atlas-faq"}, {"id": 1, "title": "atlas-router"}],
      "citations": [
        {
          "kind": "vector",
          "ref": "doc-2-chunk-1",
          "title": "atlas-faq",
          "snippet": "WireGuard uses UDP 51820. IPsec uses UDP 500 and 4500.",
          "score": 0.0328,
          "document_id": 2,
          "metadata": {"heading": "Atlas FAQ", "index": 1}
        }
      ],
      "diagnostics": {"vector_hits": 5, "graph_hits": 5, "rerank": false, "fused": 2}
    }
  }
}
```

#### The `minics` block — field reference

| Field | Meaning |
| --- | --- |
| `version` | MiniCS version that served the request. |
| `model` | Chat model that answered (the configured one). |
| `grounded` | `true` when retrieved context was actually injected. |
| `latency_ms` | Total proxy time (retrieval + LLM), non-streaming only. |
| `retrieval.used` | Any context was found and injected. |
| `retrieval.query` | The extraction of the last user message used as query. |
| `retrieval.used_rag` / `used_graph` | Which retriever sides contributed. |
| `retrieval.rerank` | Whether the reranker actually re-ordered results (config-gated). |
| `retrieval.top_k` | Effective chunk budget for the request. |
| `retrieval.chunks` | Number of chunks injected. |
| `retrieval.documents` | **Unique files used**: `id` (document id) + `title`. |
| `retrieval.citations` | One `Citation` per chunk: `kind` (`vector`/`graph`), `ref` (chunk id), `title`, 280-char `snippet`, fused `score`, `document_id`, `metadata.heading`/`index`. The `[n]` markers in the answer map to this array order. |
| `retrieval.diagnostics` | Raw retriever counters (`vector_hits`, `graph_hits`, `rerank`, `fused`). |

### 3.4 Streaming (`"stream": true`)

Server-Sent Events, exactly like OpenAI:

```
data: {"id":"chatcmpl-…","object":"chat.completion.chunk","choices":[{"delta":{"role":"assistant","content":""},"index":0}],"model":"llm-base","minics":{ … full metadata block … }}

data: {"id":"chatcmpl-…","object":"chat.completion.chunk","choices":[{"delta":{"content":"UDP 51820"},"index":0}]}

data: [DONE]
```

- The **first chunk carries the whole `minics` metadata block** (retrieval
  finished before the first token, so the metadata is known upfront).
- Later chunks are the raw upstream deltas; `[DONE]` terminates the stream.
- Streamed responses do not include `latency_ms` (the metadata is sent before
  generation completes).

### 3.5 Errors

Errors follow the OpenAI error envelope; grounding never breaks a request:

| Situation | Result |
| --- | --- |
| Retrieval fails (embeddings down, index empty, rerank timeout) | Request proceeds **ungrounded**; `minics.grounded: false`, `retrieval.used: false`. |
| LLM endpoint unreachable / errors | HTTP **502** with `{"error": {"message": "…"}}`. |
| Mid-stream upstream failure | `data: {"error": {"message": …}}` on the SSE stream. |
| Store not set up | 200 with ungrounded answer (`/health` reports `ready: false`). |

---

## 4. Client examples

### curl

```bash
curl -X POST http://127.0.0.1:8766/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
        "model": "llm-base",
        "messages": [{"role": "user", "content": "Which UDP port does the Atlas WireGuard VPN use?"}]
      }'
```

With options (single-document grounding, RAG only):

```bash
curl -X POST http://127.0.0.1:8766/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
        "model": "llm-base",
        "messages": [{"role": "user", "content": "Which UDP port does the VPN use?"}],
        "minics": {"use_graph": false, "document_ids": [2], "top_k": 3}
      }'
```

### Python (OpenAI SDK — zero changes beyond the base URL)

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8766/v1", api_key="any-key")

# Non-streaming — read the metadata from model_extra
reply = client.chat.completions.create(
    model="llm-base",
    messages=[{"role": "user", "content": "Which UDP port does the Atlas VPN use?"}],
)
print(reply.choices[0].message.content)
meta = reply.model_extra["minics"]
print(meta["retrieval"]["documents"])   # [{'id': 2, 'title': 'atlas-faq'}, …]

# Streaming — metadata rides on the first chunk
stream = client.chat.completions.create(
    model="llm-base",
    stream=True,
    messages=[{"role": "user", "content": "Does Atlas support IPsec?"}],
)
for chunk in stream:
    meta = (getattr(chunk, "model_extra", {}) or {}).get("minics")
    if meta and meta["retrieval"]["used"]:
        print("grounded with:", [d["title"] for d in meta["retrieval"]["documents"]])
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### JavaScript / TypeScript

```ts
import OpenAI from "openai";

const client = new OpenAI({ baseURL: "http://127.0.0.1:8766/v1", apiKey: "any-key" });
const reply = await client.chat.completions.create({
  model: "llm-base",
  messages: [{ role: "user", content: "Which UDP port does the Atlas VPN use?" }],
});
console.log(reply.choices[0].message.content);
console.log((reply as any).minics?.retrieval?.documents);
```

### External GUIs (Open WebUI, LibreChat, ChatBox, …)

Add a custom OpenAI connection with base URL `http://<host>:8766/v1` and any
API key. The advertised model is `GET /v1/models`-discoverable; grounding is
on by default, and `[n]` citations appear inline in the answers.

---

## 5. Configuration & retrieval behaviour

The proxy honours the same `[retrieval]` settings as the studio:

- `retrieval.top_k` — default chunk budget (per-request `minics.top_k` wins),
- `retrieval.use_rag` / `use_graph` / `use_grounding` — defaults per request,
- `retrieval.rerank` — when enabled, the fused pool is re-scored by the
  Cohere-compatible `/rerank` endpoint before the top-k cut; the proxy's
  `minics.retrieval.rerank` field reports whether it was applied
  (see [Configuration](configuration.md) for the full schema).

The chat LLM and embedding endpoints are also the studio's — configure them
once with `minics setup` and both servers share them.

---

## 6. Deploying

- **No authentication, by design** — bind to `127.0.0.1` unless the network is
  trusted. To expose it, front it with a reverse proxy that adds auth (basic
  auth, SSO, Tailscale, …).
- **Behind nginx**: streaming is SSE — disable buffering on the route
  (`proxy_buffering off;`), same as the studio's `/api/events` (see
  [Serving](serving.md)).
- **Docker**: run the studio image with `command: minics proxy --host 0.0.0.0`
  and mount the store volume at `/data` as usual; expose the proxy port
  instead of (or in addition to) 8765.
- **One process, one store** — as with `minics serve`, do not run multiple
  proxies against the same `~/.minics` at once.
- The studio UI (`minics serve`, port 8765) and the proxy (port 8766) are
  independent processes; run both when you need the app **and** the API.

---

## 7. Proxy vs studio API — which one when?

| | Studio REST (`minics serve`, port 8765) | Proxy (`minics proxy`, port 8766) |
| --- | --- | --- |
| Protocol | Custom REST + SSE (`/api/...`) | **OpenAI** (`/v1/...`) |
| Audience | The bundled web UI / your scripts | Any OpenAI client, GUIs, LangChain, services |
| Grounding | Explicit, with per-conversation toggles + UI | Automatic per request (`minics` options) |
| Traceability | Citations in the chat UI | `minics` metadata block + `[n]` citations |
| Framework | Flask + werkzeug | FastAPI + uvicorn |
| Auth | None (bind loopback) | None (bind loopback) |

Both read the same store and configuration — run them side by side.
