---
name: minics-documents
description: Import and bulk-ingest documents into MiniCS — `minics scan` for whole directories, single-file imports, supported formats (PDF, TXT, Markdown, DOCX, LaTeX), indexing into ChromaDB vectors and the Ladybug graph, and full reindexing. Use when adding knowledge/source files to a MiniCS store or fixing index problems.
---

# MiniCS documents

Every imported file is converted to **clean markdown** — that markdown is what
gets chunked, embedded into ChromaDB, and mined for graph entities. Originals
are kept untouched in `~/.minics/documents/originals/`.

## Supported formats

`.pdf`, `.txt`/`.text`, `.md`/`.markdown`, `.docx`, `.tex`/`.latex`/`.ltx`.

## Bulk-scan a directory: `minics scan`

Imports **every compatible document** found under a directory (absolute or
relative to the current working dir), one file at a time, with live terminal
progress per file (convert → index → graph):

```bash
minics scan ./papers                  # all supported formats, recursive
minics scan /abs/path/to/docs --pdf --txt   # only PDFs and TXT
minics scan ./notes --markdown        # only Markdown
minics scan ./docs --tags manuals,v2  # tag every imported document
minics scan ./docs --dry-run          # list what would be imported, change nothing
minics scan ./docs --no-index         # import only; index later with `minics reindex`
```

Format flags: `--markdown`, `--txt`, `--pdf`, `--docx`, `--latex`. With **no
format flag, all compatible formats are used**. Hidden directories and common
vendor/venv folders are skipped. Duplicate files (same SHA-256) are detected
and skipped. Per-file failures are reported and scanning continues; a summary
table is printed at the end.

## Single files

```bash
minics documents --import paper.pdf handbook.md --index
minics documents                      # list documents
minics documents --search "fusion"    # search titles/sources
```

`--index` indexes after import (vector + graph). Without it the document sits
unindexed until `minics reindex`.

## Indexing

```bash
minics reindex                        # rebuild vector index + graph for ALL documents
```

Chunking follows the markdown structure (headings), using the configured
`chunk_size` / `chunk_overlap` from the retrieval settings.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "Unsupported file type" | Only the formats above are convertible. Pre-convert others to Markdown/PDF. |
| Scan skipped a file as duplicate | Its SHA-256 already exists in the store — intended behaviour. |
| Document indexed but search is empty | Embeddings endpoint down during indexing → run `minics reindex`. |
| Graph empty | Graph needs a working chat LLM for entity extraction; check `minics setup --test`. |
