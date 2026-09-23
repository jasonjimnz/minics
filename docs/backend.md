# Core & backend

This document covers the infrastructure modules in `minics/core`, the domain
entities, the service layer, and the two entry points (CLI and desktop shell).
The LLM layer and RAG engine have their own documents.

---

## 1. `core/paths.py` — the filesystem contract

`MinicsPaths` is a frozen dataclass rooted at one directory:

- `~/.minics` by default, or `$MINICS_HOME` when set (`default_home()`).
- Sub-directories created on `ensure()`: `documents/`, `documents/markdown/`,
  `documents/originals/`, `vectordb/`, `graphdb/`, `logs/`, `cache/`.
- Key files: `config_file` (`config.json`), `database` (`minics.sqlite3`),
  `graph_file` (`graphdb/minics.graph`).

Every other module asks `get_paths()` for paths; nothing builds them by hand.
Tests simply point `MINICS_HOME` at a temp dir.

## 2. `core/db.py` — concurrency-safe SQLite

SQLite gives WAL (many concurrent readers + one writer) but not parallel
writers, and a connection cannot cross threads. MiniCS therefore funnels **all
writes through a single dedicated writer thread**:

```
caller thread                    _WriterThread ("minics-sqlite-writer")
     │  submit(fn)                      owns the only writable connection
     │  ── queue ──►  run fn(conn) ──►  conn.commit() / rollback
     │  ◄── _Future ──  result or exception
```

- **`_WriterThread`** creates its connection *inside* `run()` (sqlite3
  enforces same-thread usage), sets `journal_mode=WAL` and
  `synchronous=NORMAL`, then loops over a job queue. Each submitted callable
  runs and commits atomically; exceptions propagate through a minimal
  `_Future` back to the caller.
- **Reads** use short-lived per-thread connections opened **read-only**
  (`file:…?mode=ro`) via `threading.local` — safe to use concurrently from
  Flask request threads and job workers alike.
- **`busy_timeout`** (default 5 s, configurable) guards the rare case of an
  external process holding the lock.
- **API surface**: `query / query_one / scalar` (reads), `execute / insert /
  update / execute_many / run_write / transaction` (writes, serialised),
  `get_state / set_state` (key/value table).
- **`migrate()`** applies pending migrations on `initialize()`, inside the
  writer, and records each applied version in `schema_log`.

## 3. `core/schema.py` — migrations

Migrations are ordered `Migration(version, name, statements)` records applied
exactly once, ascending, in the writer thread. Current set:

1. `core_kv_store` — `app_state` key/value table + `schema_log`.
2. `datasets_entries_collections_documents` — the full relational model:

| Table | Holds |
| --- | --- |
| `datasets` | name, slug, description, tags, source, metadata, settings |
| `entries` | dataset_id, status, messages (JSON), tags, notes, quality, evaluation (JSON), source, position, version |
| `entry_versions` | per-entry immutable snapshots with a reason (`UNIQUE(entry_id, version)`) |
| `collections` | name, slug, description, optional dataset_id, tags |
| `collection_entries` | ordered membership (`PRIMARY KEY(collection_id, entry_id)`) |
| `documents` | title, source, kind, original/markdown paths, size, sha256, status, error, chunk_count, tags |
| `document_chunks` | canonical chunk text per document (`UNIQUE(document_id, idx)`), vector_id, heading |
| `conversations` | title, system_prompt, the three use_* switches, optional dataset_id |
| `conversation_messages` | ordered messages with citations (JSON), model, usage |

Rules: **never edit a released migration** — add a new one. Indexes are
created alongside the tables.

## 4. `core/events.py` — the event bus

`EventBus` is a thread-safe pub/sub hub with a bounded, replayable history:

- `publish(event_or_kwargs)` stamps a monotonic `id`, appends to the history
  deque (500 events) and pushes to every subscriber queue (max 1000 items; a
  slow consumer drops its oldest item instead of blocking producers).
