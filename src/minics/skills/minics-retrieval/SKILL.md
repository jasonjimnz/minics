---
name: minics-retrieval
description: Hybrid retrieval in MiniCS — ChromaDB vector search plus Ladybug knowledge-graph topology fused with Reciprocal Rank Fusion (RRF); `minics search` from the terminal, retrieval tuning (top-k, RRF k, graph hops) and graceful degradation. Use when querying the knowledge base or tuning retrieval quality.
---

# MiniCS retrieval

MiniCS retrieves with a **hybrid** engine: ChromaDB vector search **plus**
Ladybug graph topology, fused with **Reciprocal Rank Fusion (RRF)**. Each side
degrades gracefully — if the graph is unavailable, pure vector search is used,
and vice versa.

## From the terminal

```bash
minics search "how does RRF fusion work?"
minics search "sorting algorithms" --top-k 10
minics search "graph entities" --no-graph    # vector only
minics search "raw similarity" --no-rag      # skip RAG pipeline
```

Output is JSON with the fused chunks, scores and the context text ready for
prompt injection (`result.context_text()`).

## How fusion works

1. The query is embedded against the Chroma collection (cosine space).
2. The graph walk expands entity neighbours up to the configured hop count.
3. Both ranked lists are fused with RRF using the configured `rrf_k`.
4. Optionally, a cross-encoder **reranker** reorders the fused pool.
5. The top `top_k` chunks are returned, each traceable to its document.

## Tuning

All knobs live in the Retrieval panel (UI) or config:

```bash
minics config --set '{"retrieval": {"top_k": 8, "rrf_k": 60}}'
```

| Knob | Effect |
| --- | --- |
| `top_k` | Chunks returned / injected into grounded prompts. |
| `rrf_k` | RRF smoothing constant — lower ranks the top hits harder. |
| graph hops | How far the entity walk expands (higher = broader, noisier). |

## Reranking (optional, disabled by default)

`retrieval.rerank` wires a Cohere-compatible `POST /rerank` endpoint
(Cohere, Jina, TEI, vLLM) into the pipeline. When enabled and a model is set,
the fused candidate pool (`rerank.pool`, default 24) is re-scored against the
query and the best `top_k` survive; every chunk then carries `rerank_score`
and a `rerank` rank/source. Enable it via `minics setup --rerank-model ...`
or config:

```bash
minics config --set '{"retrieval": {"rerank": {
  "enabled": true, "model": "bge-reranker-v2-m3",
  "base_url": "http://localhost:7002", "endpoint": "/rerank", "pool": 24}}}'
```

`base_url`/`api_key` fall back to the embedding endpoint. Any endpoint error
degrades gracefully to the fused order (warning event
`retrieval.rerank_failed`, `diagnostics.rerank: false`).

## Requirements

- Vector search needs documents indexed (`minics scan ./docs` or
  `minics reindex`) and a working embeddings endpoint.
- Graph retrieval needs the entity graph built (chat LLM used for extraction).

If results look stale, rebuild: `minics reindex`.
