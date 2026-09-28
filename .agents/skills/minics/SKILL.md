---
name: minics
description: Use MiniCS (minichat-studio) — a local-first studio for building high quality LLM datasets with hybrid RAG + knowledge-graph grounding. Covers the full workflow: setup, document ingestion (`minics scan`), dataset authoring, retrieval, grounded chat, curation and export. Use when the user mentions MiniCS, minics CLI, ChatML datasets, grounding documents, or wants to build/tune a dataset from local files.
---

# MiniCS

MiniCS Lite (**Mini ChatML Studio Lite**) is a local-first studio for building
high quality LLM datasets. It combines a ChatML-aware dataset library, a hybrid
RAG + knowledge-graph grounding engine, LLM authoring helpers and a markdown
editor in one desktop app. Everything lives in `~/.minics` (override with
`MINICS_HOME` or `--home`).

**OpenAI-protocol first.** Any OpenAI-compatible endpoint works: OpenAI,
vLLM, llama.cpp (`llama-server`), LM Studio, Ollama's OpenAI shim, gateways.

## Core concepts

| Concept | Meaning |
| --- | --- |
| **Dataset** | Top-level container for training examples. |
| **Entry** | One ChatML conversation (system/user/assistant messages) with draft → review → approved workflow and automatic versioning on every message edit. |
| **Document** | An imported source file (PDF, DOCX, TXT, Markdown, LaTeX) converted to clean markdown, chunked and indexed. |
| **Collection** | Curated set of approved entries destined for export. |
| **Grounding** | Hybrid retrieval = ChromaDB vectors + Ladybug graph topology, fused with Reciprocal Rank Fusion (RRF). |

## The standard workflow

```bash
minics init                      # create ~/.minics
minics setup                     # interactive LLM + embedding wizard (or use flags)
minics scan ./my-docs            # bulk-import every compatible document in a tree
minics                           # launch the desktop app
```

Then, in the app or CLI: author/evaluate entries → curate a collection →
export. Every long operation is streamed live.

## Sub-skills

Load the specific sub-skill for the task at hand:

| Sub-skill | Use it for |
| --- | --- |
| `minics-setup` | Wiring LLM/embedding endpoints, `minics setup`, `minics models`, troubleshooting connections. |
| `minics-documents` | Importing and bulk-scanning directories (`minics scan`), indexing, reindexing, document formats. |
| `minics-datasets` | Creating datasets and ChatML entries, entry lifecycle, validation. |
| `minics-authoring` | LLM-assisted authoring: enhance, suggest tags, evaluate quality, grounded generation. |
| `minics-retrieval` | Hybrid retrieval (vector + graph), `minics search`, tuning top-k/RRF. |
| `minics-chat` | Grounded chat conversations, RAG/graph/grounding toggles, citations. |
| `minics-export` | Collections and exporting to ChatML, JSONL, Alpaca, ShareGPT, Markdown. |
| `minics-python` | Using MiniCS as a Python library (`minics.services.context.AppContext`). |
| `minics-server` | Headless serving: `minics serve`, Docker/GHCR image, reverse proxies. |

## Quick CLI reference

```
minics init                      create the store
minics setup [--base-url ...]    configure LLM + embedding endpoints
minics models                    list models from the endpoint
minics scan <dir> [flags]        bulk-import all compatible documents in a tree
minics documents [--import F]    import/list/index documents
minics reindex                   rebuild vector index + graph
minics search "query"            hybrid retrieval from the terminal
minics datasets --create NAME    list/create datasets
minics entries [--dataset ID]    list entries
minics export <collection>       export a collection (-o file --format jsonl)
minics serve / minics app        browser server / desktop shell
minics skills install            install the MiniCS agent skillset (.agents/skills)
minics info                      show resolved paths and state
```

## Where data lives

```
~/.minics/
├── config.json        LLM / embedding / retrieval / app settings
├── minics.sqlite3     datasets, entries, collections, documents, chats (WAL)
├── vectordb/          ChromaDB persistent store (cosine)
├── graphdb/           Ladybug graph database
├── documents/
│   ├── originals/     untouched uploads (provenance)
│   └── markdown/      cleaned markdown used for chunking + grounding
```

## Principles

- **Local-first**: no cloud, no accounts, no telemetry.
- **OpenAI-protocol only** for model traffic.
- **Lite by design**: the compact edition of ChatML Studio + Tyness.
- **Python 3.12+**, runs on Linux, macOS and Windows.
