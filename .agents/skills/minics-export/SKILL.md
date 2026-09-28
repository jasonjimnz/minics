---
name: minics-export
description: Curate MiniCS collections and export datasets to ChatML, JSONL, Alpaca, ShareGPT or Markdown — from the UI, the CLI or Python, all byte-identical. Use when exporting approved entries for fine-tuning.
---

# MiniCS export

Collections are curated sets of approved entries destined for export. Export is
**byte-identical** whether it comes from the UI, the CLI or Python.

## Formats

| Format | Flag value | Typical use |
| --- | --- | --- |
| ChatML | `chatml` (default) | Native format, messages array. |
| JSONL | `jsonl` | OpenAI fine-tuning. |
| Alpaca | `alpaca` | instruction/input/output pairs. |
| ShareGPT | `sharegpt` | conversations format. |
| Markdown | `markdown` | human-readable review. |

## CLI

```bash
minics export my-collection                       # ChatML to stdout
minics export my-collection -o train.jsonl --format jsonl
minics export my-collection --approved            # only approved entries
minics export my-collection --include-metadata
```

## Curating

In the app: create a collection (name + description), search entries, *Add*
them to the collection, then download in any format. Only approved entries
should enter final collections.

## Programmatic

```python
from minics.services.context import get_context

ctx = get_context()
content = ctx.collections.export("my-collection", fmt="jsonl", only_approved=True)
open("train.jsonl", "w", encoding="utf-8").write(content)
```

## Tips

- Export with `--approved` to keep drafts and review copies out of training.
- JSONL + Alpaca expect a single message pair per record — multi-turn entries
  are flattened deterministically; prefer ChatML/ShareGPT for multi-turn data.
- Version your exports: the entry history is kept, but the exported file is a
  snapshot — re-export after edits.
