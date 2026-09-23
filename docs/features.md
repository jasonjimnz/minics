# Features

Everything MiniCS Lite can do, area by area. Each section links to the document
that explains how it works internally.

---

## 1. Dataset library

| Feature | What you get |
| --- | --- |
| Datasets | Named groups of entries with stats (counts, statuses, tags). |
| ChatML entries | One training sample with `system`/`user`/`assistant` messages, tags, notes. |
| Status workflow | Draft → review → approved, enforced by the service layer. |
| Versioning | Every message edit creates a version — full history, no data loss. |
| Validation | Structural ChatML validation on save (roles, message shape). |
| Collections | Curated, ordered subsets of entries for export. |

Internals: [backend.md](backend.md) (entities, repository, services).

## 2. Grounding engine — documents in, knowledge out

| Feature | What you get |
| --- | --- |
| Import formats | **PDF, DOCX, TXT, Markdown, LaTeX**. |
| Conversion | Every file becomes cleaned markdown; the LLM can optionally repair bad conversions. |
| Heading-aware chunking | Chunks respect document structure, so retrieved pieces stay coherent. |
| Vector index | ChromaDB with your configured embedding model; dimension detected and enforced. |
| Knowledge graph | Entities and relations extracted into an embedded LadybugDB graph. |
| Reindexing | One command rebuilds vectors + graph for the whole library. |

Internals: [rag.md](rag.md).

## 3. Hybrid retrieval

| Feature | What you get |
| --- | --- |
| Vector search | Semantic similarity over document chunks. |
| Graph search | Topology-aware results from the entity graph. |
| RRF fusion | Reciprocal Rank Fusion merges both ranked lists. |
| Graceful degradation | If the graph is unavailable, retrieval degrades to vectors-only (and vice versa) — nothing crashes. |
| Terminal search | `minics search "query" --top-k 5` for quick checks. |

## 4. LLM authoring toolbox

| Feature | What you get |
| --- | --- |
| Enhance fields | One-click rewrite of any field with model assistance. |
| Suggest tags | Model proposes tags from the entry content. |
| Evaluate entries | Six quality dimensions scored per entry. |
| Generate entries | New ChatML entries generated **grounded** in your imported documents. |
| Clean markdown | Repair converted documents before chunking. |
| Structured output | Three fallback strategies plus truncation handling, so flaky models still produce usable JSON. |

Internals: [llm.md](llm.md).

## 5. Chat with switches

| Feature | What you get |
| --- | --- |
| Per-conversation RAG toggle | Retrieve from your documents or not. |
| Per-conversation graph toggle | Include knowledge-graph topology. |
| Grounding preview | See exactly which chunks *would* be injected — retrieval and injection are independent. |
| Citations | Answers reference the source documents and chunks they used. |

## 6. Export anywhere

| Feature | What you get |
| --- | --- |
| Formats | **ChatML, JSONL, Alpaca, ShareGPT, Markdown**. |
| Consistency | Byte-identical output from UI, CLI or Python — one code path. |
| Filtering | Export only approved entries, include or strip metadata. |

## 7. Background-first operations

| Feature | What you get |
| --- | --- |
| Worker pool | Imports, indexing and evaluations run off the request thread. |
| Live progress | Server-Sent Events stream job progress to every open UI. |
| Concurrency safety | All SQLite writes funnel through a single dedicated writer thread (WAL). |

Internals: [backend.md](backend.md) (jobs, events) and [api.md](api.md) (the SSE stream).

## 8. Three ways to run it

| Mode | Command | Best for |
| --- | --- | --- |
| Desktop | `minics` | Daily authoring — native window via PyWebView. |
| Browser | `minics serve` | Headless machines, remote boxes, quick demos. |
| Container | `docker compose up -d` | Home server / VPS with a persistent volume. |

All three share the same Flask engine and the same store — see
[serving.md](serving.md) and [docker.md](docker.md).

## 9. CLI and Python API

- **Full CLI** — `init`, `setup`, `config`, `models`, `app`, `serve`,
  `datasets`, `entries`, `documents`, `reindex`, `export`, `search`,
  `version`, `info`. All output is JSON and composes with `jq`
  (command reference in [backend.md](backend.md)).
- **Library mode** — `from minics.services.context import get_context` gives you
  `ctx.datasets`, `ctx.entries`, `ctx.collections`, `ctx.documents`,
  `ctx.authoring`, `ctx.chat`, `ctx.export` and `ctx.retriever`: the exact
  services the UI calls (see [getting-started.md](getting-started.md)).

## 10. Themable no-build UI

- A single-page app with **no framework, no bundler, no `node_modules`** —
  plain ES2020 JavaScript served straight from the package.
- **15 hand-tuned themes** (System, Light, Dark, Ocean, Forest, Sunset, Nord,
  Rose, Midnight, Paper, Mono, Grape, Dracula, Catppuccin Mocha, Solarized) —
  pure CSS-variable swaps with dark form controls and themed scrollbars.
- Hash routing, SSE consumption, markdown rendering and an interactive graph
  canvas, all module-based — details in [frontend.md](frontend.md).

## 11. Local-first by design

- **One folder, your machine** — everything (config, SQLite, vectors, graph,
  documents) lives in `~/.minics`; see [storage.md](storage.md).
- **No cloud, no accounts, no telemetry** — the only outbound calls are to the
  model endpoints *you* configure.
- **OpenAI-protocol first** — any compatible endpoint works, local models
  included.
