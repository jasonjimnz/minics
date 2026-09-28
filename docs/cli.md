# CLI reference

The `minics` command is the fastest way to drive the studio from a terminal.
Every subcommand works against the same `~/.minics` store (override with
`MINICS_HOME` or the global `--home PATH` flag), so the CLI, the desktop app
and the Python library always see the same data.

Run `minics --help` or `minics <command> --help` for the full, live reference.

## At a glance

| Command | What it does |
| --- | --- |
| `minics` | Launch the desktop app (default, PyWebView shell). |
| `minics serve` | Run the web server in a browser. |
| `minics init` | Create the `~/.minics` structure and run migrations. |
| `minics setup` | Configure LLM + embedding endpoints (wizard or flags). |
| `minics models` | List chat / embedding models from the endpoint. |
| `minics scan` | **Bulk-import every compatible document in a directory tree.** |
| `minics documents` | Import, list or index single documents. |
| `minics reindex` | Rebuild the vector index + graph for all documents. |
| `minics search` | Hybrid retrieval (vector + graph, RRF fusion). |
| `minics datasets` | List or create datasets. |
| `minics entries` | List entries (filter by dataset, status, text). |
| `minics export` | Export a collection (ChatML / JSONL / Alpaca / ShareGPT / Markdown). |
| `minics skills` | Install the bundled MiniCS agent skillset. |
| `minics config` | Show or patch the configuration (secrets masked). |
| `minics info` | Show resolved paths and initialisation state. |
| `minics version` | Print the installed version. |

## `minics setup`

Interactive wizard when called with no flags; fully scriptable with flags:

```bash
minics setup                                  # wizard
minics setup \
  --base-url http://localhost:8000/v1 \
  --model qwen3-8b \
  --embedding-base-url http://localhost:11434/v1 \
  --embedding-model bge-m3 \
  --test
```

It lists available models, auto-detects the embedding dimension (required to
create the Chroma collection), runs a connection test with `--test` and marks
setup complete. Extra flags: `--api-key`, `--embedding-api-key`,
`--embedding-dimension N`, `--temperature`, `--max-tokens`.

## `minics scan` — bulk document import

Scans a directory (absolute, or relative to the current working directory),
converts every compatible document to markdown, and adds them **one by one**
to the store with live terminal progress (import → vector index → graph):

```bash
minics scan ./docs                     # every compatible format, recursive
minics scan /data/papers --pdf         # only PDFs
minics scan ./notes --markdown --txt   # only Markdown and plain text
minics scan ./docs --tags manuals,v2   # tag every imported document
minics scan ./docs --dry-run           # preview what would be imported
minics scan ./docs --no-index          # import only; index later via reindex
```

Details:

- **Format flags** `--markdown`, `--txt`, `--pdf`, `--docx`, `--latex` — with
  *no* format flag, **all compatible formats** are used.
- Supported extensions: `.pdf`, `.txt`/`.text`, `.md`/`.markdown`,
  `.docx`, `.tex`/`.latex`/`.ltx`.
- Hidden folders and vendor directories (`node_modules`, `.venv`, `__pycache__`,
  `dist`, …) are skipped automatically.
- **Duplicates are skipped** — files whose SHA-256 already exists in the store
  are reported and left untouched, so re-running a scan is always safe.
- Per-file failures are printed and the scan continues; a summary
  (`imported / duplicates skipped / failed / total`) is printed at the end.

Example output:

```
Scanning ./docs — 3 document(s) [docx, latex, markdown, pdf, text]

[  1/3] OK      handbook.md — indexed (127 chunks + graph)
[  2/3] SKIP    old/handbook.md (duplicate of 'handbook')
[  3/3] FAILED  broken.pdf: Unsupported file type ''

Done: 1 imported, 1 duplicate(s) skipped, 1 failed, 3 total.
```

## `minics documents`

```bash
minics documents --import paper.pdf handbook.md --index
minics documents                     # list documents
minics documents --search "fusion"   # filter by title/source
```

`--index` performs vector + graph indexing right after import. Without it, run
`minics reindex` later.

## `minics search`

```bash
minics search "how does RRF fusion work?"
minics search "sorting" --top-k 10 --no-graph
```

Prints JSON with the fused chunks, scores and ready-to-inject context text.

## `minics skills` — install the agent skillset

Copies the MiniCS skillset **bundled inside the package** (never fetched from
GitHub) into an agent skills directory readable by Pi, OpenCode, Codex and any
skill-compatible agent. See [Skills](skills.md) for the full skill catalogue.

```bash
minics skills install                # project-local: ./.agents/skills/
minics skills install --global       # user-wide:     ~/.agents/skills/
minics skills install --interactive  # choose which skills to install
minics skills install --force        # overwrite existing skills
minics skills install --dir PATH     # custom target directory
minics skills list                   # show bundled skills + install status
```

Local installs (the default) live next to your project — commit them to share
with the team; global installs live in your home directory. Existing skills
are never overwritten unless `--force` is passed.

## `minics datasets` / `minics entries`

```bash
minics datasets --create "Support QA" --description "Ticket answers"
minics entries --dataset 1 --status approved --limit 20
```

## `minics export`

```bash
minics export my-collection -o train.jsonl --format jsonl --approved
```

Formats: `chatml` (default), `jsonl`, `alpaca`, `sharegpt`, `markdown`.
`--approved` restricts the export to approved entries; `--include-metadata`
adds entry metadata. Output is byte-identical to the UI and Python exports.

## `minics config` / `minics info`

```bash
minics config                                  # show (secrets masked)
minics config --set '{"llm": {"temperature": 0.2}}'
minics info                                    # paths + initialised state
```
