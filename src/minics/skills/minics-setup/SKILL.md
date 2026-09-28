---
name: minics-setup
description: Configure MiniCS LLM and embedding endpoints — interactive wizard or flags, model listing, connection testing and embedding-dimension detection. Use when setting up MiniCS, changing endpoints/API keys, or troubleshooting a failed connection.
---

# MiniCS setup

MiniCS talks to models exclusively over the **OpenAI protocol**
(`/v1/chat/completions` + `/v1/embeddings`). The chat LLM and the embedding
model may live on **different servers** — that split-endpoint setup is first
class.

## Interactive wizard

```bash
minics setup
```

Prompts for: LLM base URL, API key, chat model, embedding base URL/key/model
(blank = inherit the LLM values). It lists available models from the endpoint,
detects the embedding dimension automatically, runs a connection test, and
marks setup complete on success.

## Non-interactive (flags)

```bash
minics setup \
  --base-url http://localhost:8000/v1 \
  --api-key sk-... \
  --model qwen3-8b \
  --embedding-base-url http://localhost:11434/v1 \
  --embedding-api-key ollama \
  --embedding-model bge-m3 \
  --test
```

Useful flags: `--embedding-dimension N` (skip auto-detection), `--temperature`,
`--max-tokens`, `--test`.

## Model discovery

```bash
minics models                          # uses configured endpoints
minics models --base-url http://... --api-key ...
```

Prints JSON: `{"chat": [...], "embedding": [...]}`.

## Configuration file

Everything is stored in `~/.minics/config.json` (secrets masked in CLI output).
Patch it directly:

```bash
minics config --set '{"llm": {"temperature": 0.2}}'
minics config                          # show current config
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Connection test fails | Hit `{base_url}/models` with curl; the base URL must include `/v1` for most servers. |
| Embedding dimension errors | Chroma collections are created with the detected dimension — if you change embedding models, re-create the store or set `--embedding-dimension` explicitly and `minics reindex`. |
| Model list is empty | Some gateways don't implement `/v1/models`; type the model name manually in the wizard. |
| Wrong home used | `MINICS_HOME` env var or `--home PATH` overrides `~/.minics`. |

Verify state at any time:

```bash
minics info      # resolved paths + initialised flag
minics version
```
