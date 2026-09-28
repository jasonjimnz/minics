# Skill usage examples

The [Agent skills](skills.md) page describes *what each skill knows*; this page
shows *how an agent actually uses it*. Every example below is a realistic,
reproducible session — real commands, real flags, expected output — organised
by skill, and finished with three end-to-end **playbooks** that combine several
skills at once.

Agents: load the matching sub-skill before executing an example, and prefer the
smallest example that solves the task. All examples assume a store at
`~/.minics` (or `MINICS_HOME`) and at least one configured OpenAI-compatible
endpoint pair (`minics setup`).

> The prompts in "Agent task" quotes are what a user might type; the blocks
> underneath are what the agent should run.

---

## `minics` — the parent skill

### Example 1 — First contact with an existing store

**Agent task:** *"I inherited a machine with MiniCS already installed — what's in it?"*

```bash
minics version
minics info
minics datasets
minics documents
```

`info` is the safe first call — it reports paths and the `initialized` flag
without writing anything. If `initialized` is `false`, everything else is a
no-op; bootstrap with `minics init` first.

```json
{
  "version": "0.4.0",
  "home": "C:\\Users\\jason\\.minics",
  "initialized": true,
  "config": "C:\\Users\\jason\\.minics\\config.json",
  "database": "C:\\Users\\jason\\.minics\\minics.sqlite3",
  "vectordb": "C:\\Users\\jason\\.minics\\vectordb",
  "graphdb": "C:\\Users\\jason\\.minics\\graphdb",
  "documents": "C:\\Users\\jason\\.minics\\documents"
}
```

### Example 2 — Health check before any heavy operation

**Agent task:** *"Before scanning 400 PDFs, check the setup is healthy."*

```bash
minics info                                   # store exists?
minics config                                 # endpoints configured? (secrets masked)
minics models                                 # endpoint reachable, models listed
minics search "connection smoke test" --top-k 1   # retrieval pipeline alive
```

The parent skill's rule of thumb: `info → config → models → search` proves
store, config, endpoints and index in four read-only calls. Only then start
writing operations.

---

## `minics-setup` — endpoint configuration

### Example 3 — Split endpoints: llama.cpp for chat, Ollama for embeddings

**Agent task:** *"Set up MiniCS with llama-server on :8000 and Ollama on :11434."*

```bash
minics setup \
  --base-url http://localhost:8000/v1 \
  --api-key none \
  --model qwen3-8b \
  --embedding-base-url http://localhost:11434/v1 \
  --embedding-api-key ollama \
  --embedding-model bge-m3 \
  --test
```

Watch for two lines in the output:

```
Detected embedding dimension: 1024
...
"ok": true
```

The dimension line matters: it is baked into the Chroma collection. If it is
missing, the embeddings endpoint is wrong even if the chat endpoint answers.

### Example 4 — Switching the embedding model safely

**Agent task:** *"Move from bge-m3 to nomic-embed-text without breaking search."*

```bash
# 1. Verify the new model + its dimension BEFORE touching config
minics models --base-url http://localhost:11434/v1 --api-key ollama

# 2. Point the config at the new model and re-detect the dimension
minics setup \
  --embedding-base-url http://localhost:11434/v1 \
  --embedding-model nomic-embed-text \
  --test

# 3. The old vectors are in the old dimension — rebuild everything
minics reindex
```

The skill's rule: **never change the embedding model without `minics
reindex`** — Chroma collections are created with a fixed dimension, and mixing
dimensions corrupts retrieval.

### Example 5 — Diagnosing a failed connection

**Agent task:** *"`minics setup --test` fails — find out why."*

```bash
# Read what's actually configured (secrets are masked in output)
minics config

# Probe the endpoint directly, exactly as MiniCS would
curl -s http://localhost:8000/v1/models | head -c 400
```

The skill's troubleshooting table, in order of how often it bites:

| Check | Fix |
| --- | --- |
| Base URL missing `/v1` | Use `http://host:8000/v1`, not `http://host:8000`. |
| Model list empty | Gateways without `/v1/models`: pass the model name explicitly with `--model`. |
| Chat OK, embeddings fail | Split endpoints: set `--embedding-base-url` separately. |
| Wrong store | An env var `MINICS_HOME` may be redirecting everything — confirm with `minics info`. |

### Example 6 — Scripting config without the wizard

**Agent task:** *"Just lower the temperature, don't touch anything else."*

```bash
minics config --set '{"llm": {"temperature": 0.2}}'
minics config | python -c "import json,sys; c=json.load(sys.stdin); print(c['llm']['temperature'])"
# 0.2
```

