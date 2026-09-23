# RAG & graph engine

How MiniCS turns imported documents into retrievable, citable grounding:
conversion → chunking → entity extraction → vector index + knowledge graph →
hybrid retrieval fused with Reciprocal Rank Fusion.

```
PDF/DOCX/TXT/MD/TeX ──► markdown ──► chunks ──┬─► embeddings ──► ChromaDB (vectors)
                                              └─► entities  ──► Ladybug   (topology)

query ──┬────────────────► Chroma  (semantic)   ──┐
        │                                          ├─► RRF ─► chunks ─► grounding
        └────────────────► Ladybug (topology)     ──┘
```

Everything degrades gracefully: if the graph is unavailable the vector side
still answers, and vice-versa.

---

## 1. Document conversion (`documents/convert.py`)

Every file becomes **markdown** — the canonical text form that is chunked,
mined for entities, shown in the editor, and kept on disk under
`documents/markdown/`.

| Kind | Extensions | Converter |
| --- | --- | --- |
| PDF | `.pdf` | `pypdf`, page by page; broken pages skipped; author/title metadata harvested. |
| DOCX | `.docx` | `mammoth` → HTML → `markdownify` (ATX headings, `-` bullets, images stripped); falls back to `python-docx` (styles → headings/lists, tables → markdown pipes). |
| TXT | `.txt`, `.text` | Encoding-chained read (`utf-8` → `utf-8-sig` → `cp1252` → `latin-1`); ALL-CAPS short lines promoted to `##` headings. |
| Markdown | `.md`, `.markdown` | Passed through. |
| LaTeX | `.tex`, `.latex`, `.ltx` | Math (`$$…$$`, `\[...\]`, `$...$`) stashed first; a regex table maps structure (`\section{}` → `## …`, `\textbf{}` → `**…**`, `\item` → `- `, `\cite{}` → `[…]`); `pylatexenc` strips the rest; math restored. |

`clean_markdown()` (the deterministic one) then tidies: normalises newlines,
removes zero-width characters, rejoins hyphenated line breaks, drops
page-number lines, collapses 3+ blank lines. `convert_file()` returns a
`ConvertedDocument(kind, title, markdown, metadata)` with the title guessed
from metadata / the first `# ` heading / the file stem.

## 2. Chunking (`rag/chunking.py`)

`split_markdown(markdown, chunk_size, chunk_overlap)`:

1. `MarkdownHeaderTextSplitter` splits on `#`–`####`, keeping the heading
   metadata (`h1`–`h4`) and the headers themselves in the text
   (`strip_headers=False`).
2. The heading trail (`h1 › h2 › h3`) is stored per chunk — the graph stores
   it, and the UI shows where a chunk came from.
3. Sections larger than `chunk_size` go through
   `RecursiveCharacterTextSplitter` (`\n\n` → `\n` → `". "` → `" "` → `""`)
   with `chunk_overlap`.
4. Each `Chunk(index, text, heading, tokens, metadata)` gets a cheap token
   estimate (~4 chars/token). Documents with no headings fall back to pure
   recursive splitting.

`split_text()` is the plain-text variant. Chunk sizes come from
`embedding.chunk_size` / `chunk_overlap` (default 1000/150).

## 3. Entity extraction (`rag/entities.py`)

The graph needs stable **topology**, not perfect NLP — so extraction is cheap
and offline-first. `extract_entities(text, max_entities)` gathers four kinds:

| Kind | Source | Weight |
| --- | --- | --- |
| `markup` | `**bold**` or `` `code` `` spans the author emphasised | 2.0 |
| `phrase` | capitalised multi-word sequences ("Reciprocal Rank Fusion"), trailing connectives trimmed | 1.5 |
| `acronym` | ALL-CAPS tokens (RRF, LLM) | 1.5 |
| `term` | frequency-ranked significant words (stop-word filtered, length ≥ 4) | 1.0 + 0.25 × (count − 1) |

Entities are deduplicated case-insensitively (repeat mentions grow
`mentions`), ranked by weight, then capped. `extract_cooccurrence(entities)`
returns `(a, b, weight)` pairs for entities appearing in the same chunk
(capped at 40 pairs).

An optional **LLM enrichment** pass (`AuthoringService.enrich_graph` →
`llm.extract_entities`) adds higher-quality entities per chunk afterwards.

## 4. The knowledge graph (`rag/graph.py`)

**Ladybug** stores the topology in one file (`graphdb/minics.graph`):

```
(Document {id, public_id, title, kind})
   -[:HAS_CHUNK {position}]->  (Chunk {id, document_id, idx, heading})
   -[:NEXT]->                  (Chunk)          # reading order
(Chunk) -[:MENTIONS {weight}]-> (Entity {name, kind, mentions})
(Entity) -[:CO_OCCURS {weight}]-> (Entity)
```

`GraphStore` wraps a `ladybug.Connection` behind an `RLock`:

- **Schema** (`SCHEMA`) is created on first connect; `is_available()` probes
  connectivity (the rest of the app treats the graph as optional).
- **Writes**: `upsert_document`, `clear_document_chunks` (idempotent
  re-indexing), `add_chunk` + `link_next`, `add_mention`
  (`MERGE` entity, accumulate edge weight), `add_cooccurrence`.
