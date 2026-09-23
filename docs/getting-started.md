# Getting started

From zero to a working studio in a few minutes: create the store, point MiniCS
at your model endpoints, launch the app, and build your first dataset with
grounding from your own documents.

---

## 1. Create the store

```bash
minics init
```

This creates the home directory (default `~/.minics`), the folder structure and
the SQLite database, and applies schema migrations. You only need to run it
once — every command that needs the store (`setup`, `serve`, `app`, `export`,
…) **auto-creates it on first use**, so `init` is really for users who want the
folder to exist explicitly.

To keep the store somewhere else (external disk, server volume, encrypted
folder), set `MINICS_HOME` first:

```bash
export MINICS_HOME=/srv/minics      # Windows: set MINICS_HOME=D:\minics
```

## 2. Run the setup wizard

```bash
minics setup
```

The wizard asks for two endpoints (they may live on different servers):

- a **chat endpoint** — any OpenAI-compatible `/v1/chat/completions` server
  (OpenAI, vLLM, `llama.cpp`, LM Studio, Ollama, …),
- an **embedding endpoint** — any server speaking `/v1/embeddings`.

It then probes the embedding **dimension** (Chroma collections are created
with it) and runs a connection test. The API key is stored locally in
`~/.minics/config.json` and always masked when displayed.

Non-interactive variant — useful for scripts and containers:

```bash
minics setup \
  --base-url http://localhost:11434/v1 \
  --model llama3.1-instruct \
  --embedding-model nomic-embed-text
```

Everything the wizard writes is documented key by key in
[configuration.md](configuration.md). You can change any of it later in the
UI (**Settings**) or with `minics config --set '{"llm": {"model": "..."}}'`.

## 3. Launch the app

Three interchangeable ways — same engine, same store:

```bash
minics                        # desktop app (PyWebView window)
minics serve --port 8800      # browser only, opens http://127.0.0.1:8800
docker compose up -d --build  # server container (see docker.md)
```

- The **desktop app** embeds a local Flask server and opens it in a native
  window. If no webview is available (headless Linux), it falls back to your
  browser automatically.
- **`minics serve`** runs the same server and opens the UI in your default
  browser; add `--no-browser` to keep it quiet.
- Details on hosting the Flask app properly (reverse proxy, ports, security)
  are in [serving.md](serving.md).

On first launch you land on the setup screen — if you already ran
`minics setup`, the dashboard is ready to go.

## 4. Build your first dataset

In the UI: **New dataset** → give it a name → **New entry**. An entry is one
ChatML training sample with `system`, `user` and `assistant` messages. Save it
as a **draft**, mark it **reviewed** when checked, **approve** it when done —
that is the built-in draft → review → approved workflow, and every message edit
is versioned automatically.

From the terminal:

```bash
minics datasets --create "Support QA"
minics entries --dataset "Support QA" --limit 10
```

Or from Python, using the same service layer the UI uses:

```python
from minics.services.context import get_context

ctx = get_context()
ds = ctx.datasets.create("Support QA")
ctx.entries.add(ds.id, messages=[
    {"role": "system", "content": "You answer from the manual."},
    {"role": "user", "content": "How do I reindex?"},
    {"role": "assistant", "content": "Run `minics reindex`…"},
])
```

Structural ChatML validation runs on save, so malformed message lists are
rejected before they enter the library.

## 5. Import and index documents

This is what powers retrieval and grounding. Supported input formats:
**PDF, DOCX, TXT, Markdown and LaTeX**. Every file is converted to cleaned
markdown (optionally repaired by the LLM), then chunked by headings and indexed
into the vector store and the knowledge graph.

```bash
minics documents --import paper.pdf --index
minics reindex                                   # rebuild vectors + graph for everything
```

Or drag files in through the UI's **Documents** screen. Verify retrieval before
writing any prompts:

```bash
minics search "what is RRF?" --top-k 5
```

## 6. Chat with grounding

Open a conversation and flip the per-conversation switches:

- **RAG** — inject retrieved chunks from your imported documents,
- **Graph** — add topology from the knowledge graph,
- **Grounding** — preview exactly what would be injected before sending.

Retrieval and injection are separate: you can *preview* what the model would
see without forcing it into the prompt. Citations point back to source
documents and chunks.

## 7. Export anywhere

```bash
minics export "Support QA" -o out.jsonl --format jsonl --approved
```

Formats: **ChatML, JSONL, Alpaca, ShareGPT and Markdown** — byte-identical
whether you export from the UI, the CLI or Python. Use `--approved` to ship
only entries that passed review.

## 8. Everyday workflow

| Step | UI | CLI |
| --- | --- | --- |
| Configure endpoints | Settings screen | `minics setup` |
| Create dataset | Datasets → New | `minics datasets --create N` |
| Author entries | Editor with enhance/suggest buttons | `minics entries --dataset N` |
| Import documents | Documents → Import | `minics documents --import F --index` |
| Check retrieval | Chat grounding preview | `minics search "query"` |
| Export | Collections → Export | `minics export C -o out --format jsonl` |

All CLI output is JSON, so it composes with `jq`; the full command reference is
in [backend.md](backend.md), and every REST endpoint behind the UI is documented
in [api.md](api.md).
