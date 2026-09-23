# Libraries

Every runtime dependency declared in `pyproject.toml`, what it does, where it
is used and why it was chosen. MiniCS follows one rule: **prefer small,
well-scoped libraries over frameworks that own your code**.

---

## 1. Web / desktop shell

| Library | Version | Used in | Why |
| --- | --- | --- | --- |
| **Flask** | ≥ 3.0 | `server/app.py`, `server/api/*` | Minimal, explicit web framework. The app factory pattern + blueprints map 1:1 onto MiniCS's module layout; no ORM or auth machinery to fight. Werkzeug (bundled) also powers the threaded dev server inside the desktop shell (`werkzeug.serving.make_server`). |
| **PyWebView** | ≥ 5.0 | `desktop.py` | Renders the local Flask UI inside a native OS window using the system webview. Gives a "desktop app" feel with zero bundling. MiniCS degrades gracefully to the system browser if no GUI backend is available. |

## 2. Config / validation

| Library | Version | Used in | Why |
| --- | --- | --- | --- |
| **Pydantic v2** | ≥ 2.6 | `core/config.py`, `domain/entities.py`, `core/repository.py`, `llm/structured.py` | One library does four jobs: config validation, domain entities, JSON (de)serialisation, and JSON-Schema generation for structured LLM output. Pydantic v2's Rust core keeps model_validate cheap in hot paths. The generic repository inspects `model_fields` annotations to derive SQLite column types (JSON columns, bool columns). |

## 3. LLM + orchestration

| Library | Version | Used in | Why |
| --- | --- | --- | --- |
| **openai** | ≥ 1.40 | `llm/client.py` | Raw OpenAI SDK used directly for model discovery (`client.models.list`), embeddings (`client.embeddings.create`) and the connection test. MiniCS talks to *any* OpenAI-compatible server by swapping `base_url`. |
| **langchain / langchain-core** | ≥ 0.3 | `llm/structured.py`, `services/chat.py`, `llm/enhance.py` | Used sparingly and deliberately: `with_structured_output` (native schema + json_mode strategies), chat message types (`SystemMessage`, `HumanMessage`, `AIMessage`), and `chat.stream()` for token streaming. Everything else is hand-rolled. |
| **langchain-openai** | ≥ 0.2 | `llm/client.py` (`build_chat_model`, `build_embeddings`) | `ChatOpenAI` / `OpenAIEmbeddings` wrappers around the same OpenAI protocol. `check_embedding_ctx_length=False` is set so tiktoken does not try to tokenise unknown local embedding models. |
| **langchain-community** | ≥ 0.3 | dependency umbrella | Kept for compatibility with the LangChain stack; most RAG pieces are implemented locally. |
| **langchain-text-splitters** | ≥ 0.3 | `rag/chunking.py` | `MarkdownHeaderTextSplitter` (splits on `#`–`####` while keeping the heading trail in metadata) and `RecursiveCharacterTextSplitter` (paragraph → sentence → word fallback). Battle-tested splitters instead of a custom parser. |

## 4. Vector + graph stores

| Library | Version | Used in | Why |
| --- | --- | --- | --- |
| **chromadb** | ≥ 0.5, < 2 | `rag/vectorstore.py` | Embedded, persistent vector database (`PersistentClient`, no server process). Cosine distance space; MiniCS computes embeddings itself and hands vectors over, so model/dimension/batching stay in its own config. Telemetry is disabled via `Settings(anonymized_telemetry=False)`. |
| **ladybug** | ≥ 0.17, < 0.19 | `rag/graph.py` | Embedded property-graph database with a Cypher-like query language (`MERGE`, `MATCH … DELETE`). Single-file storage (`graphdb/minics.graph`). Used for the Document → Chunk → Entity topology and `CO_OCCURS` relationships. |

## 5. Document conversion