- **Reads**: `find_entities` (substring match ranked by mentions),
  `chunks_for_entities` (chunks scored by summed mention weights),
  `neighbors` (`CO_OCCURS*1..hops` expansion), `expand_chunks` (one `NEXT`
  step), `subgraph` (nodes/edges around query terms for the Graph view),
  `stats` (documents/chunks/entities/mentions/cooccurrences).
- `clear()` wipes relationships then nodes for a full rebuild.

`GraphIndexer.index_document()` re-chunks the markdown, rebuilds that
document's chunk nodes, links `NEXT` in reading order, and adds
mentions/co-occurrences per chunk — reporting progress per chunk and checking
cancellation. `search(query)` matches query terms → entities → optional
neighbour expansion (`retrieval.graph_hops`) → chunk ranking → `NEXT`
expansion when short.

## 5. The vector store (`rag/vectorstore.py`)

**ChromaDB** `PersistentClient` in `~/.minics/vectordb`, one collection
(default `minics`), **cosine** space, telemetry off.

- MiniCS embeds text itself (`llm.client.embed_texts`) and hands vectors to
  Chroma — the model, dimension and batching stay under its own config.
- `upsert(ids, embeddings, documents, metadatas)` sanitises metadata to
  scalars (lists become comma-joined strings).
- `query(embedding, n_results, where)` returns hits with
  `score = max(0, 1 - distance)`; `delete_document(document_id)` uses the
  `document_id` metadata filter; `reset()` drops the collection.

## 6. The indexing pipeline (`rag/indexer.py`)

`DocumentIndexer.index_document(ref, progress, job_ctx)`:

1. Load the document + its markdown (empty → status `error`).
2. Chunk with the configured size/overlap.
3. **Embed in batches** (`embedding.batch_size`, default 64), reporting
   progress across the 10%–85% span and checking cancellation between
   batches. A dimension mismatch against `embedding.dimension` publishes a
   warning event.
4. Write to Chroma (`delete_document` then `upsert`) with metadata:
   `document_id`, `document_public_id`, `title`, `chunk_index`, `heading`,
   `kind`, `tags`. Vector ids are deterministic:
   `vector_id_for(doc_id, idx)` → `doc-{id}-chunk-{idx}`.
5. Persist the canonical chunk text to SQLite (`document_chunks`) in one
   transaction — Chroma and SQLite are (re)written together so they cannot
   drift.
6. Set the document `ready` with `chunk_count` and publish
   `document.indexed`.

`remove_document()` clears both stores; `reindex_all()` loops documents,
publishing `document.index_failed` warnings for stragglers.

## 7. Fusion (`rag/fusion.py`)

The two retrievers produce scores on incomparable scales (cosine similarity
vs. entity weights), so MiniCS fuses **ranks**:

```
score(d) = Σ_r  w_r / (k + rank_r(d))
```

- `reciprocal_rank_fusion(rankings, k=60, weights)` — pure id-list version.
- `fuse_hit_lists(rankings, key="chunk_id", k, weights)` — the version used
  in production: merges hit dicts field-by-field (first non-empty wins),
  annotates every hit with `fused_score`, `ranks` (`{"vector": 1, "graph": 4}`)
  and `sources` (`["vector", "graph"]`), and sorts by fused score.

`k = 60` (configurable, `retrieval.rrf_k`) damps the top of each list, making
fusion robust to one retriever being noisy. A retriever with weight ≤ 0 is
skipped entirely.

## 8. Hybrid retrieval (`rag/retriever.py`)

`HybridRetriever.retrieve(query, top_k, use_rag, use_graph, document_ids,
candidates)`:

1. Read defaults from `retrieval.*` settings.
2. **Vector side**: embed the query, `VectorStore.query` with the candidate
   pool (optionally filtered by `document_ids` via a Chroma `$in` filter).
   Failures warn on the bus and return `[]`.
3. **Graph side**: `GraphIndexer.search` (term → entity → chunks). Same
   failure policy.
4. **Fuse** with `fuse_hit_lists`, take `top_k`.
5. **Enrich** from SQLite: canonical chunk text, document titles, heading and
   index — producing `RetrievedChunk` objects carrying
   `vector_score` / `graph_score` / `fused_score` / `ranks` / `sources` /
   `entities`.

`RetrievalResult` adds `used_rag` / `used_graph` / diagnostics and:

- `citations()` → `Citation` objects (kind, ref, title, 280-char snippet,
  score, document_id),
- `context_text(max_chars=8000)` → the numbered grounding block:

  ```
  [1] Handbook — Installation › Requirements
  <chunk text>

  [2] FAQ — Troubleshooting
  <chunk text>
  ```

`build_grounding_block()` pairs the context with its citations — exactly what
the chat service injects into prompts and the UI renders as `[n]` references.

## 9. Retrieval settings at a glance

| Setting | Effect |
| --- | --- |
| `top_k` (8) | Chunks returned after fusion. |
| `candidates` (24) | Pool fetched from each retriever before fusion. |
| `rrf_k` (60) | Fusion damping; higher flattens rank differences. |
| `vector_weight` / `graph_weight` (1.0) | Relative trust per retriever. |
| `graph_hops` (1) | Entity-neighbour expansion depth (1–3). |
| `use_rag` / `use_graph` | Retriever switches (also per conversation). |
| `use_grounding` | Whether retrieved context is actually injected into prompts. |
| `embedding.chunk_size` / `chunk_overlap` | Chunking granularity (re-index after changing). |
