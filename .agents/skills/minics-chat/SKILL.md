---
name: minics-chat
description: Grounded chat in MiniCS — per-conversation RAG, graph and grounding toggles, previewing what retrieval would inject, and `[n]` citation references in answers. Use when testing a model against the knowledge base or building grounded conversations.
---

# MiniCS chat

Chat is the smoke-test surface for the model: each conversation carries its own
**RAG**, **Graph** and **Grounding** toggles, and retrieval and injection are
separate — you can *preview* what would be used without forcing it into the
prompt.

## Toggles

| Toggle | Effect |
| --- | --- |
| **RAG** | Retrieve fused hybrid chunks for the question. |
| **Graph** | Include the entity-graph expansion in retrieval. |
| **Grounding** | Actually inject the retrieved context into the prompt sent to the model. |

Leave grounding off to inspect what *would* be injected (context preview)
without polluting the conversation.

## Citations

When grounding is on, answers cite the chunks they used as **`[n]` references**,
each traceable to a document in the store — verify claims by following the
reference to the source markdown.

## Conversations

Conversations are stored in the SQLite store (like datasets and documents) and
shown in the Activity feed. They are independent of datasets — use chat to
validate that retrieval answers correctly *before* generating dataset entries
grounded in the same corpus.

## Typical validation loop

```bash
minics scan ./docs          # 1. knowledge in
minics search "key topic"   # 2. check retrieval quality directly
# 3. open the app → Chat, toggle RAG + Grounding, ask the same question
# 4. follow the [n] citations back to the source documents
```

If retrieval is good but answers are poor, the problem is the model/prompt, not
the index — and vice versa.
