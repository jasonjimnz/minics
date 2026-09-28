---
name: minics-datasets
description: Create and manage MiniCS datasets and ChatML entries — datasets via CLI or UI, entry structure (system/user/assistant), draft→review→approved workflow, versioning and ChatML validation. Use when creating datasets, adding training examples, or inspecting entries.
---

# MiniCS datasets

Datasets are the top-level containers for training examples. Each **entry** is
a ChatML conversation: `system`, `user` and `assistant` messages.

## CLI

```bash
minics datasets                          # list (with stats)
minics datasets --create "Support QA" --description "Ticket answers" 
minics entries                           # list entries
minics entries --dataset 1 --status approved --search "RRF" --limit 20
```

## Entry lifecycle

```
draft ──► review ──► approved
```

- Entries start as **draft**; promote through review to approved.
- **Every message edit bumps the entry version automatically** — history is
  kept, nothing is silently overwritten.
- Structure is **validated as ChatML** in real time (roles, ordering,
  non-empty content).

## ChatML shape

```json
{"messages": [
  {"role": "system", "content": "You are a precise support assistant."},
  {"role": "user", "content": "What is RRF?"},
  {"role": "assistant", "content": "Reciprocal Rank Fusion is ..."}
]}
```

## Authoring options

1. **By hand** — in the entry editor (messages can be reordered, deleted,
   switched between roles).
2. **Grounded generation** — type a topic and let the LLM draft the whole
   entry using your indexed documents as context (see the `minics-authoring`
   sub-skill).

## Workflow tips

- Import knowledge first (`minics scan ./docs`), *then* generate entries —
  grounded drafts cite real chunks instead of hallucinating.
- Keep entries approved-only in export collections (`--approved`).
- Use `minics entries --status review` as a review queue.
