# Serving with Flask

MiniCS ships one HTTP engine — a Flask app built by `create_app()` — and every
run mode wraps it: the desktop shell embeds it in a PyWebView window, `minics
serve` exposes it to your browser, and Docker runs it in a container. This page
explains the server itself and how to host it deliberately.

A **second, independent server** — the OpenAI-compatible RAG proxy — is
documented in section 7 (`minics proxy`, FastAPI).

---

## 1. The three run modes

| Mode | What happens | When to use |
| --- | --- | --- |
| `minics` (desktop) | Picks a free port, starts the Flask app on a **threaded werkzeug server** in a daemon thread, opens a PyWebView window at `http://127.0.0.1:<port>/`. Falls back to your browser if no webview exists. | Daily authoring. |
| `minics serve` | Runs the same Flask app via `run_browser()` and opens it in your default browser. | Headless machines, remote boxes. |
| Your own process | Import `create_app()` and serve it however you like. | Custom deployments, WSGI servers, testing. |

All modes use the identical code path: `get_context()` → `ensure_ready()`
(auto-creates the store) → `create_app(ctx)`.

## 2. `minics serve` — the built-in server

```bash
minics serve                    # default host/port from config (127.0.0.1:8765)
minics serve --host 0.0.0.0 --port 8800 --no-browser
```

| Flag | Meaning |
| --- | --- |
| `--host` | Bind address. Defaults to the `app.host` config key (`127.0.0.1`). |
| `--port` | Port. Defaults to the `app.port` config key (`8765`). |
| `--no-browser` | Do not open a browser tab. |
| `--debug` | Flask debug mode (development only). |

First run auto-creates the store — on a fresh machine `minics serve` alone
gives you a working, empty studio.

## 3. Running the Flask app yourself

The app factory is public API:

```python
from minics.server import create_app
from minics.services.context import get_context

ctx = get_context()          # honours MINICS_HOME; auto-creates the store
app = create_app(ctx)
app.run(host="127.0.0.1", port=8800)
```

`create_app()` also accepts `home=` (store path) and `config_overrides=`
(dict deep-merged over `config.json`) — convenient for tests and one-off
deployments:

```python
app = create_app(home="/srv/minics", config_overrides={"app": {"port": 9001}})
```

What the app exposes:

| Route | Purpose |
| --- | --- |
| `/` | The SPA (static files under `minics/server/static/`). |
| `/api/...` | The REST endpoints — every one documented in [api.md](api.md). |
| `/api/events` | The **SSE** stream for live job/event progress. |
| `/healthz` | Health probe (the Docker `HEALTHCHECK` polls this). |

> **Threading matters.** The SSE stream and background jobs require a threaded
> server. Flask's built-in `app.run(threaded=True)` (the default) is fine;
> never run it with a single-threaded WSGI worker.

## 4. Production considerations

### No authentication — by design

MiniCS has **no login, no user model, no rate limiting**. The API can create,
edit and delete your datasets. Treat the server as a **single-user application
on a trusted network**:

- keep the default `127.0.0.1` binding when the UI is only for you,
- expose it to your LAN or VPN only if everyone on that network may edit the
  store,
- **never** port-forward it directly to the public internet.

If you need remote access, put it behind a proxy that adds authentication
(basic auth, SSO, Tailscale/Firewall gating) — see below.

### Behind a reverse proxy (nginx example)

Two things need care: SSE and request sizes.

```nginx
server {
    listen 443 ssl;
    server_name minics.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;

        # SSE: the /api/events stream must not be buffered
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_set_header Connection "";

        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        client_max_body_size 100m;   # document uploads
    }
}
```

Basic auth at the proxy is the simplest way to add credentials:

```nginx
auth_basic "MiniCS";
auth_basic_user_file /etc/nginx/.htpasswd;
```

### WSGI servers

The app is a plain Flask/WSGI application, so any compliant server works, e.g.:

```bash
pip install waitress
```

