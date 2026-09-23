# HTTP API

The Flask layer (`minics/server`) is a thin, typed façade over the service
layer. Every endpoint returns the same JSON envelope, long work returns a job,
and live progress streams over Server-Sent Events. The API is what the
built-in SPA consumes — there is no auth layer because the server binds to
`127.0.0.1` by default; keep it that way if you expose it.

---

## 1. Conventions

### Response envelope (`server/deps.py`)

```json
{ "ok": true,  "data": { … } }
{ "ok": false, "error": "human readable message" }
```

Extra keys may be merged at the top level (e.g. `job_response` returns both
`data` and a top-level `job` for backwards compatibility).

### Error mapping

| Exception | HTTP | Body |
| --- | --- | --- |
| `NotFoundError` | 404 | `{ok: false, error}` |
| `FileNotFoundError` | 404 | `{ok: false, error}` |
| `ValueError` | 400 | `{ok: false, error}` |
| `LLMError` | 502 | `{ok: false, error}` |
| `DatabaseError` | 500 | `{ok: false, error}` |

### References

Almost every `<ref>` path segment accepts either the numeric `id` or the
`public_id` (`Service.resolve_id`).

### Background jobs

Anything slow returns **`202 Accepted`** with a job payload instead of the
result:

```json
{
  "ok": true,
  "data": {
    "id": "1a2b3c4d5e6f", "name": "Import 2 document(s)", "source": "api",
    "status": "queued", "progress": 0.0, "message": "", "result": null,
    "error": null, "metadata": {"entry": "ab12cd34"},
    "created_at": 1758..., "started_at": null, "finished_at": null,
    "duration": null
  },
  "job": { … same … }
}
```

Poll `GET /api/jobs/<id>` or subscribe to `/api/events`; the status moves
`queued → running → success | error | cancelled`, `progress` spans 0–1 and
`result` holds the payload on success.

---

## 2. System (`server/api/system.py`)

| Method & path | Purpose |
| --- | --- |
| `GET /` | The SPA (renders `index.html` with a config bootstrap). |
| `GET /healthz` | Minimal liveness: `{ok, version}`. |
| `GET /api/health` | Version, home path, `ready`, `setup_complete`, `missing` requirements. |
| `GET /api/config` | Full config with masked API keys + `missing_requirements`. |
| `PUT /api/config` | Deep-merge a patch; returns the updated public config. |
| `POST /api/config/test` | Apply an optional patch, then run the connection test (chat ping + embedding probe + model list). |
| `POST /api/config/setup` | Same as test; on success flags `setup_complete`. |
| `GET /api/config/models?kind=chat|embedding&base_url=&api_key=` | List models from the given endpoint (falls back to configured values; a masked key resolves to the stored one). |
| `POST /api/config/embedding-dimension` | Apply an optional patch, probe the dimension, persist it, return `{dimension}`. |
| `GET /api/overview` | Dashboard counts: datasets, entries (total/approved/drafts/in_review), document stats, graph stats, chunk totals, `ready`. |

## 3. Datasets (`server/api/datasets.py`)

| Method & path | Purpose |
| --- | --- |
| `GET /api/datasets?search=&tag=&limit=&offset=` | Page datasets (each with `stats`: entries, by_status, approved). |
| `POST /api/datasets` | `{name, description?, tags?, source?, metadata?, settings?}` → 201. |
| `GET /api/datasets/<ref>` | One dataset + stats. |
| `PATCH /api/datasets/<ref>` | Update fields (name re-slugs). |
| `DELETE /api/datasets/<ref>` | Delete (entries cascade). |
| `GET /api/datasets/<ref>/stats` | Stats only. |
| `GET /api/datasets/<ref>/entries?status=&search=&limit=&offset=` | The dataset's entries. |

## 4. Entries (`server/api/entries.py`)

### CRUD