| Library | Version | Used in | Why |
| --- | --- | --- | --- |
| **pypdf** | ≥ 4.2 | `documents/convert.py` (`pdf_to_markdown`) | Pure-Python PDF text extraction, page by page; a broken page is skipped rather than failing the import. Metadata (author/title) is harvested for the document title. |
| **python-docx** | ≥ 1.1 | `documents/convert.py` (fallback DOCX path) | Second-chance DOCX extraction: paragraphs with heading/list styles mapped to markdown, plus real markdown tables built from DOCX tables. |
| **mammoth** | ≥ 1.8 | `documents/convert.py` (primary DOCX path) | Converts DOCX → semantic HTML, which `markdownify` then turns into clean markdown (ATX headings, `-` bullets, images stripped). |
| **markdownify** | ≥ 0.12 | `documents/convert.py` | HTML → markdown conversion for the mammoth path. |
| **pylatexenc** | ≥ 2.10 | `documents/convert.py` (`latex_to_markdown`) | Final cleanup pass for LaTeX: a regex table handles structure (`\section` → `## …`, `\textbf` → `**…**`, `\item` → `- `, math stashed and restored), then `LatexNodes2Text` strips whatever remains. Falls back to pure regex if the import fails. |

## 6. Dev dependencies

| Library | Version | Why |
| --- | --- | --- |
| **pytest** | ≥ 8.0 | Test runner. `pytest.ini_options` sets `testpaths = ["tests"]`, quiet output. |
| **pytest-cov** | ≥ 5.0 | Coverage when requested (`pytest --cov`). |
| **ruff** | ≥ 0.6 | Linter + import sorting. Config: `line-length = 100`, `target-version = "py310"`, rules `E,F,I,W,UP,B` with `B008` ignored (Flask dependency injection in route defaults). |

## 7. Standard library doing the heavy lifting

A lot of MiniCS is deliberately stdlib-only:

| Module | Where | Purpose |
| --- | --- | --- |
| `sqlite3` | `core/db.py` | The entire persistence layer, including WAL, migrations, and the writer-thread pattern. |
| `threading`, `queue`, `concurrent.futures` | `core/db.py`, `core/events.py`, `core/jobs.py` | Writer thread, pub/sub bus, job pool, minimal futures. |
| `argparse` | `cli.py` | The whole CLI. |
| `http.server` (via werkzeug) | `desktop.py` | The local server the webview points at. |
| `re`, `unicodedata`, `hashlib`, `uuid`, `json` | `core/utils.py`, `documents/convert.py`, `rag/entities.py` | Slugs, IDs, SHA-256 dedupe, LaTeX/text munging, heuristic entity extraction. |
| `pathlib`, `dataclasses` | everywhere | Path management and light-weight value objects (`Chunk`, `Event`, `Job`, `RetrievedChunk`). |

## 8. The front-end (no dependencies at all)

The browser side uses **no JavaScript libraries and no build step**:

- plain ES2020 in four IIFE modules (`api.js`, `ui.js`, `views.js`, `app.js`),
- `fetch` + `ReadableStream` for REST and SSE consumption
  (`EventSource` for the global event feed),
- hand-written markdown renderer and modal/toast system,
- pure CSS custom properties for theming.

Details in [frontend.md](frontend.md).

## 9. What was deliberately *not* used

| Not used | Why not |
| --- | --- |
| SQLAlchemy / an ORM | The data model is simple; the generic pydantic repository covers CRUD without a second query language. |
| Celery / Redis | Background work is thread-pool scale (document imports, embeddings), not distributed-queue scale. |
| React / Vue / a bundler | The UI is a handful of views; a no-build SPA keeps install weight at zero and the code instantly editable. |
| spaCy / an NLP stack | The graph needs topology, not linguistics — regex heuristics plus optional LLM enrichment suffice and keep installs light. |
| LangChain chains/agents | MiniCS needs structured calls and streaming, not orchestration; using only the client wrappers keeps behaviour predictable and debuggable. |
