# Architecture

MiniCS is a **local-first, layered Python application** with a no-build web
front-end. This document explains how the pieces fit, how a request travels
through the system, how concurrency is handled, and why each major decision was
made.

---

## 1. The big picture

```
┌────────────────────────────────────────────────────────────────────────┐
│  Presentation                                                          │
│    CLI (minics.cli)          Desktop shell (desktop.py, PyWebView)     │
│         │                            │                                 │
│         ▼                            ▼                                 │
│    Flask app (server/app.py)  ◄──── werkzeug on 127.0.0.1              │
│         │  REST blueprints + SSE + static SPA (no build step)          │
├─────────┼──────────────────────────────────────────────────────────────┤
│  Service layer                                                         │
│    AppContext (services/context.py) — one object wiring everything     │
│    datasets · entries · collections · documents · authoring · chat     │
│    indexer · graph_indexer · retriever   (all usable from Python)      │
├────────────────────────────────────────────────────────────────────────┤
│  Engine layer                                                          │
│    core/  (config, SQLite writer, event bus, job manager, repository)  │
│    llm/   (OpenAI protocol, embeddings, structured output)             │
│    rag/   (chunking, entities, graph, vectors, fusion, retrieval)      │
│    documents/ (format conversion)                                      │
├────────────────────────────────────────────────────────────────────────┤
│  Storage                                                               │
│    SQLite (WAL, single writer) · ChromaDB · Ladybug graph · files      │
└────────────────────────────────────────────────────────────────────────┘
```

Key principle: **the service layer is the application**. The Flask API, the CLI
and any Python script call the exact same services, so behaviour is identical
everywhere. `server/app.py` is deliberately thin — every endpoint delegates to
`AppContext`.

## 2. Layers in detail

### 2.1 `core/` — infrastructure

| Module | Responsibility |
| --- | --- |
| `paths.py` | The single source of filesystem truth (`~/.minics`, overridable via `MINICS_HOME`). Everything else asks it for paths; nothing builds paths by hand. |
| `config.py` | Pydantic config models (`LLMSettings`, `EmbeddingSettings`, `RetrievalSettings`, `AppSettings`), atomic JSON persistence, deep-merge updates, secret masking. |
| `db.py` | Thread-safe SQLite: one dedicated writer thread, short-lived read connections, ordered migrations. |
| `schema.py` | Ordered migration list. Migrations are applied exactly once, never edited after release. |
| `events.py` | In-process pub/sub bus with bounded replayable history. |
| `jobs.py` | Thread-pool job manager with progress reporting and cancellation. |
| `repository.py` | Generic CRUD for pydantic entities — derives column mapping from the model. |
| `utils.py` | Timestamps, IDs, slugs, hashing, JSON helpers. |

### 2.2 `domain/` — entities

Pydantic models that are **storage-agnostic**: the repository layer flattens
them to SQLite rows (scalars → columns, bools → 0/1, lists/dicts → JSON text),
while the API layer serialises the same objects to JSON with
`model_dump(mode="json")`. `Entry.validate_chatml()` implements structural
validation (needs user + assistant, at most one system message, must not start
with assistant, no empty user/assistant messages).

### 2.3 `documents/` — conversion

Every imported file becomes **markdown** — the canonical text form. Markdown is
what gets chunked, what the graph extracts from, and what the editor shows.
Converters exist for PDF (`pypdf`), DOCX (`mammoth` → `markdownify`, fallback
`python-docx`), TXT, Markdown and LaTeX (regex pass + `pylatexenc`, math
protected).

### 2.4 `llm/` — model access

All model traffic goes through the **OpenAI protocol** (see [llm.md](llm.md)):
`client.py` builds raw `openai.OpenAI` clients and LangChain `ChatOpenAI`
wrappers; `structured.py` implements structured output with three strategies
and truncation detection; `enhance.py` + `prompts.py` implement the authoring
features.

### 2.5 `rag/` — retrieval

