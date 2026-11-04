---
name: minics-skills
description: Install and manage the MiniCS agent skillset with `minics skills install` — local `.agents/skills`, global installs, interactive selection. Use when setting up the MiniCS skills for an agent (Pi, OpenCode, Codex or any skill-compatible agent) or updating an existing installation.
---

# MiniCS skills installer

The MiniCS skillset ships **inside the PyPI package** — no GitHub fetch needed.
`minics skills install` copies the bundled skills into an agent skills
directory compatible with Pi, OpenCode, Codex and any agent that reads
`.agents/skills/`.

## Usage

```bash
minics skills install                # project-local: ./.agents/skills/
minics skills install --global       # user-wide: ~/.agents/skills/
minics skills install --interactive  # pick which skills to install
minics skills install --force        # overwrite existing versions
minics skills install --dir PATH     # custom target directory
minics skills install --pi-trust     # save Pi project-trust for this directory
minics skills list                   # show bundled skills and their status
```

## Pi (pi.dev) compatibility

The SKILL.md format itself is Agent-Skills-spec compliant and loads in Pi as
is. The one gotcha is **project trust**: Pi treats project-level
`.agents/skills/` as a trust-protected resource and silently skips it until
the project directory has been approved.

- `minics skills install` auto-saves the Pi trust decision when Pi is
  detected and no decision exists yet (or pass `--pi-trust` explicitly).
- Inside Pi, `/trust` approves the current project interactively;
  `pi --approve` is the one-shot CLI equivalent.
- Decisions live in `~/.pi/agent/trust.json` (`{"<dir>": true}`), closest
  parent decision wins.
- **Global installs (`--global` → `~/.agents/skills/`) need no trust** — use
  them when you want the skills in every Pi session without per-project
  approval.
- After (re)installing, restart Pi or run `/reload` to pick up the skills.

## What gets installed

Each skill is a directory with a `SKILL.md` (YAML frontmatter: `name` +
`description`) plus supporting docs when needed:

- `minics` — parent skill: overview, workflow, quick CLI reference
- `minics-setup` — LLM/embedding endpoint configuration
- `minics-documents` — document import and `minics scan` bulk ingestion
- `minics-datasets` — datasets and ChatML entries
- `minics-authoring` — LLM-assisted enhance/tags/evaluate/generate
- `minics-retrieval` — hybrid RAG + graph retrieval
- `minics-chat` — grounded chat with citations
- `minics-export` — collections and export formats
- `minics-python` — library usage via `AppContext`
- `minics-server` — headless serving and Docker
- `minics-proxy` — OpenAI-compatible RAG proxy server (`minics proxy`)

## Notes

- Local installs go to `./.agents/skills/` relative to the **current working
  directory** — commit them to the repo if the whole team should have them.
- Re-running the installer skips skills that already exist unless `--force`.
- The installed skills document the CLI and Python API of the installed
  `minichat-studio` version — reinstall after upgrading MiniCS.
