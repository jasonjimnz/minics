# MiniCS + vLLM on Google Colab: a programmatic knowledge base and dataset studio

This example runs the **entire MiniCS library programmatically** — no UI, no
desktop shell — on a Google Colab GPU runtime, with **vLLM serving two models
in the background**: a chat LLM and an embedding model. It is a complete,
self-contained tour of the Python API: configure a MiniCS home, build a
documental database, run hybrid retrieval, chat with grounding, author
grounded dataset entries, and export to JSONL.

```
                         Google Colab VM (T4 GPU, 16 GB)
┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│   notebook ──► minics library (AppContext)             run_vllm.sh     │
│      │             │                                   (nohup)         │
│      │             ├─► SQLite  /content/minics-home   │       │       │
│      │             ├─► ChromaDB (vectors)             ▼       ▼       │
│      │             ├─► Ladybug  (graph)      vLLM :8001   vLLM :8002  │
│      │             └─► OpenAI protocol ──────► Qwen2.5-1.5B  bge-m3    │
│      │                                        (chat)      (embed)     │
│   /content/sample_docs  ── import ──► convert → chunk → embed → graph   │
└────────────────────────────────────────────────────────────────────────┘
```

**Files in this example:**

| File | Purpose |
| --- | --- |
| [`minics_colab_vllm.ipynb`](minics_colab_vllm.ipynb) | The example notebook (11 sections + troubleshooting). |
| [`run_vllm.sh`](run_vllm.sh) | Launcher: starts both vLLM servers in the background, waits until healthy, `stop` subcommand for cleanup. Dependency install is **not** handled here — it is done from a terminal with the commands documented in the notebook's §2 markdown. The notebook writes an identical copy into the Colab VM so it works standalone.
| [`README.md`](README.md) | This document. |

---

## 1. Prerequisites

**Nothing.** This scenario is designed for someone starting from zero: you
don't install anything on your machine. The Colab runtime already provides
Python; the notebook itself installs vLLM and the MiniCS PyPI package, runs
them, and cleans up.

- A **Google Colab** account with a **GPU runtime** — `Runtime → Change
  runtime type → T4 GPU`. The defaults fit a T4 (16 GB) with room to spare;
  the models total ~4 GB of weights.
- No other accounts, keys or services. Everything stays inside the Colab VM;
  the only network traffic is downloading model weights from Hugging Face
  and PyPI.

The notebook also runs unchanged on **any local Jupyter with an NVIDIA GPU**
(nothing is Colab-specific except one optional `google.colab` import and the
`/content/...` paths).

The launcher script lives in this repo at
`examples/colab-vllm/run_vllm.sh`; on Colab the notebook writes
its own identical copy, but if the runtime has internet access you can pull
it from GitHub instead:

```bash
!wget -q https://raw.githubusercontent.com/jasonjimnz/minics/main/examples/colab-vllm/run_vllm.sh
```

## 2. The two model servers

One vLLM process serves one model, so `run_vllm.sh` starts **two**:

| Server | Default model | Command | Port | Why this model |
| --- | --- | --- | --- | --- |
| Chat LLM | `Qwen/Qwen2.5-1.5B-Instruct` | `vllm serve ... --gpu-memory-utilization 0.45 --max-model-len 16384` | `8001` | Small, strong instruction follower; fits comfortably next to the embedder on a T4. |
| Embeddings | `BAAI/bge-m3` | `vllm serve ... --gpu-memory-utilization 0.30` | `8002` | Multilingual pooling model, **1024 dimensions**, served over the OpenAI `/v1/embeddings` shape MiniCS expects. vLLM auto-detects it as a pooling model from its architecture — no `--task`/`--runner` flag needed (on old vLLM it was `--task embed`, on the newest ones `--runner pooling`). |

Both speak the OpenAI protocol, which is MiniCS's only requirement — the
same notebook works against llama.cpp, Ollama, LM Studio or OpenAI by
changing two URLs.

**Swap models via environment variables** (before running the launcher):

```bash
LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct \
EMBED_MODEL=BAAI/bge-small-en-v1.5 \   # dimension 384
bash run_vllm.sh
```

The same works for the install: the pinned versions and index URL are plain
arguments in the commands above — edit them inline if your VM's driver needs
a different CUDA variant.

> If you change the embedding model, MiniCS must be told: the notebook
> **probes the dimension from the live endpoint** automatically, but the
> Chroma collection from a previous run keeps the old dimensionality. Wipe
> `/content/minics-home/vectordb` and re-run the indexing section.

