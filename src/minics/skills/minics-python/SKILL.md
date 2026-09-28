---
name: minics-python
description: Use MiniCS as a Python library — the AppContext service API for datasets, entries, documents, indexing, retrieval, authoring, chat and export, without launching the UI. Use when automating MiniCS pipelines, scripting in Colab/notebooks, or embedding MiniCS in another tool.
---

# MiniCS as a Python library

MiniCS is a library first; the Flask API and desktop shell are thin layers on
top of a single application context.

```bash
pip install minichat-studio
```

## App context

```python
from minics.services.context import get_context

ctx = get_context()          # uses ~/.minics (or MINICS_HOME)
ctx.ensure_ready()           # create structure + run migrations on first use
# ... work ...
ctx.close()
```

Respect `MINICS_HOME` (or `get_context(home=...)`) to isolate stores — the
test suite runs against throwaway homes this way.

## End-to-end example

```python
from minics.services.context import get_context

ctx = get_context()
ctx.ensure_ready()

# dataset + entries
dataset = ctx.datasets.create("Support QA", description="Ticket answers")
entry = ctx.entries.create(dataset.id, user="What is RRF?", assistant="A fusion method.")

# documents -> index
doc = ctx.documents.import_file("handbook.pdf")
ctx.indexer.index_document(doc.id)
if ctx.graph.is_available():
    ctx.graph_indexer.index_document(doc.id)

# hybrid retrieval
result = ctx.retriever.retrieve("how does fusion work?", top_k=6, use_rag=True, use_graph=True)
print(result.context_text())

# export
content = ctx.collections.export("my-collection", fmt="jsonl", only_approved=True)
ctx.close()
```

## Service map

| Service | Role |
| --- | --- |
| `ctx.config` / `ctx.config_manager` | Read/patch configuration. |
| `ctx.datasets` | Create/list datasets, `stats(id)`. |
| `ctx.entries` | Create/update entries, lifecycle, versions. |
| `ctx.documents` | `import_file`, `import_bytes`, `add_text`, markdown access. |
| `ctx.indexer` / `ctx.graph_indexer` | Vector and graph indexing, `reindex_all()`. |
| `ctx.retriever` | Hybrid retrieval, `retrieve(query, top_k, use_rag, use_graph)`. |
| `ctx.authoring` | Enhance / tags / evaluate / grounded generation. |
| `ctx.collections` | Curate and `export(..., fmt=..., only_approved=...)`. |
| `ctx.chat` | Conversations against the configured model. |
| `ctx.jobs` | Background job manager (same engine the UI streams over SSE). |

## Notes

- Everything is local-first: SQLite (WAL, single writer thread), ChromaDB,
  Ladybug — safe to script, but don't share one store across processes for
  writes.
- Point at any OpenAI-compatible endpoints in config before calling
  LLM-dependent helpers (`authoring`, graph extraction).
