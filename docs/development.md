# Development

Everything you need to hack on MiniCS: environment setup, how the tests work,
code style, how to extend the schema, and how the pieces are meant to evolve.

---

## 1. Environment

```bash
git clone <repo> && cd minics
python -m venv .venv
.venv\Scripts\activate            # Windows   (source .venv/bin/activate on Unix)
pip install -e ".[dev]"
```

- Python **≥ 3.10** (developed on 3.13).
- `pip install -e .` gives you the `minics` console script wired to
  `minics.cli:main`.
- Dev extras: `pytest`, `pytest-cov`, `ruff`.

Run the app from source:

```bash
minics init && minics setup       # point at any OpenAI-compatible endpoint
minics --debug                    # desktop shell with debug tools
minics serve --port 8800          # or browser-only
```

Point the UI at your own servers (vLLM, llama.cpp, LM Studio, Ollama) or at
OpenAI itself; the connection test verifies chat + embeddings before setup is
marked complete.

## 2. Running the tests

```bash
pytest -q                         # the whole suite, no network required
pytest tests/test_llm.py -q       # one module
pytest --cov=minics --cov-report=term-missing
ruff check src tests              # lint (must pass before commit)
```

The suite needs **no model server**: `tests/conftest.py` fakes embeddings and
isolates the home directory.

### Fixtures (`tests/conftest.py`)

| Fixture | What it provides |
| --- | --- |
| `fake_embed` | Deterministic 8-dimensional embeddings monkeypatched into `minics.rag.indexer` and `minics.rag.retriever`, so indexing and retrieval run offline. |
| `home` | Sets `MINICS_HOME` to a fresh `tmp_path` — every test gets an isolated `~/.minics`. |
| `ctx` | A fully wired `AppContext` (config manager, migrated database, event bus) on that home; closed afterwards. |
| `client` | A Flask test client built from `create_app(ctx)` with `TESTING=True`. |
| `_cleanup_managers` (autouse) | Resets the global job manager and `MINICS_HOME` after each test. |

### Test modules

| File | Covers |
| --- | --- |
| `test_core.py` | Config manager (masking, deep merge, atomic writes), paths, utils, repository mapping, database writer/transactions. |
| `test_services.py` | Dataset/entry/collection/document services, versioning, export formats. |
| `test_rag.py` | Chunking, entity extraction, fusion maths, vector store, graph store, retriever (with fake embeddings). |
| `test_llm.py` | Model discovery/splitting, structured-output truncation handling, markdown-cleanup retry. |
| `test_api.py` | HTTP endpoints through the Flask test client. |
| `test_cli.py` | CLI commands. |

### Writing tests

- Use the `ctx` fixture for service-level work and `client` for HTTP; both
  share the same isolated home.
- LLM-touching code should be monkeypatched (see the `_FakeChat` pattern in
  `test_llm.py`, which replaces `minics.llm.structured.build_chat_model`).
- Never depend on the real `~/.minics`; the `home` fixture guarantees
  isolation.

## 3. Code style

Ruff enforces the rules (`pyproject.toml`): `line-length = 100`,
`target-version = "py310"`, rule sets `E, F, I, W, UP, B` with `B008` ignored
(Flask dependency injection). Conventions used throughout:

- **Type hints everywhere**, `from __future__ import annotations` at the top.
- **Module docstrings explain the *why*** — each module opens with the design
  rationale, not just a description.
- Services are stateless façades; business rules live there, raw SQL stays in
  repositories/migrations.
- Errors are typed exceptions (`LLMError`, `NotFoundError`, `DatabaseError`,
  `VectorStoreError`, `GraphStoreError`, `StructuredOutputError`) mapped once
  in `server/deps.py`.
- Events for anything a user can observe: services `emit(...)`; jobs report
  progress via `JobContext`.
- `# noqa: BLE001` marks deliberate broad excepts in graceful-degradation
  paths.

## 4. Schema migrations

The database shape lives in `core/schema.py` as an ordered list. To change it:

1. **Never edit a released migration** — SQLite files in the wild already
   applied it.
2. Append `Migration(version=N+1, name="describe_change", statements=(...))`
   with idempotent statements (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ...`).
3. If a domain entity changed, mirror it in `domain/entities.py` — the
   generic repository maps columns automatically (annotations decide JSON vs
   bool vs scalar; `column_map` renames like `index → idx`).
4. Bump nothing else; `Database.migrate()` applies the new version on next
   start and logs it in `schema_log`.

## 5. Common change recipes

| Task | Touch points |
| --- | --- |
| New config key | `core/config.py` (pydantic field) → Settings card in `views.js` → document it in [configuration.md](configuration.md). |
| New REST endpoint | New/edited blueprint in `server/api/` → service method → tests in `test_api.py` → [api.md](api.md). |
| New LLM feature | Prompt in `llm/prompts.py` → pydantic schema + helper in `llm/enhance.py` → service method in `services/authoring.py` → endpoint + UI action (background job). |
| New document format | `SUPPORTED_EXTENSIONS` + converter in `documents/convert.py`; add a dev dependency only if unavoidable. |
| New event type | Publish via `ctx.bus.publish(...)` (services) or `JobContext.log/update`; it reaches SSE and the Activity log automatically. |
| New theme | One `[data-theme="..."]` block of CSS variables in `app.css` + entry in `UI.THEMES` (`ui.js`). |
| New graph query | `GraphStore` read method using `rows(...)` → expose via `GraphIndexer` → endpoint in `api/retrieval.py` if the UI needs it. |

## 6. Project conventions worth knowing

- **Everything through the context.** Never construct services with raw
  dependencies; pull them from `AppContext` so caching, config epochs and
  shutdown stay correct.
- **Deterministic ids for vectors.** `vector_id_for(document_id, index)` is
  the contract between SQLite chunks, Chroma and the graph — re-indexing
  relies on it being stable.
- **Truncation-aware LLM calls.** Any helper that echoes large input back
  should pass an explicit `max_tokens` and react to `OutputTruncatedError`
  (see `clean_markdown` for the split-and-retry pattern).
- **Progress spans.** Indexing maps embedding progress into 10%–85% of a job;
  imports give each file an equal span and the indexer a 40% slice. Keep new
  jobs composable the same way.
- **The bus is the UI contract.** If the frontend should react to something,
  publish an event rather than inventing a poll.

## 7. Release notes workflow

- Version lives in `pyproject.toml` and is read
  by `minics/__init__.py` for the UI badge, `/healthz` and cache busting.
- The project moves in small, versioned increments; `git log` is the changelog.
- Before committing:

```bash
pytest -q
ruff check src tests
```
