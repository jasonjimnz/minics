# Example: MiniCS + vLLM on Google Colab

Run the **whole MiniCS library programmatically** — no UI, no desktop shell —
on a free **Google Colab** GPU runtime, with **vLLM serving two models in the
background**: a chat LLM and an embedding model. The example builds a complete
knowledge base end to end: documents → hybrid retrieval → grounded chat →
dataset authoring → JSONL export.

Everything lives in [`examples/colab-vllm/`](https://github.com/jasonjimnz/minics/tree/main/examples/colab-vllm):

| File | Purpose |
| --- | --- |
| [`minics_colab_vllm.ipynb`](https://github.com/jasonjimnz/minics/blob/main/examples/colab-vllm/minics_colab_vllm.ipynb) | The example notebook (11 sections + troubleshooting). |
| [`run_vllm.sh`](https://github.com/jasonjimnz/minics/blob/main/examples/colab-vllm/run_vllm.sh) | Launcher: starts both vLLM servers in the background, waits until healthy; `stop` cleans up. The notebook writes an identical copy into the VM. |
| [`README.md`](https://github.com/jasonjimnz/minics/blob/main/examples/colab-vllm/README.md) | Full walkthrough, model table and troubleshooting. |

---

## Why a T4 GPU and small models

The example is tuned for **Colab's free T4 runtime (16 GB VRAM)**, so it uses
small but capable models that fit side by side:

| Server | Default model | Port | OpenAI surface |
| --- | --- | --- | --- |
| Chat LLM | `Qwen/Qwen2.5-1.5B-Instruct` (16K context) | `8001` | `/v1/chat/completions` |
| Embeddings | `BAAI/bge-m3` (1024 dims, auto-detected pooling model) | `8002` | `/v1/embeddings` |

Both speak the OpenAI protocol — MiniCS's only requirement — so the same
notebook works against llama.cpp, Ollama, LM Studio or OpenAI by changing two
URLs. On a bigger GPU, swap in larger models via environment variables.

## Quick start

1. Open `minics_colab_vllm.ipynb` in Colab and set the runtime to
   **T4 GPU** (`Runtime → Change runtime type`).
2. Open a **terminal** in Colab (*File → New terminal*) and run the
   dependency install documented in the notebook's §2 (uv removes Colab's
   mismatched torch stack, installs a pinned cu130
   `torch`/`torchvision`/`torchaudio`, then vLLM + `minichat-studio`).
3. Run the notebook top to bottom: the launcher writes both servers, waits
   for `/health`, then the notebook configures MiniCS programmatically and
   runs the full flow.

## What the notebook covers

| § | Section | MiniCS API |
| --- | --- | --- |
| 5 | Configure a MiniCS home programmatically | `get_context`, `ctx.update_config`, `probe_embedding_dimension` |
| 6 | Build the documental database (import → index → graph) | `ctx.documents.import_file`, `ctx.indexer.index_document`, `ctx.graph_indexer.index_document` |
| 7 | Hybrid retrieval (vector + graph fused with RRF) | `ctx.retriever.retrieve` |
| 8 | Grounded chat with `[n]` citations | `ctx.chat.create`, `ctx.chat.send` |
| 9 | Dataset authoring (generate, tag, evaluate) | `ctx.authoring.generate_entry / suggest_tags / evaluate_entry` |
| 10 | Curate a collection and export to JSONL | `ctx.collections.*` |

MiniCS is used purely as the **published PyPI package**
(`pip install minichat-studio`) — no editable or source installs. The
resulting `/content/minics-home` is a portable MiniCS home: download it and
open it with the desktop app or point the `MINICS_HOME` of any tooling at it.

## Troubleshooting

The notebook ends with a troubleshooting table (CUDA mismatches, OOM, 404 on
`/v1/embeddings`, dimension changes, …). The launcher's preflight fails fast
with a fix hint if the torch stack is inconsistent, and the verification cell
checks the driver's CUDA level before any server starts. Details in the
[example README](https://github.com/jasonjimnz/minics/tree/main/examples/colab-vllm).