```python
# wsgi.py
from minics.services.context import get_context
from minics.server import create_app

application = create_app(get_context())   # store auto-created on first request
```

```bash
waitress-serve --host 0.0.0.0 --port 8765 --threads 8 wsgi:application
```
```

or, in your own wrapper script (the most explicit option):

```python
from waitress import serve
from minics.services.context import get_context
from minics.server import create_app

serve(create_app(get_context()), host="0.0.0.0", port=8765, threads=8)
```

Keep in mind:

- **One process, one store.** SQLite and the embedded vector/graph databases
  (see [storage.md](storage.md)) assume a single application process. Do not
  run multiple instances against the same `~/.minics`; scale up containers
  instead.
- **Threads, not processes.** The writer-thread and SSE design is
  in-process; prefer a threaded server (waitress with `threads=N`) over
  multi-process forking models.
- **WebSocket-free** — progress is SSE only, which simplifies proxies.

## 5. Configuration keys that affect serving

| Key (in `config.json`) | Default | Meaning |
| --- | --- | --- |
| `app.host` | `127.0.0.1` | Bind address used when `--host` is omitted. |
| `app.port` | `8765` | Port used when `--port` is omitted. |
| `app.open_browser` | `true` | Whether `minics serve` opens a browser. |

The full schema is in [configuration.md](configuration.md).

## 6. Docker is the same server

The Docker image simply runs `minics serve --host 0.0.0.0 --no-browser` with
the store mounted at `/data` — everything on this page (routes, proxying,
auth) applies unchanged. Build and run instructions, compose file and
container-specific troubleshooting are in [docker.md](docker.md).

---

## 7. `minics proxy` — the OpenAI-compatible RAG proxy (FastAPI)

The studio UI answers questions *interactively*; the proxy lets **any other
service** consume the same index through the OpenAI protocol. It is a separate
FastAPI/uvicorn process, launchable from the CLI:

```bash
minics proxy                            # http://127.0.0.1:8766/v1
minics proxy --host 0.0.0.0 --port 9000
```

It reads the same `~/.minics/config.json` (LLM, embedding, retrieval defaults,
reranker), so it always serves the model configuration you set up in the
studio.

### Routes

| Route | Purpose |
| --- | --- |
| `POST /v1/chat/completions` | Chat completions with automatic retrieval grounding. Supports `stream: true` (SSE). |
| `GET /v1/models` | OpenAI model list containing the configured chat model. |
| `GET /health` | `{status, version, model, ready, rerank}`. |

### Flow

```
client ──► /v1/chat/completions
             │ 1. last user message becomes the query
             │ 2. hybrid retrieval (vector + graph [+ rerank])
             │ 3. context injected as a system message (References: [n]…)
             │ 4. enhanced prompt sent to the configured LLM
             ▼
          OpenAI-shaped response + minics metadata block
```

### The `minics` metadata block

Every non-streaming response (and the first streaming chunk) carries the
MiniCS metadata — version, model, which **documents** fed the answer,
traceable citations and retrieval diagnostics:

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

### Per-request options

Pass an optional top-level `minics` object in the request body to override the
defaults for that call: `use_rag`, `use_graph`, `use_grounding`, `top_k`,
`document_ids` (restrict grounding to specific documents) and
`max_context_chars`.

### Example

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8766/v1", api_key="none")
reply = client.chat.completions.create(
    model="llm-base",  # any name works; the configured model answers
    messages=[{"role": "user", "content": "How does Tyness score replies?"}],
)
print(reply.choices[0].message.content)
print(reply.model_extra["minics"]["retrieval"]["documents"])  # files used
```

Streaming works with the standard SDK (`stream=True`); metadata rides on the
first chunk. Retrieval failures never break the chat — the request degrades to
an ungrounded call and the metadata reports `grounded: false`.

> Same trust model as the Flask server: **no authentication** — bind to
> loopback unless the network is trusted and put auth in front otherwise.