### Installing the dependencies (from a terminal)

Run once per VM, before starting the servers (full walkthrough in the
notebook's §2 markdown):

```bash
pip install -U uv
uv pip uninstall --system torch torchvision torchaudio
uv pip install --system \
    torch==2.11.0 \
    torchvision==0.26.0 \
    torchaudio==2.11.0 \
    --index-url https://download.pytorch.org/whl/cu130
uv pip install --system vllm "minichat-studio>=0.3.2"
```

On a CUDA-12 Colab image, swap the index to `.../whl/cu128` and pin an older
vLLM release compiled for that variant.

### What `run_vllm.sh` does, step by step

**default subcommand** (start):

1. Runs a preflight — `torch`/`torchaudio`/`torchvision` must import cleanly
   (same-CUDA check), or it fails fast with the fix hint.
2. Kills any previous `vllm serve` processes (idempotent restarts).
3. Starts the chat LLM and the embedder with `nohup`, each logging to
   `/tmp/minics-vllm-logs/{llm,embed}.log`.
4. Polls `GET /health` on both ports until each server is live — first run
   downloads the weights, so allow **5–10 minutes**. If a process dies or
   the timeout (`HEALTH_TIMEOUT`, default 900 s) hits, it prints the last 40
   log lines and exits non-zero.
5. Prints the two `http://127.0.0.1:<port>/v1` base URLs.
6. `bash run_vllm.sh stop` tears everything down (the notebook's final cell).

The GPU fractions (0.45 + 0.30) leave ~25 % of VRAM for activations/KV cache.
On a 24 GB GPU you can raise both and serve bigger models; on CPU-only hosts
add `--device cpu` to both `vllm serve` invocations (slow, but it works).

## 3. The notebook, section by section

| § | Cell(s) | What happens | MiniCS API used |
| --- | --- | --- | --- |
| 1 | `nvidia-smi` | Confirm the GPU runtime. | — |
| 2 | terminal install (markdown) | The §2 markdown documents the dependency install to run **from a terminal** (Colab: *File → New terminal*): uv removes Colab's mismatched torch stack, installs the pinned cu130 family (`torch==2.11.0` / `torchvision==0.26.0` / `torchaudio==2.11.0`), then vLLM + `minichat-studio`. A verification cell imports the whole stack and checks the driver's CUDA level. | — |
| 3 | `run_vllm.sh` | Write the launcher into the VM and start both servers in the background; the launcher polls `/health` until each is live. | — |
| 4 | smoke test | Raw OpenAI-protocol calls: list models, one completion, one embedding (prints the vector size). | — |
| 5 | configure | `MINICS_HOME=/content/minics-home`; create the app context; deep-merge the endpoint config; probe the embedding dimension; mark setup complete. | `get_context`, `ctx.update_config`, `probe_embedding_dimension` |
| 6 | documents | Write two sample markdown docs, import each (→ clean markdown), index (→ chunks + Chroma vectors), wire the graph (→ entity mentions + co-occurrences). | `ctx.documents.import_file`, `ctx.indexer.index_document`, `ctx.graph_indexer.index_document` |
| 7 | retrieval | Hybrid search: vector + graph rankings fused with RRF; inspect per-chunk scores, sources, entities and the `[n]`-numbered `context_text()` block. | `ctx.retriever.retrieve` |
| 8 | grounded chat | Persisted conversation with RAG/Graph/Grounding switches; the answer cites `[n]` sources; usage stats returned. | `ctx.chat.create`, `ctx.chat.send` |
| 9 | authoring | Generate a grounded ChatML entry about a topic, suggest + merge tags, evaluate quality across six dimensions (persisted on the entry). | `ctx.datasets.create`, `ctx.authoring.generate_entry / suggest_tags / evaluate_entry` |
| 10 | export | Create a collection, add the entry, export as JSONL (byte-identical to UI/CLI exports), save to `/content/minics-export.jsonl`. | `ctx.collections.create / add_entries / export` |
| 11 | cleanup | `run_vllm.sh stop` + `ctx.close()` (Chroma, Ladybug, SQLite closed cleanly). | `ctx.close` |

### Why *programmatic* MiniCS?

MiniCS is a library first; the Flask app and PyWebView shell are thin layers
over `AppContext`. This notebook never launches them — which is exactly the
mode you want on a headless VM, in CI, or when embedding MiniCS into another
product. The same home directory remains **portable**: download
`/content/minics-home` and open it with the desktop app
(`MINICS_HOME=/path/to/minics-home minics`) — datasets, entries, documents,
vectors and graph all carry over.

## 4. Running it

1. Open [Colab](https://colab.research.google.com) → `File → Upload notebook`
   → `minics_colab_vllm.ipynb` (or open it from the GitHub repo once pushed).
2. `Runtime → Change runtime type → T4 GPU`.
3. Run the cells top to bottom. Expect:
   - uv install: **2–4 min** (parallel downloads; still allow a few extra minutes on the very first run of the day)
   - first `run_vllm.sh`: **5–10 min** (weight download) — the cell blocks
     until both servers report healthy
   - everything after: seconds
4. At the end, optionally download the two artifacts:
   - `/content/minics-export.jsonl` — the exported dataset,
   - `/content/minics-home` (zip it first) — the whole studio home.

### Cost/time notes

- Free-tier T4 is sufficient; nothing here needs A100s.
- Re-runs after the first are fast: weights stay in the Colab disk cache for
  the session, and MiniCS deduplicates documents by SHA-256.

## 5. Customising

| Want to… | Do this |
| --- | --- |
| Use bigger models | `LLM_MODEL=Qwen/Qwen2.5-3B-Instruct LLM_GPU_FRAC=0.6 bash run_vllm.sh` (T4 fits ~3B qweight + bge-m3). |
| Import real documents | Replace the two sample files in Section 6 with PDFs/DOCX — `import_file` converts them (needs `pypdf`/`python-docx`, bundled with minichat-studio). |
| Skip the graph | Drop the `ctx.graph_indexer...` line; retrieval degrades to vector-only automatically. |
| Turn off import-time LLM cleaning | `ctx.update_config({"app": {"clean_imports_with_llm": False}})` — irrelevant on Colab only if you want to save tokens. |
| Stream chat tokens | Use `ctx.chat.stream(conversation.id, ...)` — yields `retrieval` → `token` → `done` events. |
| Export other formats | `fmt=` one of `chatml`, `jsonl`, `alpaca`, `sharegpt`, `markdown`. |
| Point at a remote endpoint | Change the two base URLs in Section 5 — the notebook no longer needs vLLM at all. |

## 6. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `RuntimeError: Detected that PyTorch and TorchAudio were compiled with different CUDA versions` when starting the servers | The terminal install from §2 was skipped or partially run. Re-run its four commands (uninstall torch family → pinned cu130 reinstall → vLLM), then re-run the launcher — its preflight check fails fast with this exact hint. |
| `nvidia-smi` fails | Runtime has no GPU: `Runtime → Change runtime type → T4 GPU`, then re-run. |
| `CUDA out of memory` | Lower `LLM_GPU_FRAC` / `EMBED_GPU_FRAC`, or switch to `Qwen2.5-0.5B-Instruct` + `bge-small-en-v1.5`. |
| Launcher: "process died" | Read the printed log tail (`/tmp/minics-vllm-logs/llm.log` or `embed.log`). Common causes: no GPU, OOM, or a typo'd model id. |
| 404 on `/v1/embeddings` | The served model is not a pooling model, or the request hit the chat port (8001). Embeddings live on :8002 — vLLM auto-detects pooling models; on old vLLM the flag was `--task embed`, on the newest `--runner pooling`. |
| `Embedding dimension mismatch` warning during indexing | The Chroma collection was created with another dimension. Delete `/content/minics-home/vectordb` and re-index. |
| Chat answers ignore the documents | Ensure Section 6 ran (documents + indexes exist — check `ctx.documents.stats()`), and the conversation was created with `use_grounding=True`. |
| Colab disconnects mid-run | Everything durable lives in `/content/minics-home`; re-run the cells (vLLM restart + `reindex_all` if you want to be safe). |

## 7. Where to go next

- **Serve this knowledge base to a coding agent**: see the MCP example in
  `../mcp-knowledge-base` — the same home can be exposed as
  an MCP server for OpenCode.
  Download `/content/minics-home` from this notebook and hand it to the MCP
  server via `MINICS_HOME` — Colab-built knowledge base, agent-searchable.
- Main docs: [`docs/rag.md`](../../docs/rag.md) for the retrieval pipeline,
  [`docs/llm.md`](../../docs/llm.md) for endpoints and structured output,
  [`docs/api.md`](../../docs/api.md) for the HTTP surface.
