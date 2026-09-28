---
name: minics-authoring
description: LLM-assisted dataset authoring in MiniCS — enhance assistant replies, suggest tags, evaluate entries against six quality dimensions, and generate new grounded entries from topics using indexed documents as context. Use when improving, reviewing or scaling up dataset entries.
---

# MiniCS authoring helpers

The LLM layer ships structured-output helpers (with 3 fallback strategies for
robustness) that act on entries. In the desktop app they are one-click actions
in the entry editor; programmatically they live in
`minics.services.authoring.AuthoringService`.

## The four helpers

| Helper | What it does |
| --- | --- |
| **Enhance assistant** | Rewrites the assistant reply for accuracy, completeness and tone — grounded in retrieved context when available. |
| **Suggest tags** | Proposes topical tags from the entry content. |
| **Evaluate** | Scores the entry against **6 quality dimensions** (accuracy, completeness, clarity, grounding, format, safety) with per-dimension feedback. |
| **Generate grounded** | Drafts a whole new entry (system/user/assistant) from a topic, using your indexed documents as context, with `[n]` citations to the chunks used. |

## Programmatic use

```python
from minics.services.context import get_context

ctx = get_context()
entry = ctx.entries.get(42)

ctx.authoring.enhance(entry.id)          # improve the assistant reply
ctx.authoring.suggest_tags(entry.id)     # propose tags
report = ctx.authoring.evaluate(entry.id)  # 6-dimension quality report
draft = ctx.authoring.generate(topic="RRF vs plain reranking", dataset_id=1)
```

(See the `minics-python` sub-skill for context setup and the exact signatures.)

## Recommended loop

1. `minics scan ./docs` — get real knowledge into the index.
2. Generate grounded entries for the topics you need.
3. **Evaluate** every generated entry; discard or rewrite low scorers.
4. **Enhance** the assistant reply of keepers; **suggest tags** to keep the
   dataset navigable.
5. Promote to approved and curate into a collection.

Quality gates beat volume: evaluate-then-enhance produces markedly better
datasets than bulk generation alone.