Chunking (heading-aware), heuristic entity extraction, the Ladybug graph store,
the Chroma vector store, the indexing pipeline, RRF fusion and the hybrid
retriever (see [rag.md](rag.md)).

### 2.6 `services/` — the library API

Stateless façades over repositories that own business rules and publish events.
`context.py` wires everything lazily and caches it:

- repositories and services are created once and reused,
- the `vectorstore` is **rebuilt whenever LLM/embedding settings change**
  (`llm_epoch` counter), because the collection depends on the embedding
  dimension,
- `get_context()` returns a process-wide singleton; tests swap it with
  `set_context()`.

### 2.7 `server/` — HTTP

- `app.py` — Flask factory: registers blueprints, error handlers, `/` (SPA),
  `/healthz`.
- `api/` — eight blueprints (system, datasets, entries, collections,
  documents, chat, jobs, retrieval), each with its own `/api/...` prefix.
- `deps.py` — request helpers: context access, `{ok, data}` envelope, job
  submission, global error → HTTP mapping.
- `sse.py` — Server-Sent Events response helper.
- `static/` + `templates/index.html` — the front-end SPA (see
  [frontend.md](frontend.md)).

### 2.8 `desktop.py` / `cli.py` — entry points

The desktop shell runs a werkzeug server on a background thread bound to
`127.0.0.1` and renders the UI in a native PyWebView window; if no GUI backend
exists it falls back to the system browser. The CLI (argparse) exposes
init/setup/config/models/datasets/entries/documents/reindex/export/search and
launches the app when called with no subcommand.

---

## 3. Request lifecycle

A typical write-heavy request — **import a document** — flows like this:

```
POST /api/documents  (multipart files)
  │
  ├─ api/documents.create_document()      reads files into bytes
  ├─ deps.submit_job("Import N document(s)", _import_files, files=…)
  │    └─ JobManager.submit()             queues on ThreadPoolExecutor
  │       publishes job.queued on the bus          ──► SSE ──► UI toast
  │       returns 202 + job JSON immediately
  │
  └─ worker thread runs _import_files(job_ctx, …):
       for each file:
         documents.import_bytes()          store original, sha256 dedupe
           convert_file()                  format → markdown
           _maybe_clean()                  heuristic + optional LLM cleanup
           repo.update()                   status = ready
         _index_document()
           indexer.index_document()        chunk → embed (batched) → Chroma
                                           persist chunks to SQLite
           graph_indexer.index_document()  chunk → entities → Ladybug
         job_ctx.update(fraction, message) publishes job.progress ──► SSE
       job_ctx.check_cancelled() between steps
       JobManager publishes job.finished            ──► SSE ──► UI refresh
```

The UI never blocks: the POST returns `202 Accepted` with the job id, and the
page either polls (`App.watchJob`) or reacts to SSE events. A read request
(e.g. `GET /api/entries`) is simpler: blueprint → service → repository →
short-lived SQLite reader → pydantic entities → `{ok: true, data: …}`.

## 4. Concurrency model

MiniCS is a threaded desktop app, so concurrency is handled explicitly:

1. **SQLite — single writer.** SQLite in WAL mode allows many concurrent
   readers but only one writer, and a connection cannot cross threads. MiniCS
   funnels *all* writes through one dedicated `_WriterThread` that owns the
   writable connection and executes submitted callables in order, committing
   after each. Readers use per-thread connections (`threading.local`) opened
   read-only. `busy_timeout` guards against external processes.
   See `core/db.py`.
2. **Background jobs.** `JobManager` wraps a `ThreadPoolExecutor`
   (`app.max_workers`, default 4). Each job gets a `JobContext` for progress
   reporting and cooperative cancellation (`check_cancelled()` raises
   `JobCancelled`, which the manager turns into a `cancelled` status).
3. **Event bus.** `EventBus` is a lock-protected set of subscriber queues with
   a bounded history deque (500 events). Slow consumers drop the oldest queue
   item rather than blocking producers.
