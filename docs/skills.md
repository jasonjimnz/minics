# Agent skills

MiniCS ships a complete **agent skillset** — precise, task-focused
instructions that teach coding agents (Pi, OpenCode, Codex and any other
skill-compatible agent) how to drive MiniCS from the CLI and the Python
library. The skills are **bundled inside the PyPI package**: installation is a
local file copy, no GitHub access needed.

## Installing

```bash
minics skills install                # project-local: ./.agents/skills/
minics skills install --global       # user-wide:     ~/.agents/skills/
minics skills install --interactive  # pick individual skills
minics skills install --force        # overwrite an existing installation
minics skills list                   # see what is bundled / installed
```

- **Local (default)** — installs into `./.agents/skills/` relative to the
  current working directory. Commit the folder to your repository so the whole
  team (and their agents) get the same skillset.
- **Global** — installs into `~/.agents/skills/`, available in every project.
- `--interactive` lets you install only the sub-skills you need.
- Skills are skipped when already present; use `--force` to update them after
  upgrading MiniCS.

Each skill is a directory containing a `SKILL.md` with YAML frontmatter
(`name` + `description`) — the format agents use to decide when to load a
skill. Your agent will pick them up on its next session. For worked sessions
per skill, see [Skill usage examples](skill-examples.md).

## The skillset

One parent skill plus ten focused sub-skills:

### `minics` — the parent skill

The map of everything: what MiniCS is, the core concepts (datasets, entries,
documents, collections, grounding), the standard workflow
(`init → setup → scan → app`), the quick CLI reference, the `~/.minics` store
layout and the project principles. It links to every sub-skill, so agents
start here and drill down as needed.

### `minics-setup` — endpoint configuration

Wiring the LLM and embedding endpoints: the interactive wizard, the
non-interactive flags, model discovery (`minics models`), config patching
(`minics config --set`) and a troubleshooting table (missing `/v1`, embedding
dimension changes, empty model lists, `MINICS_HOME`).

### `minics-documents` — ingestion and indexing

The document pipeline: supported formats, **`minics scan`** for bulk directory
import (format flags, `--tags`, `--dry-run`, `--no-index`, duplicate skipping,
failure tolerance), single-file imports (`minics documents --import`), and
indexing/reindexing — plus what to do when scan skips a file or the graph
stays empty.

### `minics-datasets` — datasets and entries

Datasets as containers, the ChatML entry shape (system/user/assistant), the
draft → review → approved lifecycle, automatic versioning on message edits,
real-time ChatML validation, and the recommended order: import knowledge
*before* generating entries.

### `minics-authoring` — LLM-assisted authoring

The four structured-output helpers: **enhance assistant**, **suggest tags**,
**evaluate** (six quality dimensions) and **generate grounded** (draft whole
entries from topics, citing indexed chunks) — with the recommended
evaluate-then-enhance loop.

### `minics-retrieval` — hybrid search

ChromaDB vectors + Ladybug graph topology fused with Reciprocal Rank Fusion:
`minics search` usage, how the fusion pipeline works, the tuning knobs
(`top_k`, `rrf_k`, graph hops) and the graceful-degradation guarantees.

### `minics-chat` — grounded chat

Per-conversation **RAG / Graph / Grounding** toggles, previewing what
retrieval *would* inject without forcing it into the prompt, `[n]` citation
references, and a validation loop that separates retrieval problems from
model problems.

### `minics-export` — collections and formats

Curating approved entries into collections and exporting to **ChatML, JSONL,
Alpaca, ShareGPT and Markdown** — byte-identical from UI, CLI or Python, with
per-format guidance (multi-turn data, `--approved`, export versioning).

### `minics-python` — library usage

The `AppContext` service API for scripting and automation: `get_context()`,
`ensure_ready()`, an end-to-end example (dataset → import → index → retrieve →
export), the full service map and the local-first caveats (single SQLite
writer, isolated homes via `MINICS_HOME`).

### `minics-server` — headless serving

`minics serve` vs `minics app`, the prebuilt **GHCR** server image
(`ghcr.io/jasonjimnz/minics`), volumes and first-run behaviour, health
endpoints, and reverse-proxy notes (SSE buffering).

### `minics-skills` — the installer itself

How to install/update the skillset: local vs global targets, `--interactive`,
`--force`, `--dir`, the list of bundled skills and when to reinstall (after
upgrading `minichat-studio`).

## Agent compatibility

The `SKILL.md` + frontmatter format is the emerging cross-agent standard:

| Agent | Where it looks |
| --- | --- |
| **Pi** | `.agents/skills/` in the project or home directory. |
| **OpenCode** | `.agents/skills/` (project) / `~/.agents/skills/` (global). |
| **Codex** | `.agents/skills/` (project) / `~/.agents/skills/` (global). |
| Others | Any agent that reads the agent-skills format. |

That is exactly the layout `minics skills install` writes — install once and
every compatible agent in the project benefits.