`--set` is a deep merge: only the provided keys change. This is the agent's
preferred way to make surgical, non-interactive edits.

---

## `minics-documents` — ingestion and indexing

### Example 7 — Building a knowledge base from a docs tree

**Agent task:** *"Ingest everything under ./company-docs and make it searchable."*

```bash
# 1. Preview — always dry-run a large, unknown tree first
minics scan ./company-docs --dry-run

# 2. Ingest with live progress (convert → embed → graph, one file at a time)
minics scan ./company-docs
```

Typical session output:

```
Scanning ./company-docs — 214 document(s) [docx, latex, markdown, pdf, text]

[  1/214] OK      handbook/onboarding.md — indexed (38 chunks + graph)
[  2/214] OK      handbook/security.pdf — indexed (212 chunks + graph)
[  3/214] SKIP    handbook/security.pdf.bak (duplicate of 'security')
...
[214/214] FAILED  legacy/scan_2003.doc — Docx file is corrupted

Done: 210 imported, 3 duplicate(s) skipped, 1 failed, 214 total.
```

3. Verify retrieval immediately:

```bash
minics search "what is the password rotation policy?" --top-k 5
```

### Example 8 — Format-targeted ingest with tags

**Agent task:** *"Only the PDFs from the archive, tag them so we can tell them apart later."*

```bash
minics scan /data/archive-2024 --pdf --tags archive,2024
```

Tags land on every imported document and surface in the vector-store metadata,
which makes filtered analysis possible later (e.g. by title/source search via
`minics documents --search`).

### Example 9 — The incremental re-scan (idempotent ingest)

**Agent task:** *"More files were added to ./company-docs since yesterday."*

```bash
minics scan ./company-docs
```

That's the whole command — the skill's key insight is that `scan` is
**idempotent**: files already in the store (same SHA-256) are reported as
`SKIP (duplicate of ...)` and cost nothing, so re-running after every batch of
new documents is the intended workflow, not a mistake.

```
[  1/31] SKIP    handbook/onboarding.md (duplicate of 'onboarding')
[  2/31] OK      handbook/travel-policy.md — indexed (19 chunks + graph)
...
```

### Example 10 — Offline batch: import now, index once

**Agent task:** *"Import 2 GB of PDFs but don't hammer the embedding server yet."*

```bash
minics scan /data/big-archive --pdf --no-index
# ... later, in one pass, while the embedding endpoint is idle:
minics reindex
```

`--no-index` stores and converts only. `reindex` then chunks + embeds +
graph-extracts every document in one deterministic pass — useful when the
embedding server is slow, rate-limited, or not yet configured.

### Example 11 — Handling unsupported and broken files

**Agent task:** *"The scan reports failures — clean them up."*

The skill's rule: `scan` never stops on a bad file — it reports and continues.
After the run:

```bash
# What formats are supported again?
# .pdf .txt .text .md .markdown .docx .tex .latex .ltx  — nothing else.

# Convert the stragglers, then re-scan (duplicates are skipped for free)
pandoc notes.rtf -o notes.md
minics scan ./company-docs
```

A file that fails repeatedly (corrupt PDF, password-protected DOCX) should be
moved out of the tree or repaired — `scan` will keep reporting it otherwise.

---

## `minics-datasets` — datasets and entries

### Example 12 — Dataset creation and inventory

**Agent task:** *"Create a dataset for the support fine-tune and show me what we have."*

```bash
minics datasets --create "Support QA" --description "Ticket answers grounded in the handbook"
minics datasets
```

```json
[
  {
    "id": 1,
    "name": "Support QA",
    "description": "Ticket answers grounded in the handbook",
    "stats": {"entries": 0, "approved": 0}
  }
]
```

### Example 13 — Working the review queue

**Agent task:** *"How many entries are still drafts? Push the good ones to approved."*

```bash
minics entries --dataset 1 --status draft
minics entries --dataset 1 --status review
minics entries --dataset 1 --status approved
```

The lifecycle is `draft → review → approved`. The skill's guidance for agents:
treat `--status review` as the queue to triage, and only promote to `approved`
entries that would survive the quality gates from the `minics-authoring`
skill (evaluate first — see Example 16).

### Example 14 — Programmatic dataset seeding

**Agent task:** *"Create 20 FAQ entries from this YAML file."*

```python
from minics.services.context import get_context
import yaml

ctx = get_context()
ctx.ensure_ready()
dataset = ctx.datasets.create("FAQ", description="Seeded from faq.yaml")

for item in yaml.safe_load(open("faq.yaml", encoding="utf-8")):
    ctx.entries.create(
        dataset.id,
        system="You are a precise FAQ assistant. Answer from the handbook.",
        user=item["question"],
        assistant=item["answer"],
    )
ctx.close()
```

