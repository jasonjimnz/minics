# LLM layer

Everything MiniCS does with models lives in `minics/llm`: the OpenAI-protocol
client factory, embeddings, structured output with three fallback strategies,
the prompt library and the authoring helpers. One decision shapes it all:
**every provider is reached through the OpenAI protocol** — OpenAI, Azure-style
gateways, vLLM, llama.cpp, LM Studio, Ollama's OpenAI shim — with no
provider-specific code.

---

## 1. `client.py` — protocol access

### Raw clients

| Factory | Used for |
| --- | --- |
| `build_openai_client(cfg, timeout)` | Model discovery (`models.list`), the ping test, anything needing raw control. |
| `build_async_openai_client(cfg, timeout)` | Async variant for future server-side use. |
| `build_embeddings_client(cfg, timeout)` | The embedding endpoint, falling back to the LLM base URL/key when the embedding section is blank. |

Local endpoints that need no key get the `PLACEHOLDER_KEY` (`"not-needed"`),
because the SDK insists on one.

### Model discovery

- `list_models(base_url, api_key, ...)` returns `ModelInfo` rows and **never
  raises for missing `/models` support** (many local servers omit it) — it
  raises `LLMError` on real failures.
- `is_embedding_model(id)` uses hint substrings (`embed`, `bge`, `e5`, `gte`,
  `nomic`, `mxbai`, `voyage`, …); anything else is chat.
- `split_models` → `{"chat": [...], "embedding": [...]}`; `list_available_models`
  queries both endpoints independently (once, when they coincide).
- `test_connection(cfg)` pings chat (`max_tokens=1`), probes the embedding
  dimension, and lists models — returning a structured report used by the
  setup wizard and Settings screen.

### LangChain wrappers

- `build_chat_model(cfg, model, temperature, max_tokens, **overrides)` →
  `ChatOpenAI` with `max_retries=2`, config-driven temperature/top_p/
  max_tokens/timeout, and `cfg.llm.extra` forwarded verbatim as
  `model_kwargs` (e.g. `{"num_ctx": 8192}` for Ollama).
- `build_embeddings(cfg)` → `OpenAIEmbeddings` with
  **`check_embedding_ctx_length=False`** — critical for local models, so
  tiktoken never tokenises text it doesn't know.
- `embed_texts(texts, cfg)` batches nothing itself but preserves server order
  by `index` (some servers reorder). `probe_embedding_dimension()` embeds one
  short string and returns the vector length.

## 2. `structured.py` — structured output

`invoke_structured(schema, *, system, user, config, model, temperature,
max_tokens)` returns a **validated pydantic object**; callers never parse
JSON. Because OpenAI-compatible servers differ wildly in structured-output
support, it tries the strongest mechanism first and falls back:

| # | Strategy | How |
| --- | --- | --- |
| 1 | **Native structured output** | `chat.with_structured_output(schema).invoke(messages)` — tool calling or `json_schema` depending on the server. |
| 2 | **JSON mode** | `with_structured_output(schema, method="json_mode")` with a `_schema_hint` appended to the user message ("Respond with a single JSON object with these fields: …"). |
| 3 | **Prompt + parse** | Plain completion; `_extract_json` pulls a fenced ```` ```json ```` block or the outermost `{...}`; `schema.model_validate` does the rest. |

Every failure is recorded (`structured: …`, `json_mode: …`, `text: …`) and the
combined message raises `StructuredOutputError`.

### Truncation detection (`OutputTruncatedError`)

A completion cut off by the token limit used to surface as a cryptic
"Could not parse response content as the length limit was reached". Now:

- `_is_truncation(exc)` recognises length-limit wording and
  `finish_reason='length'` markers in exception text (strategies 1 and 2),
- `_finish_reason(response)` inspects `response_metadata` /
  `generation_info` (strategy 3),
- on detection MiniCS **raises `OutputTruncatedError` immediately** with the
  effective limit and the failing strategy — falling back to other strategies
  would truncate identically, so there is no point trying:

  > *The model hit its output token limit (max_tokens=2048) during the
  > 'structured' step, so the structured response was cut off. Increase
  > llm.max_tokens or reduce the input size.*

The effective limit is the `max_tokens` argument or `cfg.llm.max_tokens`.

## 3. `prompts.py` — the prompt library

| Prompt | Used by | Contract |
| --- | --- | --- |
| `FIELD_ENHANCE_SYSTEM` | `enhance_field` | Rewrite one ChatML field; preserve intent/language/facts; no meta commentary; minimal changes when already good. |
| `TAG_SYSTEM` | `suggest_tags` | Short reusable lowercase tags; task-type + domain; never exceed the requested maximum; never repeat existing. |
| `EVALUATION_SYSTEM` | `evaluate` | Score 0–1 on clarity, correctness, completeness, instruction_following, format, safety; overall reflects the weakest important dimension; concrete strengths/issues/suggestions. |
| `GENERATE_ENTRY_SYSTEM` | `generate_entry` | Produce one high-quality ChatML entry (system may be empty); ground every claim in the supplied material. |
| `MARKDOWN_CLEAN_SYSTEM` | `clean_markdown` | Repair extraction artefacts; keep ALL information, order, math, numbers, names, citations; never summarise or rewrite. |
| `ENTITY_SYSTEM` | LLM entity extraction | Compact entity list with kinds (person/organisation/product/method/concept/place/other) and salience 0–1. |

`entry_as_text(system=, user=, assistant=, …)` renders an entry as readable
XML-ish blocks (`<system>…</system>` etc.) for prompts.

## 4. `enhance.py` — authoring helpers

All helpers return validated pydantic objects (`FieldEnhancement`,
`TagSuggestions`, `EvaluationResult`, `GeneratedEntry`, `MarkdownCleanup`,
`EntityExtraction`) via `invoke_structured`.

| Helper | Output budget | Notes |
| --- | --- | --- |
| `enhance_field(role, content, …)` | config default | Context = rest of entry + optional instruction; temperature 0.4. |
| `suggest_tags(…)` | config default | Avoids existing tags; caps at `max_tags`; temperature 0.3. |
| `evaluate(…)` | config default | Clamps score/dimensions into [0, 1] afterwards; grounding material truncated to 4000 chars; temperature 0. |
| `generate_entry(topic, grounding, …)` | config default | Grounding truncated to 6000 chars; temperature 0.8. |
| `clean_markdown(markdown, …)` | **`CLEAN_MAX_TOKENS = 8192`** | See below. |
| `extract_entities(text, …)` | **`ENTITY_MAX_TOKENS = 4096`** | Passage truncated to 6000 chars. |

### Why the bigger budgets

Cleaning **echoes the whole document back** inside `MarkdownCleanup.markdown`,
and extraction output varies across models. The defaults of 8192 / 4096
override the (smaller) global `llm.max_tokens` for these calls only.

### `clean_markdown` — segmentation and the truncation retry

1. Text longer than `max_chars` (default 16 000) is split on paragraph
   boundaries (`_segments`) and each segment is cleaned recursively, then
   joined with `\n\n`.
2. A single segment still fits inside one LLM call — but if it **truncates**
   (`OutputTruncatedError`), the segment is **split in half on paragraph
   boundaries and retried** (`max(len(text) // 2, 1000)`). If a segment cannot
   be split further (one huge paragraph), the truncation error propagates with
   its clear message.
3. Every recursion passes `max_tokens` through, so partial results always join
   into one coherent markdown document.

`enhance_entry(entry, fields, instruction)` is the convenience wrapper used by
the authoring service (per-field calls with the other fields as context), and
`summarize_text()` is a generic text helper for the chat UI via `invoke_text`.

## 5. Where the helpers are used

| Feature | Path |
| --- | --- |
| "✦ Enhance assistant" (entries view) | `POST /api/entries/<ref>/enhance` → `AuthoringService.enhance_entry_fields` → `enhance_field` (optionally grounded, persisted as a new version). |
| "✦ Suggest tags" | `POST /api/entries/<ref>/suggest-tags` → `suggest_tags` (optionally applied). |
| "✓ Evaluate" | `POST /api/entries/<ref>/evaluate` → `evaluate` → `Evaluation` persisted; quality score set. |
| "+ New entry → Generate" | `POST /api/entries/generate` → grounded retrieval + `generate_entry` → new entry. |
| "Clean with LLM" (document editor) | `POST /api/documents/<ref>/clean` → `clean_markdown` written back. |
| "Enrich graph" | `POST /api/documents/<ref>/enrich-graph` → chunk-wise `extract_entities` merged into the graph. |
| Import cleaning | `AppSettings.clean_imports_with_llm` → `DocumentService._maybe_clean` uses the LLM cleaner on import (falls back to the heuristic cleaner on failure). |

All of these run as **background jobs**; the UI tracks them via
`App.watchJob` and the SSE stream.

## 6. Streaming chat

`ChatService.stream()` uses `build_chat_model(...).stream(messages)` and yields
SSE-ready dicts: `{"type": "retrieval", …}`, `{"type": "token", "text": …}`,
`{"type": "error", …}`, `{"type": "done", content, citations, usage, message}`.
Token usage is harvested from `usage_metadata` or `response_metadata.token_usage`.
See [api.md](api.md) for the wire format and [rag.md](rag.md) for how the
grounding block is built.