- `subscribe()/unsubscribe()` manage per-consumer `queue.Queue`s.
- `stream(after_id, timeout, stop)` yields history first, then live events,
  yielding `None` as a keep-alive heartbeat when idle. The SSE endpoint
  (`/api/events`) is the main consumer; the UI's `EventSource` reconnects with
  `?after=<last id>` to catch up.

Event fields: `type, message, level (debug|info|success|warning|error),
progress, source, data, id, ts, job_id`.

## 5. `core/jobs.py` — background jobs

`JobManager` runs callables on a `ThreadPoolExecutor` (`app.max_workers`) and
reports through the bus. Jobs are **handles, not durable records** — they live
in memory with 200-item history.

Lifecycle: `submit()` → `job.queued` → `job.started` → `job.progress`* →
`job.finished` (or `job.error` with a full traceback in `data.traceback`).

- **`Job`** carries status (`queued/running/success/error/cancelled`),
  progress 0–1, message, result, metadata, timings, `cancel_event`.
- **`JobContext`** is the handle passed to the callable:
  - `update(progress, message)` publishes `job.progress` and **raises
    `JobCancelled` if cancellation was requested**,
  - `step(i, total)` for loops,
  - `log(message, level, **data)` for `job.log` events,
  - `check_cancelled()` for cooperative cancellation between units of work.
- **`call()`** submits and waits (CLI/tests). **`cancel()`** sets the cancel
  event and un-queues queued jobs.
- Results are converted to JSON-safe data by `_jsonable` (pydantic models →
  dicts, non-serialisables → strings).

## 6. `core/repository.py` + `services/repositories.py` — persistence

`ModelRepository[M]` is generic CRUD derived from the pydantic model:

- scalars → native columns,
- `bool` → `0`/`1`,
- lists / dicts / nested models → compact JSON text (`json_dumps`),
- `column_map` renames a field (`index` → `idx` for chunks/messages),
- `exclude` drops computed fields (`Collection.entry_ids` is stored via the
  join table, not a column),
- `__init_subclass__` computes `json_columns` / `bool_columns` once per
  subclass.

Provides `get / get_by_public_id / list(where, params, limit, offset) / count
/ exists / insert / update (touch() included) / save / delete /
delete_by_public_id / transaction`.

Concrete repositories add domain queries: `EntryRepository.add_version()`
(snapshot + reason), `CollectionRepository.add_entries/remove_entries/
entries_for/collections_for_entry`, `DocumentRepository.by_sha256/set_status`,
`DocumentChunkRepository.by_vector_ids` (used by retrieval enrichment),
`ConversationMessageRepository.next_index`, slug lookups, etc.

## 7. `domain/entities.py` — the vocabulary

- **Enums**: `Role` (system/user/assistant/tool/developer), `EntryStatus`
  (draft/in_review/approved/rejected), `DocumentStatus`
  (pending/converting/indexing/ready/error), `SourceKind`.
- **`Entity`** base: `id`, `public_id` (16-hex), timestamps, `touch()`.
- **`ChatMessage`**: role + content (coerced to string) + optional name.
- **`Entry`**: dataset_id, status, messages, tags, notes, quality,
  evaluation (`Evaluation`: score, per-dimension scores, summary, strengths,
  issues, suggestions, evaluator, model), source, position, version.
  Helpers: `first(role)`, `system/user/assistant` properties,
  `validate_chatml()` (structural problems list), `to_chatml()`.
- **`Dataset`** / **`Collection`** (auto-slug), **`Document`** /
  **`DocumentChunk`**, **`Conversation`** / **`ConversationMessage`**
  (with `Citation`: kind vector/graph/document, ref, title, snippet, score).
- **`ExportRequest`**: format + metadata + status filters.

## 8. The service layer

`Service` (services/base.py) is the base façade: holds `ctx`, exposes
`db`/`config` shortcuts, `emit()` (publishes events with the service name as
source), `resolve_id()` (int or public-id → numeric id) and
`unique_slug()`.

