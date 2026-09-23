# Configuration

All configuration lives in one file — `~/.minics/config.json` — managed by
`core/config.py` (`Config`, `ConfigManager`). It is the single source of truth
for how MiniCS talks to the LLM/embedding endpoints and how it behaves.

---

## 1. Where it lives

```
~/.minics/config.json
```

Override the whole home directory with the `MINICS_HOME` environment variable
(`core/paths.py:ENV_HOME`). Tests use this to run against throwaway homes.

Writes are **atomic**: the payload goes to a temp file in the same directory,
is fsynced, then `os.replace`d over the target — a crash can never leave a
half-written config (`ConfigManager._atomic_write`).

## 2. The schema

The config is four pydantic sections inside `Config`:

### `llm` — chat endpoint (`LLMSettings`)

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `base_url` | str | `""` | OpenAI-compatible base URL, e.g. `http://localhost:11434/v1`. Trailing slashes stripped by validator. |
| `api_key` | str | `""` | May be empty for local servers (`not-needed` placeholder is sent instead). |
| `model` | str | `""` | Default chat model name. |
| `temperature` | float | `0.7` | 0.0–2.0. |
| `top_p` | float | `1.0` | Nucleus sampling. |
| `max_tokens` | int | `2048` | Completion budget for chat calls. Long-output tasks (markdown cleaning, entry generation) pass their own larger budget — see [llm.md](llm.md). |
| `timeout` | float | `120.0` | HTTP timeout in seconds. |
| `extra` | dict | `{}` | Extra body params forwarded verbatim as `model_kwargs` to `ChatOpenAI` (e.g. `{"num_ctx": 8192}`). |

### `embedding` — embedding endpoint (`EmbeddingSettings`)

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `base_url` / `api_key` | str | `""` | Fall back to the LLM endpoint when blank (`embedding_base_url` / `embedding_api_key` properties). |
| `model` | str | `""` | Embedding model name. |
| `dimension` | int | `0` | Vector size. **Required** (`> 0`) before MiniCS is "ready": Chroma collections are created with an explicit dimensionality, and the indexer warns on mismatch. Auto-detected by probing with a test string. |
| `batch_size` | int | `64` | Chunks per embedding request during indexing. |
| `chunk_size` / `chunk_overlap` | int | `1000` / `150` | Chunking for indexing (characters). |
| `timeout` | float | `120.0` | HTTP timeout. |

### `retrieval` — hybrid retrieval defaults (`RetrievalSettings`)

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `top_k` | int | `8` | Final chunks returned per retrieval. |
| `candidates` | int | `24` | Per-retriever candidate pool before fusion. |
| `rrf_k` | int | `60` | RRF damping constant — bigger flattens rank differences. |
| `vector_weight` / `graph_weight` | float | `1.0` / `1.0` | Retriever weights in the fusion sum. |
| `graph_hops` | int | `1` | Entity-neighbour expansion hops (1–3). |
| `use_rag` / `use_graph` / `use_grounding` | bool | all `true` | Per-conversation defaults; chat conversations store their own copy of these three switches. |

### `app` — desktop/server behaviour (`AppSettings`)

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `theme` | str | `"system"` | Theme id persisted server-side; the UI also caches it in `localStorage`. |
| `language` | str | `"en"` | Reserved for i18n. |
| `host` / `port` | str/int | `127.0.0.1` / `8765` | Server bind address; the desktop shell picks a free port starting from this one. |
| `open_browser` | bool | `false` | `minics serve` opens the browser. |
| `window_width` / `window_height` | int | `1360` / `900` | PyWebView window size (min 900×600). |
| `log_level` | str | `"INFO"` | Reserved for logging setup. |
| `max_workers` | int | `4` | Background job thread pool size (1–32). |
| `sqlite_busy_timeout` | float | `5.0` | SQLite `busy_timeout` in seconds. |
| `clean_imports_with_llm` | bool | `true` | Run the LLM cleanup pass on imported markdown (in addition to the heuristic cleaner). |

## 3. Readiness

`Config.missing_requirements()` returns what is still missing:

- `llm.base_url`, `llm.model`,
- `embedding.model`, `embedding.base_url`, `embedding.dimension > 0`.

`Config.is_ready()` is `true` when that list is empty. The dashboard's
"Getting started" checklist and the top-bar **ready/setup** pill both read
`/api/health`, which exposes `ready` and `missing`. `setup_complete` flips to
`true` once the setup wizard's connection test succeeds
(`ConfigManager.mark_setup_complete`).

## 4. Secrets handling

API keys are masked before the config leaves the server:

- `Config.public_dict()` replaces `llm.api_key` / `embedding.api_key` with
  `********` (`SECRET_MASK`) and adds `api_key_set` booleans.
- When the UI submits settings, a value equal to `********` means "unchanged"
  — `ConfigManager.update()` swaps the mask back for the stored value
  (`config.py:203-206`). The browser never sees or re-sends real keys.

## 5. Changing configuration

### Setup wizard (interactive)

```bash
minics setup
```

Asks for LLM base URL/key/model and embedding base URL/key/model (listing
available models from the endpoint when reachable), applies optional
`--temperature` / `--max-tokens`, probes the embedding dimension
automatically, and runs a connection test by default. Non-interactive mode
activates when `--base-url`, `--model` or `--embedding-model` is passed.

### CLI one-liner

```bash
minics config --set '{"llm": {"max_tokens": 8192}}'
```

`--set` takes a JSON object that is **deep-merged** into the current config
(`_deep_merge`), so you can patch a single nested key.

### REST API

```bash
curl -X PUT http://127.0.0.1:8765/api/config \
     -H "Content-Type: application/json" \
     -d '{"retrieval": {"top_k": 12}}'
curl -X POST http://127.0.0.1:8765/api/config/test -d '{}' -H "Content-Type: application/json"
curl -X POST http://127.0.0.1:8765/api/config/setup -d '{}' -H "Content-Type: application/json"
```

The Settings screen in the UI builds the same patches client-side and calls
`PUT /api/config`.

### In Python

```python
ctx.update_config({"app": {"max_workers": 8}})
```

## 6. How changes propagate

`AppContext.update_config()` bumps an `llm_epoch` counter and evicts the cached
vector store. The next access to `ctx.vectorstore` rebuilds the Chroma
collection with the current `embedding.dimension` — so changing the embedding
model/dimension takes effect immediately for subsequent indexing, while
previously indexed vectors stay until re-indexed. Everything else (services,
repositories, job manager) reads `ctx.config` live on each access.

Connection-related endpoints that accept a config patch
(`POST /api/config/test`, `/api/config/setup`, `/api/config/embedding-dimension`)
apply the patch *before* running, so you can test unsaved settings from the
Settings screen.

## 7. Environment variables

| Variable | Purpose |
| --- | --- |
| `MINICS_HOME` | Redirect the entire home directory (config, db, stores, documents). Used by the test suite. |