| Method & path | Purpose |
| --- | --- |
| `GET /api/entries?dataset=&status=&search=&tag=&limit=&offset=` | Page entries (`items` + `total`). |
| `POST /api/entries` | Create from `{messages}` or `{system, user, assistant}` plus dataset/tags/status/notes/source/metadata → 201. |
| `POST /api/entries/bulk` | `{entries: [chatml…], dataset?, status?}` → 201 with created count. |
| `GET /api/entries/<ref>` | Entry + `validation` (structural problems) + collections containing it. |
| `PATCH /api/entries/<ref>` | Update fields; message changes bump `version` and snapshot; `reason` overrides the snapshot label. |
| `DELETE /api/entries/<ref>` | Delete. |
| `GET /api/entries/<ref>/versions` | Version history (newest first). |
| `GET /api/entries/<ref>/validate` | `{valid, problems}`. |
| `POST /api/entries/<ref>/status` | `{status}` → set draft/in_review/approved/rejected. |
| `POST /api/entries/<ref>/tags` | `{tags: [...]}` merged in (deduplicated). |

### LLM authoring (all return 202 + job)

| Method & path | Body |
| --- | --- |
| `POST /api/entries/<ref>/enhance` | `{fields: ["assistant"], instruction?, use_grounding?, persist?, model?}` |
| `POST /api/entries/<ref>/suggest-tags` | `{max_tags?, add?, model?}` |
| `POST /api/entries/<ref>/evaluate` | `{use_grounding?, model?}` |
| `POST /api/entries/generate` | `{topic, dataset?, system_hint?, use_grounding?, tags?, model?}` — persists a new entry. |

### Grounding preview

| Method & path | Purpose |
| --- | --- |
| `POST /api/entries/<ref>/grounding` | `{query?, use_rag?, use_graph?, top_k?}` — retrieval result the entry would be grounded with (query defaults to system + user text). |

## 5. Collections & export (`server/api/collections.py`)

| Method & path | Purpose |
| --- | --- |
| `GET /api/collections?search=&dataset=` | List (includes available `formats`). |
| `POST /api/collections` | `{name, description?, dataset?, tags?, entry_ids?, metadata?}` → 201. |
| `GET /api/collections/<ref>` | Collection + stats + entries. |
| `PATCH /api/collections/<ref>` | Update fields. |
| `DELETE /api/collections/<ref>` | Delete (membership join rows cascade). |
| `POST /api/collections/<ref>/entries` | `{entries: [refs…]}` appended in order. |
| `PUT /api/collections/<ref>/entries` | Replace membership wholesale. |
| `DELETE /api/collections/<ref>/entries` | `{entries: [refs…]}` removed. |
| `GET /api/collections/<ref>/export?format=chatml|jsonl|alpaca|sharegpt|markdown&include_metadata=&only_approved=` | File download with `Content-Disposition` (`<slug>.json/.jsonl/.md`). |

Export shapes: **chatml/jsonl** `{"messages": [...]}` (metadata optional);
**alpaca** `{system, instruction, input, output}`; **sharegpt**
`{"conversations": [{from: human|gpt|system, value}]}`; **markdown** readable
blocks with status/tags/quality.

## 6. Documents (`server/api/documents.py`)

| Method & path | Purpose |
| --- | --- |
| `GET /api/documents/supported` | Accepted extensions and kinds. |
| `GET /api/documents?search=&status=&limit=&offset=` | List + library stats. |
| `POST /api/documents` (multipart `files`, `tags`, `index`) | Upload → **202 + job** (convert → clean → index → graph). |
| `POST /api/documents` (JSON `{title, markdown, index?}`) | Create a markdown note → document + optional index job. |
| `GET /api/documents/<ref>` | Document + markdown + chunks. |
| `DELETE /api/documents/<ref>` | Remove vector chunks, graph nodes and files. |
| `GET /api/documents/<ref>/markdown` | Raw markdown (`text/markdown`). |
| `PUT /api/documents/<ref>/markdown` | `{markdown, reindex?}` — save (and optionally re-index). |
| `POST /api/documents/<ref>/index` | Re-index this document → 202 + job. |
| `POST /api/documents/<ref>/clean` | LLM markdown cleanup → 202 + job. |
| `POST /api/documents/<ref>/enrich-graph` | `{max_entities?, model?}` — LLM entity extraction into the graph → 202. |
| `POST /api/documents/reindex` | `{graph?: true}` — re-index everything (60% vector, 40% graph progress) → 202. |

Import dedupes by SHA-256: re-uploading the same bytes returns the existing
document.

## 7. Chat (`server/api/chat.py`)