Entries created this way start as drafts — the workflow (Example 13) applies to
them exactly like hand-written ones, and every later edit bumps the version.

---

## `minics-authoring` — LLM-assisted authoring

### Example 15 — The grounded generation loop

**Agent task:** *"Generate an entry about the vacation policy, grounded in our docs."*

Prerequisite (the skill insists on this ordering): knowledge first, generation
second.

```bash
minics scan ./company-docs          # 1. corpus in
```

Then, in the app's entry editor — or programmatically:

```python
from minics.services.context import get_context

ctx = get_context()
draft = ctx.authoring.generate_entry(topic="vacation carry-over policy", dataset=1)
print(draft.messages[-1].content[:400])   # answer cites retrieved chunks as [n]
```

Grounded drafts cite `[n]` chunks from the indexed documents (`use_grounding`
is on by default). The skill's verification step: follow at least one citation
before trusting the draft.

### Example 16 — Evaluate before you promote

**Agent task:** *"Score every draft entry and tell me which ones are worth approving."*

```python
from minics.services.context import get_context

ctx = get_context()
for entry in ctx.entries.list(dataset=1, status="draft"):
    report = ctx.authoring.evaluate_entry(entry.id)
    print(entry.id, report.score, report.summary)
ctx.close()
```

Six dimensions come back per entry: **accuracy, completeness, clarity,
grounding, format, safety**. The skill's policy: promote to approved only
entries with no grounding or accuracy flags; rewrite the rest with
`ctx.authoring.enhance_entry_fields(entry.id, persist=True)` and re-evaluate.

### Example 17 — Enhance → re-evaluate → tags

**Agent task:** *"Improve the weak entries and make the dataset navigable."*

```python
from minics.services.context import get_context

ctx = get_context()
for entry in ctx.entries.list(dataset=1, status="review"):
    ctx.authoring.enhance_entry_fields(entry.id, use_grounding=True, persist=True)
    suggested = ctx.authoring.suggest_tags(entry.id, add=True)
    print(entry.id, "enhanced, tags:", suggested["tags"])
ctx.close()
```

Two kwargs matter here: `enhance_entry_fields` **does not save by default**
(`persist=True` required), and `suggest_tags` only applies the tags when
`add=True` — otherwise it just proposes them. With `use_grounding=True` the
enhancement retrieves before rewriting, so improvements stay anchored to the
corpus instead of drifting.

---

## `minics-retrieval` — hybrid search

### Example 18 — Vector-only vs hybrid, side by side

**Agent task:** *"Is the graph actually helping?"*

```bash
minics search "who owns the incident response process" --no-graph --top-k 5
minics search "who owns the incident response process" --top-k 5
```

Run both, diff the top hits. Ownership-style questions ("who", "which team")
usually rank better **with** the graph, because the entity walk connects
`Incident Response` → `Team: Platform`; wording-similarity questions barely
differ. That's the skill's heuristic for when to bother tuning graph hops.

### Example 19 — Tuning RRF

**Agent task:** *"The right chunk is at position 6 — make it rank first."*

```bash
minics config --set '{"retrieval": {"rrf_k": 30}}'
minics search "vacation carry-over" --top-k 3
```

Lower `rrf_k` sharpens the fusion: a chunk that ranks high on *both* sides
(vector + graph) climbs faster. The skill's tuning table:

| Symptom | Knob |
| --- | --- |
| Correct chunk present but low | lower `rrf_k` (60 → 30 → 10) |
| Too few chunks in context | raise `top_k` |
| Context is broad and noisy | fewer graph hops / lower `top_k` |
| Results look stale | `minics reindex` |

### Example 20 — Proving an index is stale

**Agent task:** *"Search used to find this, now it doesn't."*

```bash
minics search "q3 revenue table" --no-graph --top-k 3   # empty or weak
minics documents --search "q3"                          # is the doc even in?
minics reindex                                          # rebuild vectors + graph
```

The skill's diagnostic order: corpus → config → index. If `documents` shows
the file but search is empty, the index (or embedding endpoint at index time)
is the culprit, and `reindex` is the fix.

---

## `minics-chat` — grounded chat

### Example 21 — The retrieval-vs-model separation test

**Agent task:** *"Answers are bad — is it the index or the model?"*

```bash
# Step 1: ask the index directly, no model involved
minics search "what ports does the firewall allow?" --top-k 3
```

Good chunks? Then the index is fine and the problem is prompting — go to the
app's Chat screen with **RAG + Grounding** on and re-ask. Bad chunks? Back to
the `minics-documents` / `minics-retrieval` skills; do not touch the prompt.

