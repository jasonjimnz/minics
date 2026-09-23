# Data & storage

MiniCS is **local-first**: the application and all of its data live on your
machine, in one folder. There is no cloud, no account and no sync service.
This page explains exactly what is stored where, how the embedded databases
work, and what that means for backups, moving and running multiple instances.

---

## 1. One folder: the store

Everything lives in **`~/.minics`** by default. Override it with the
`MINICS_HOME` environment variable — every code path resolves paths through
`core/paths.py` (`MinicsPaths`), nothing is ever hardcoded:

```bash
export MINICS_HOME=/srv/minics        # Windows: set MINICS_HOME=D:\minics
```

The store is created automatically by any command that needs it
(`minics init` does it explicitly), including SQLite migrations.

## 2. What is inside

```
~/.minics/
├── config.json            # all settings (LLM/embedding endpoints, app config)
├── minics.sqlite3         # the relational store (WAL mode)
├── minics.sqlite3-wal     # SQLite write-ahead log (transient)
├── minics.sqlite3-shm
├── documents/
│   ├── originals/         # uploaded PDF/DOCX/TXT/MD/TeX, untouched
│   └── markdown/          # the cleaned markdown conversion of each document
├── vectordb/              # ChromaDB embedded persistent store (vectors + metadata)
├── graphdb/
│   └── minics.graph       # LadybugDB embedded knowledge graph
├── cache/                 # working files
└── logs/                  # application logs
```

| Path | Owned by | Contents |
| --- | --- | --- |
| `config.json` | `core/config.py` | Four pydantic sections: `llm`, `embedding`, `app`, … (full schema in [configuration.md](configuration.md)). |
| `minics.sqlite3` | `core/db.py` | Datasets, entries (+ version history), collections, documents, jobs. |
| `documents/originals/` | `documents/convert.py` | Source files exactly as uploaded. |
| `documents/markdown/` | `documents/convert.py` | Cleaned markdown — the input to chunking and indexing. |
| `vectordb/` | `rag/vectorstore.py` | ChromaDB collections, created with your embedding **dimension**. |
| `graphdb/` | `rag/graph.py` | Entities and relations for graph-aware retrieval. |

## 3. The embedded databases

MiniCS deliberately uses **three embedded databases** — no database server to
install, no connection strings, each store is just a file inside the folder:

| Engine | File | Role | Concurrency model |
| --- | --- | --- | --- |
| **SQLite** | `minics.sqlite3` | System of record for all app data | WAL mode: many readers + **one dedicated writer thread** inside the process; every write is funnelled through it (`core/db.py`). |
| **ChromaDB** | `vectordb/` | Vector index over document chunks | Embedded persistent client; safe within the single app process. |
| **LadybugDB** | `graphdb/minics.graph` | Knowledge graph (entities + relations) | Embedded; opened at startup. |

Two design consequences worth knowing:

- **One process per store.** These embedded engines assume a single owning
  application. Run one MiniCS instance against a given `MINICS_HOME` — do not
  open the same folder from two processes (two `minics serve` runs, or CLI
  commands while a server holds the same store) and never share the folder
  over a network filesystem. A second, *separate* store is as easy as a second
  `MINICS_HOME`.
- **Graceful degradation.** If the graph file cannot be opened, retrieval
  falls back to vectors-only; if embeddings are unreachable, chat keeps
  working without grounding. The app never becomes unusable because one store
  is unhappy.

## 4. Configuration and secrets

- `config.json` is written **atomically** (temp file → fsync → `os.replace`),
  so a crash can never leave a half-written config.
- **API keys are stored in plain text** in `config.json` — that is the price of
  local-first simplicity. The CLI and UI always *display* them masked
  (`sk-…abcd`), but treat the file like you would `.env` files: keep the folder
  private, and prefer `MINICS_HOME` inside an encrypted volume (BitLocker,
  FileVault, LUKS) if that matters to you.
- Local model servers usually need no key at all — an empty key sends a
  `not-needed` placeholder.

## 5. Backups

Because the store is plain files, backups are simple:

1. **Stop the application** (or pause activity) so SQLite reaches a consistent
   snapshot, then
2. **copy the whole folder** — nothing else is needed, config included.

Docker note: the store is a single volume, so the same rule applies — stop the
container (`docker compose down`), copy the volume / bind-mounted directory,
start again. See [docker.md](docker.md).

A minimal in-place SQLite backup (while the app is stopped) is also possible:

```bash
sqlite3 ~/.minics/minics.sqlite3 ".backup '/tmp/minics-backup.sqlite3'"
```

## 6. Moving or syncing the store

The store is **portable by construction** — relative layout, absolute paths
resolved at runtime, engine-agnostic formats:

```bash
# move the store to a new machine / disk
tar -C ~ -czf minics-store.tgz .minics
export MINICS_HOME=/srv/minics
tar -C /srv -xzf minics-store.tgz
```

Move the folder (or set `MINICS_HOME` to the new location), install the package
on the target, and the app continues exactly where it left off. Avoid syncing
the *live* folder with Dropbox/Nextcloud-style tools while the app runs — sync
a stopped copy instead, for the SQLite consistency reason above.

## 7. Upgrades, resets and privacy

| Concern | Reality |
| --- | --- |
| Package upgrade | Never touches the store; schema migrations are automatic and additive on next start. |
| Uninstall | `pip uninstall` leaves `~/.minics` untouched. |
| Full reset | Delete the folder (`rm -rf ~/.minics`), or in Docker `docker compose down -v`. |
| Partial reset | Delete individual databases (e.g. `vectordb/`) and re-run `minics reindex` — the relational store is untouched. |
| Privacy | No telemetry, no accounts; the only network traffic is to the model endpoints **you** configured, plus document retrieval is entirely local. |
| Inspectability | The data is yours: open the SQLite file with any tool, read the markdown conversions, export datasets in five formats ([features.md](features.md)). |