| Method & path | Purpose |
| --- | --- |
| `GET /api/chat/conversations` | List with message counts. |
| `POST /api/chat/conversations` | `{title?, system_prompt?, use_rag?, use_graph?, use_grounding?, dataset?}` → 201. |
| `GET /api/chat/conversations/<ref>` | Conversation + messages. |
| `PATCH /api/chat/conversations/<ref>` | Update title/system prompt/switches. |
| `DELETE /api/chat/conversations/<ref>` | Delete. |
| `GET /api/chat/conversations/<ref>/messages` | History. |
| `POST /api/chat/conversations/<ref>/messages` | Non-streaming send → full answer + citations + retrieval info. |
| `DELETE /api/chat/conversations/<ref>/messages` | Clear history. |
| `POST /api/chat/conversations/<ref>/stream` | SSE streaming send (see below). |
| `POST /api/chat/conversations/<ref>/retrieve` | `{query, use_rag?, use_graph?, top_k?}` — preview retrieval without touching the transcript. |
| `GET /api/chat/conversations/<ref>/citations` | All citations stored on the conversation's messages. |

### Streaming wire format

`POST …/stream` responds `text/event-stream`. Each frame is
`event: <type>` + `data: <json>`:

| Event | Payload |
| --- | --- |
| `retrieval` | `{retrieval: RetrievalResult.to_dict(), grounding: bool}` — emitted first, before generation. |
| `token` | `{text}` — incremental answer text. |
| `error` | `{error}` — model failure; the stream ends after this. |
| `done` | `{content, citations, usage, message}` — final accumulated answer; the assistant message is persisted before this fires. |

Keep-alives appear as SSE comment frames (`: keep-alive`).

## 8. Jobs & events (`server/api/jobs.py`)

| Method & path | Purpose |
| --- | --- |
| `GET /api/jobs` | All jobs (newest first semantics via client) + `active` count. |
| `GET /api/jobs/<id>` | One job. |
| `POST /api/jobs/<id>/cancel` | Cooperative cancellation. |
| `POST /api/jobs/cancel-all` | Cancel every non-terminal job. |
| `GET /api/events?after=<id>&job=<id>` | **SSE stream** of the global event bus (replays history after `after`, optionally filtered to one job). |
| `GET /api/events/history?after=&limit=` | Recent events as JSON. |

### Global event stream

Frames carry the event `type` as the SSE event name and the full event dict as
data: `id, type, message, level, progress, source, data, ts, job_id`. Common
types: `job.queued/started/progress/log/error/finished/cancelling`,
`document.created/converted/indexed/index_failed`,
`graph.indexed/index_failed`, `dataset.*`, `entry.*`, `collection.*`,
`chat.*`, `retrieval.vector_failed`, `embedding.dimension_mismatch`.

## 9. Retrieval & graph (`server/api/retrieval.py`)

| Method & path | Purpose |
| --- | --- |
| `POST /api/retrieval/search` | `{query, top_k?, use_rag?, use_graph?, candidates?, document_ids?}` → fused `RetrievalResult`. |
| `GET /api/retrieval/status` | Vector index summary, graph availability + stats, retrieval settings. |
| `GET /api/graph/subgraph?q=&limit=` | Nodes/edges around entities matching `q` (for the Graph view). |
| `GET /api/graph/entities?q=&limit=` | Matching entities ranked by mentions. |
| `POST /api/graph/rebuild` | Clear and rebuild the whole graph → 202 + job. |

## 10. A worked example

```bash
# 1) upload and index a document (job-based)
JOB=$(curl -s -F files=@handbook.pdf http://127.0.0.1:8765/api/documents | jq -r .job.id)

# 2) watch it finish
curl -s http://127.0.0.1:8765/api/jobs/$JOB | jq .data.status

# 3) search it
curl -s -X POST http://127.0.0.1:8765/api/retrieval/search \
  -H "Content-Type: application/json" \
  -d '{"query": "installation requirements", "top_k": 5}' | jq .data.chunks[0]

# 4) stream a grounded chat answer
CONV=$(curl -s -X POST http://127.0.0.1:8765/api/chat/conversations \
  -H "Content-Type: application/json" -d '{"title": "Demo"}' | jq -r .data.public_id)
curl -N -X POST http://127.0.0.1:8765/api/chat/conversations/$CONV/stream \
  -H "Content-Type: application/json" -d '{"content": "How do I install it?"}'
```
