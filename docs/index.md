# MiniCS documentation

Welcome to the **MiniCS Lite** documentation — *Mini ChatML Studio Lite*, a
local-first studio for building high quality LLM datasets: a ChatML library, a
hybrid RAG + graph grounding engine, LLM authoring tools, and a desktop UI —
all in one `~/.minics` folder.

These documents explain **how the application is built, which libraries it uses
and why, and how every feature works**, from the SQLite writer thread to the
theme picker in the browser.

## Reading order

| # | Document | Read it to learn… |
| --- | --- | --- |
| 1 | [Installation](installation.md) | Installing from PyPI or source, requirements, verifying and upgrading. |
| 2 | [Getting started](getting-started.md) | Creating the store, the setup wizard, your first dataset and export. |
| 3 | [Features](features.md) | The full feature tour across library, grounding, retrieval and UI. |
| 4 | [Architecture](architecture.md) | How the layers fit together, the request lifecycle, the concurrency model and the reasoning behind each big decision. |
| 5 | [Libraries](libraries.md) | What every dependency in `pyproject.toml` does, where it is used, and why it was chosen. |
| 6 | [Configuration](configuration.md) | Every config key, the setup wizard, `MINICS_HOME`, API-key masking and how config changes propagate. |
| 7 | [Core & backend](backend.md) | The SQLite writer thread, event bus, job manager, generic repository, domain entities, services, CLI and desktop shell. |
| 8 | [LLM layer](llm.md) | The OpenAI-protocol client, embeddings, structured output with fallbacks + truncation handling, the prompt library and the authoring helpers. |
| 9 | [RAG & graph](rag.md) | Document conversion, markdown-aware chunking, entity extraction, the Ladybug graph schema, ChromaDB, the indexing pipeline and RRF hybrid retrieval. |
| 10 | [Serving with Flask](serving.md) | `minics serve`, the Flask app factory, reverse proxies, security and WSGI notes. |
| 11 | [Docker](docker.md) | Running MiniCS as a server container: build, volumes, first-run setup, operations. |
| 12 | [HTTP API](api.md) | Every REST endpoint, the SSE event stream, the background-job workflow and error mapping. |
| 13 | [Frontend](frontend.md) | The no-build SPA: module layout, hash routing, SSE consumption, theming, the markdown renderer, the graph canvas and every screen. |
| 14 | [Data & storage](storage.md) | The `~/.minics` store, the three embedded databases, backups, portability and privacy. |
| 15 | [Development](development.md) | Setting up a dev environment, running tests, fixtures, code style, schema migrations and contribution workflow. |

## Cheat sheet

### Start the app

```bash
minics init && minics setup && minics    # desktop (PyWebView)
minics serve --port 8800                 # browser only — auto-creates the store on first run
docker compose up -d --build             # or as a server container (see docs/docker.md)
```

### Talk to the API

```bash
curl http://127.0.0.1:8765/api/health
curl http://127.0.0.1:8765/api/overview
curl -X POST http://127.0.0.1:8765/api/retrieval/search \
     -H "Content-Type: application/json" -d '{"query": "what is RRF?"}'
```

### Use as a Python library

```python
from minics.services.context import get_context

ctx = get_context()
ctx.datasets.create("Support QA")
ctx.retriever.retrieve("hybrid search").context_text()
```

### Run the tests

```bash
pytest -q
ruff check src tests
```

## Where the code lives

```
src/minics/
├── core/        paths, config, SQLite, events, jobs, repository, utils
├── domain/      pydantic entities (Dataset, Entry, Collection, Document, …)
├── documents/   PDF/DOCX/TXT/MD/TeX → markdown conversion
├── llm/         OpenAI client, embeddings, structured output, prompts
├── rag/         chunking, entities, graph, vectorstore, indexer, fusion, retriever
├── services/    the library API (datasets, entries, collections, documents,
│                authoring, chat, export, repositories, context)
├── server/      Flask app factory + REST blueprints + SSE + static SPA
│   └── static/  the frontend (api.js, ui.js, views.js, app.js, app.css)
├── desktop.py   PyWebView desktop shell
└── cli.py       the `minics` command
```

## Glossary

| Term | Meaning |
| --- | --- |
| **ChatML** | The `{"messages": [{role, content}, …]}` format used for training samples. |
| **Entry** | One ChatML training sample inside a dataset, with status, tags, notes, quality score and version history. |
| **Collection** | A curated, ordered, exportable set of entries. |
| **Document** | An imported source file plus its cleaned markdown. |
| **Chunk** | A heading-aware piece of a document; the unit of retrieval. |
| **Grounding** | Injecting retrieved chunks into a prompt so the model answers from your material. |
| **RRF** | Reciprocal Rank Fusion — combining ranked lists from multiple retrievers. |
| **Job** | A background task running on the worker pool with progress events. |
| **Event** | A message on the in-process bus, streamed to the UI over SSE. |