| Service | Responsibility (highlights) |
| --- | --- |
| `DatasetService` | CRUD + per-status stats; name/description/tag filters. |
| `EntryService` | CRUD with `build_messages()` normalisation (messages list or system/user/assistant strings); **auto-versioning** — message changes bump `version` and snapshot into `entry_versions`; status/evaluation/tag helpers; `bulk_create` for ChatML imports; search across messages/notes. |
| `CollectionService` | CRUD, ordered membership (add/remove/set), stats, and export delegation. |
| `DocumentService` | Import (file or bytes) with **sha256 dedupe**, original storage, conversion, heuristic + optional LLM cleaning, markdown persistence and status tracking; markdown read/write; stats. |
| `AuthoringService` | LLM features over entries/documents: enhance fields (optionally grounded, optionally persisted), suggest tags (optionally applied), evaluate (persists `Evaluation`), generate entries (grounded), clean document markdown, enrich the graph with LLM entities. |
| `ChatService` | Conversations with the three switches; non-streaming `send()` and SSE `stream()`; grounding block built from retrieval; last-16-message prompt window; auto-titling; persisted citations and token usage. |

### `AppContext` (services/context.py)

One object wiring everything, created lazily and cached:

- `config` / `update_config()` (bumps `llm_epoch`, evicts the vector store),
- `db` (opens + migrates on first touch), `jobs`,
- lazy properties for every repository-backed service, `vectorstore`
  (rebuilt when the embedding settings change), `graph`, `graph_indexer`,
  `indexer`, `retriever`, `authoring`, `chat`,
- `get_context()` returns the process singleton; `set_context()` /
  `reset_context()` support tests and alternate entry points;
- `close()` closes the vector store, graph and database.

## 9. `cli.py` — the command line

`minics` with no subcommand launches the desktop app. Commands (all accept
`--home`):

> **First-run auto-initialisation** — every command that needs the store
> (`setup`, `datasets`, `entries`, `documents`, `reindex`, `export`, `search`,
> `serve`, `app`) creates the home directory structure and applies SQLite
> migrations before doing anything else. A brand-new machine only needs
> `minics serve` to get a working, empty studio; `init` exists for users who
> want to create the folder explicitly.

| Command | What it does |
| --- | --- |
| `init` | Create the home structure and run migrations. |
| `setup` | Interactive or flag-driven endpoint wizard; probes embedding dimension; connection test; marks setup complete. |
| `config` | Print the (masked) config; `--set JSON` deep-merges a patch. |
| `models` | List chat/embedding models from the endpoint. |
| `app` | Launch the desktop app (`--port`, `--debug`). |
| `serve` | Run the web server (`--host`, `--port`, `--no-browser`). |
| `datasets` | List datasets (with stats) or `--create NAME`. |
| `entries` | List entries (`--dataset`, `--status`, `--search`, `--limit`). |
| `documents` | `--import PATH…` (optionally indexing + graph), `--index-ref`, or list with `--search`. |
| `reindex` | Re-index every document (vectors + graph). |
| `export` | Export a collection (`--format`, `-o`, `--include-metadata`, `--approved`). |
| `search` | Hybrid retrieval from the terminal (`--top-k`, `--no-rag`, `--no-graph`). |
| `version`, `info` | Version; resolved paths and init state. |

Output is JSON everywhere (`_print`), so commands compose with `jq`.

## 10. `desktop.py` — the desktop shell

`run_app()`:

1. resolves/ensures the context and config,
2. picks a free port (`find_free_port` starting at `app.port`),
3. starts `ServerThread` — a `werkzeug.serving.make_server(host, port, app,
   threaded=True)` on a daemon thread,
4. opens a PyWebView window (`webview.create_window`, min size 900×600,
   text-selectable) pointed at `http://127.0.0.1:<port>/`,
5. on exit stops the server and closes the context.

If `webview` cannot import (headless Linux, missing GTK/Qt backend), it falls
back to `webbrowser.open()` and serves until interrupted — the app is never
unusable. `run_browser()` is the plain-server variant used by `minics serve`.