### Example 22 — Preview without injecting

**Agent task:** *"Show me what would be sent to the model, without sending it."*

In the Chat screen, toggle **RAG** on but **Grounding** off: retrieval runs and
the context panel shows exactly which chunks *would* be injected, with their
scores — the conversation itself stays clean. The skill's rule: preview first
when validating a new corpus, inject only when the preview looks right.

### Example 23 — Trusting the answer via citations

**Agent task:** *"The bot gave a policy number — verify it."*

With grounding on, answers cite `[n]` references. Each `[n]` maps to a chunk
traceable to its source document in `~/.minics/documents/markdown/`. The
agent's verification move: open the cited document, confirm the claim, *then*
report the answer as trustworthy. Cited-but-wrong is a model problem;
uncited is usually a retrieval problem.

---

## `minics-export` — collections and formats

### Example 24 — A clean fine-tuning export

**Agent task:** *"Export the Support QA dataset for OpenAI fine-tuning."*

```bash
minics export "Support QA" -o train.jsonl --format jsonl --approved
```

`--approved` is the whole point: drafts and review copies never reach the
training file. Verify the shape before shipping:

```bash
python -c "import json; rows=[json.loads(l) for l in open('train.jsonl', encoding='utf-8')]; print(len(rows), 'rows'); print(rows[0]['messages'][0]['role'])"
```

### Example 25 — Format matrix for one collection

**Agent task:** *"We need the same data in every format MiniCS supports."*

```bash
for fmt in chatml jsonl alpaca sharegpt markdown; do
  minics export "Support QA" -o "support_qa.$fmt" --format "$fmt" --approved
done
```

All five files are byte-identical snapshots of the same query — the skill's
multi-turn caveat applies: ChatML and ShareGPT keep full conversations, while
JSONL and Alpaca flatten deterministically to one instruction/response pair per
record, so prefer ChatML/ShareGPT for multi-turn data.

### Example 26 — Metadata-rich review export

**Agent task:** *"Give the reviewers a readable file that still says where each entry came from."*

```python
from minics.services.context import get_context

ctx = get_context()
content = ctx.collections.export(
    "Support QA", fmt="markdown", include_metadata=True, only_approved=True
)
open("review.md", "w", encoding="utf-8").write(content)
ctx.close()
```

---

## `minics-python` — library usage

### Example 27 — Full pipeline in twenty lines (notebook-style)

**Agent task:** *"Script the whole loop: ingest, retrieve, draft, export."*

```python
from minics.services.context import get_context

ctx = get_context()
ctx.ensure_ready()

# 1. dataset
dataset = ctx.datasets.create("Colab KB", description="Built in one script")

# 2. ingest + index one document
doc = ctx.documents.import_file("handbook.pdf")
ctx.indexer.index_document(doc.id)
if ctx.graph.is_available():
    ctx.graph_indexer.index_document(doc.id)

# 3. retrieval check
result = ctx.retriever.retrieve("how does fusion work?", top_k=6)
print(result.context_text()[:500])

# 4. grounded draft + quality gate
draft = ctx.authoring.generate_entry(topic="RRF vs reranking", dataset=dataset.id)
report = ctx.authoring.evaluate_entry(draft.id)
print("score:", report.score)

# 5. export
print(ctx.collections.export("Colab KB", fmt="jsonl", only_approved=True)[:200])
ctx.close()
```

This is the `examples/colab-vllm` notebook pattern in miniature — the same
service API the UI calls, usable from any script or notebook.

### Example 28 — Incremental nightly ingest (cron-friendly)

**Agent task:** *"Every night: ingest new files, report what changed."*

```python
# nightly_ingest.py — run via cron/Task Scheduler
import subprocess
import sys

# 1. scan is idempotent — duplicates are skipped by SHA-256, so just re-run it
subprocess.run([sys.executable, "-m", "minics", "scan", "./company-docs"], check=True)

# 2. report what the store holds now
from minics.services.context import get_context

ctx = get_context()
stats = ctx.documents.stats()
print(f"documents={stats['documents']} chunks={stats['chunks']} bytes={stats['bytes']}")
ctx.close()
```

The pattern to remember: shell out to `minics scan` for the resilient,
progress-printing path; use the context API only for reads and reporting.

### Example 29 — Isolated stores for tests and experiments

**Agent task:** *"Experiment without touching my real dataset."*

```python
import os, tempfile
os.environ["MINICS_HOME"] = tempfile.mkdtemp(prefix="minics-lab-")

from minics.services.context import get_context   # read AFTER setting the env var
ctx = get_context()
ctx.ensure_ready()
# throwaway store: experiment freely, delete the folder when done
```