4. **Stores.** `VectorStore` and `GraphStore` guard lazy initialisation and all
   operations with `RLock`s (Chroma and Ladybug are not relied upon for
   cross-thread safety).
5. **HTTP.** Flask runs `threaded=True`; desktop uses `werkzeug.make_server`
   with `threaded=True` on a daemon thread. No request handler ever blocks on
   model calls for long — anything slow goes through the job manager.

## 5. Storage layout

```
~/.minics/
├── config.json            ConfigManager (atomic temp-file replace)
├── minics.sqlite3         all relational data (WAL → -wal/-shm sidecars)
├── vectordb/              Chroma PersistentClient, cosine space, one collection
├── graphdb/minics.graph   Ladybug database file
├── documents/originals/   untouched uploads (provenance / re-extraction)
├── documents/markdown/    cleaned markdown keyed by public_id
├── logs/  cache/          reserved for diagnostics and temp data
```

Why this split:

- **SQLite** holds relational data *and* the canonical chunk text — needed for
  enriching retrieval hits, feeding the graph extractor and showing sources
  without touching Chroma.
- **Chroma** holds vectors only; embeddings are computed by MiniCS (not by
  Chroma) so model, dimension and batching stay configurable and visible.
- **The graph** holds topology only (mentions, co-occurrences, adjacency), not
  text — it is a *structural* signal to be fused with vectors.
- **Originals** are kept byte-exact so re-conversion never loses information.

## 6. Design decisions & rationale

| Decision | Rationale |
| --- | --- |
| **OpenAI protocol everywhere** | One integration covers OpenAI, vLLM, llama.cpp, LM Studio, Ollama and gateways. No provider-specific code paths. |
| **Services as the API** | CLI, HTTP and Python callers share behaviour; tests can exercise business logic without Flask. |
| **Single writer thread for SQLite** | Eliminates `database is locked` errors from concurrent workers; WAL keeps readers fast; transactions are explicit per job. |
| **Pydantic entities + generic repository** | One CRUD implementation for seven entities; column mapping derived from type annotations (JSON columns, bool columns, `index`→`idx` renames). |
| **Event bus + SSE instead of polling** | Instant UI feedback for long jobs with a replayable history buffer so reconnecting clients catch up. |
| **Structured output with 3 fallbacks** | Local servers differ wildly in structured-output support (json_schema, tools, plain prompting). Falling back keeps one code path for all of them, and truncation is detected explicitly rather than surfacing as a parse error. |
| **Markdown as canonical document form** | Chunking, graph extraction and editing all operate on one human-readable format; originals stay for re-extraction. |
| **Heuristic graph + optional LLM enrichment** | The graph needs stable topology, not perfect NLP. Cheap heuristics always work offline; the LLM pass is a quality boost, not a dependency. |
| **RRF over score blending** | Vector similarity (cosine) and graph entity weights are incomparable scales; fusing *ranks* with damping constant *k* is robust and needs no calibration. |
| **No-build front-end** | Plain ES2020 modules served from `static/`; zero toolchain, instant hackability, versioned cache-busting via `?v={{ version }}`. |
| **Everything under one home dir** | Backup = copy a folder; tests override `MINICS_HOME`; uninstall = delete it. |

## 7. Failure philosophy

- **Degrade, don't die.** Chat works without retrieval; retrieval works without
  the graph; both sides warn via the event bus and the other side keeps
  answering.
- **Background work is cancellable.** Long jobs check `cancel_event` between
  units (per file, per batch, per chunk).
- **Best-effort persistence.** LLM markdown cleanup failing falls back to the
  heuristic cleaner; a document that fails to index is marked `error` with the
  message instead of breaking the import batch.
- **Errors are data.** The API maps typed exceptions (`NotFoundError` → 404,
  `LLMError` → 502, …) into the `{ok: false, error}` envelope; job failures are
  published as events with full tracebacks in `data.traceback`.