The skill's warning: read `MINICS_HOME` **before** importing the context, and
never share one store across processes for concurrent writes — SQLite runs a
single writer thread by design.

---

## `minics-server` — headless serving

### Example 30 — Deploy the GHCR image

**Agent task:** *"Stand MiniCS up on this box, persistent storage, no build."*

```bash
docker pull ghcr.io/jasonjimnz/minics:0.4.0
docker run -d --name minics \
  -p 8765:8765 \
  -v minics-data:/data \
  ghcr.io/jasonjimnz/minics:0.4.0

curl -s http://localhost:8765/api/health   # verify
```

First open of `http://localhost:8765` finishes setup in the UI; the store
persists in the `minics-data` volume across restarts and upgrades.

### Example 31 — Behind nginx with SSE

**Agent task:** *"The UI works directly but hangs behind our proxy."*

```nginx
location / {
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header Host $host;
}
location /api/events {
    proxy_pass http://127.0.0.1:8765;
    proxy_buffering off;        # SSE needs this — buffering stalls the stream
}
```

The skill's tell-tale symptom: progress bars and activity updates freeze while
plain requests work — that's SSE buffering, every time.

---

## `minics-skills` — the installer

### Example 32 — Team onboarding: committed, local skills

**Agent task:** *"Every agent working in this repo should know MiniCS."*

```bash
cd ./our-project
minics skills install            # writes ./.agents/skills/
git add .agents && git commit -m "Add MiniCS agent skillset"
```

Because the folder is committed, every teammate (and their agents) gets the
same skillset on clone — no per-machine step. This is the default for a reason.

### Example 33 — Minimal personal install

**Agent task:** *"I only author datasets — just install what I need."*

```bash
minics skills install --global --interactive
```

```
Select the skills to install (Enter = all, comma-separated numbers or names):

   1. minics             Use MiniCS (minichat-studio) — ...
   2. minics-setup       Configure MiniCS LLM and embedding endpoints ...
   ...

Skills: 1 4 5

Installing MiniCS skills into ~/.agents/skills

  + minics
  + minics-datasets
  + minics-authoring

Done: 3 installed, 0 skipped.
```

### Example 34 — Upgrade day

**Agent task:** *"We updated minichat-studio — refresh the skills."*

```bash
pip install -U minichat-studio
minics skills install --global --force   # overwrite the stale copies
```

The skill's rule: skills document the CLI/API of the installed package —
reinstall with `--force` after every upgrade, and `minics skills list` shows
what's bundled vs installed.

---

## Playbooks — several skills in one session

### Playbook A — "Paper archive → fine-tuning dataset"

**Agent task:** *"Turn our 200 research PDFs into a fine-tuning dataset."*

1. **`minics-setup`** — verify endpoints: `minics models` (embedding model
   present? dimension detected?).
2. **`minics-documents`** — `minics scan ./papers --dry-run`, then
   `minics scan ./papers --pdf --tags papers`; confirm a probe search hits.
3. **`minics-retrieval`** — `minics search "<core topic>" --top-k 5`; tune
   `rrf_k` if the obvious chunk ranks low.
4. **`minics-chat`** — validate 3–4 questions in Chat with grounding on;
   follow the `[n]` citations once.
5. **`minics-authoring`** — generate grounded entries per topic; evaluate each;
   enhance the keepers; suggest tags.
6. **`minics-datasets`** — work the review queue, promote to approved.
7. **`minics-export`** — `minics export papers -o train.jsonl --format jsonl
   --approved`.

### Playbook B — "Nightly knowledge refresh"

**Agent task:** *"Keep the KB current and tell me if anything got worse."*

```bash
#!/usr/bin/env bash
set -euo pipefail
minics scan ./company-docs                      # idempotent — only new files land
minics reindex                                  # fold new docs into vectors + graph
minics search "smoke test query" --top-k 1      # retrieval still alive?
curl -fsS http://localhost:8765/api/health      # server still up?
```

Wrap that in cron/Task Scheduler; on failure, the `minics-retrieval`
stale-index diagnostic (Example 20) is the first follow-up.

### Playbook C — "New teammate, new machine"

**Agent task:** *"Set up a fresh laptop to work on the project."*

```bash
pip install minichat-studio        # 1. package
minics init                        # 2. store
minics setup                       # 3. interactive wizard (models, dimension, test)
git clone our-project && cd our-project
minics skills install              # 4. skills (already committed to the repo)
minics                             # 5. desktop app
```

Four commands and a clone — the parent skill's workflow, end to end.
