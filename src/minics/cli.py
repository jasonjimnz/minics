"""Command line interface for MiniCS.

Running ``minics`` with no arguments launches the desktop application.  The
server, setup wizard and library helpers are all available as subcommands, and
every one of them works against the same ``~/.minics`` store.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable

from minics import __version__
from minics.core.config import get_config_manager
from minics.core.paths import get_paths


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _ctx(args: argparse.Namespace):
    """Build the app context, creating the home + running migrations on first use."""
    from minics.services.context import get_context

    ctx = get_context(getattr(args, "home", None))
    ctx.ensure_ready()
    return ctx


def _print(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_version(args: argparse.Namespace) -> int:
    """Print the installed MiniCS version."""
    print(f"minics {__version__}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    """Show the resolved paths and initialisation state."""
    paths = get_paths(args.home)
    _print(
        {
            "version": __version__,
            "home": str(paths.root),
            "initialized": paths.exists(),
            "config": str(paths.config_file),
            "database": str(paths.database),
            "vectordb": str(paths.vectordb),
            "graphdb": str(paths.graph_file),
            "documents": str(paths.documents),
        }
    )
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Create the MiniCS home directory structure."""
    paths = get_paths(args.home).ensure()
    ctx = _ctx(args)
    ctx.ensure_ready()
    ctx.close()
    print(f"Initialised MiniCS home at {paths.root}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Show or update configuration (secrets are masked)."""
    manager = get_config_manager(get_paths(args.home))
    if args.set:
        try:
            manager.update(json.loads(args.set))
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON patch: {exc}", file=sys.stderr)
            return 2
    _print(manager.load().public_dict())
    return 0


def cmd_app(args: argparse.Namespace) -> int:
    """Launch the desktop application (default command)."""
    from minics.desktop import run_app

    return run_app(args.home, port=args.port, debug=args.debug)


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the web server (open it in a browser)."""
    from minics.desktop import run_browser

    return run_browser(
        args.home,
        host=args.host,
        port=args.port,
        debug=args.debug,
        open_browser=not args.no_browser,
    )


def cmd_setup(args: argparse.Namespace) -> int:
    """Configure LLM and embedding endpoints (interactive or via flags)."""
    from minics.llm.client import (
        LLMError,
        probe_embedding_dimension,
        test_connection,
    )

    ctx = _ctx(args)
    patch: dict = {"llm": {}, "embedding": {}}
    interactive = not any([args.base_url, args.model, args.embedding_model])

    if interactive:
        print("MiniCS setup wizard (press Enter to keep the current value)\n")
        current = ctx.config
        patch["llm"]["base_url"] = _ask("LLM base URL", current.llm.base_url)
        patch["llm"]["api_key"] = _ask("LLM API key", current.llm.api_key, secret=True)
        models = _safe_models(patch["llm"]["base_url"], patch["llm"]["api_key"])
        if models["chat"]:
            print("Available chat models:", ", ".join(models["chat"][:20]))
        patch["llm"]["model"] = _ask("Chat model", current.llm.model)
        patch["embedding"]["base_url"] = _ask(
            "Embedding base URL (blank = same as LLM)", current.embedding.base_url
        ) or patch["llm"]["base_url"]
        patch["embedding"]["api_key"] = _ask(
            "Embedding API key (blank = same as LLM)", current.embedding.api_key, secret=True
        ) or patch["llm"]["api_key"]
        if models["embedding"]:
            print("Available embedding models:", ", ".join(models["embedding"][:20]))
        patch["embedding"]["model"] = _ask("Embedding model", current.embedding.model)
    else:
        patch["llm"]["base_url"] = args.base_url or ctx.config.llm.base_url
        patch["llm"]["api_key"] = args.api_key or ctx.config.llm.api_key
        patch["llm"]["model"] = args.model or ctx.config.llm.model
        patch["embedding"]["base_url"] = args.embedding_base_url or patch["llm"]["base_url"]
        patch["embedding"]["api_key"] = args.embedding_api_key or patch["llm"]["api_key"]
        patch["embedding"]["model"] = args.embedding_model or ctx.config.embedding.model

    if args.temperature is not None:
        patch["llm"]["temperature"] = args.temperature
    if args.max_tokens is not None:
        patch["llm"]["max_tokens"] = args.max_tokens

    ctx.update_config(patch)

    dimension = args.embedding_dimension
    if dimension is None and patch["embedding"]["model"]:
        try:
            dimension = probe_embedding_dimension(config=ctx.config)
            print(f"Detected embedding dimension: {dimension}")
        except LLMError as exc:
            print(f"Could not detect embedding dimension: {exc}", file=sys.stderr)
    if dimension:
        ctx.update_config({"embedding": {"dimension": dimension}})

    if args.test or interactive:
        report = test_connection(ctx.config)
        _print(report)
        if report["ok"]:
            ctx.config_manager.mark_setup_complete()
            print("Setup complete.")
        else:
            print("Setup saved, but the connection test failed.", file=sys.stderr)
    _print(ctx.config.public_dict())
    ctx.close()
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    """List the models advertised by the configured endpoint."""
    from minics.llm.client import LLMError, list_models, split_models

    ctx = _ctx(args)
    try:
        models = split_models(
            list_models(
                base_url=args.base_url or ctx.config.llm.base_url,
                api_key=args.api_key or ctx.config.llm.api_key,
            )
        )
    except LLMError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    _print(models)
    return 0


def cmd_datasets(args: argparse.Namespace) -> int:
    """List or create datasets."""
    ctx = _ctx(args)
    ctx.ensure_ready()
    if args.create:
        dataset = ctx.datasets.create(args.create, description=args.description or "")
        _print(dataset.to_dict())
    else:
        items = [d.to_dict() | {"stats": ctx.datasets.stats(d.id)} for d in ctx.datasets.list()]
        _print(items)
    ctx.close()
    return 0


def cmd_entries(args: argparse.Namespace) -> int:
    """List entries (optionally filtered)."""
    ctx = _ctx(args)
    ctx.ensure_ready()
    entries = ctx.entries.list(
        dataset=args.dataset, status=args.status, search=args.search, limit=args.limit
    )
    _print([e.to_dict() for e in entries])
    ctx.close()
    return 0


def cmd_documents(args: argparse.Namespace) -> int:
    """Import, list or index documents."""
    ctx = _ctx(args)
    ctx.ensure_ready()
    if args.import_:
        for path in args.import_:
            document = ctx.documents.import_file(path)
            print(f"Imported '{document.title}' -> {document.public_id}")
            if args.index:
                ctx.indexer.index_document(document.id)
                try:
                    if ctx.graph.is_available():
                        ctx.graph_indexer.index_document(document.id)
                except Exception as exc:  # noqa: BLE001
                    print(f"  graph indexing failed: {exc}", file=sys.stderr)
    elif getattr(args, "index_ref", None):
        ctx.indexer.index_document(args.index_ref)
        if ctx.graph.is_available():
            ctx.graph_indexer.index_document(args.index_ref)
        print("Indexed.")
    else:
        _print([d.to_dict() for d in ctx.documents.list(search=args.search)])
    ctx.close()
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    """Re-index every document for the vector store and graph."""
    ctx = _ctx(args)
    ctx.ensure_ready()
    result = ctx.indexer.reindex_all()
    if ctx.graph.is_available():
        result["graph"] = ctx.graph_indexer.reindex_all()
    _print(result)
    ctx.close()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Export a collection to a file (or stdout)."""
    ctx = _ctx(args)
    ctx.ensure_ready()
    content = ctx.collections.export(
        args.collection, fmt=args.format, include_metadata=args.include_metadata,
        only_approved=args.approved,
    )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(content)
        print(f"Wrote {len(content)} characters to {args.output}")
    else:
        print(content)
    ctx.close()
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Run hybrid retrieval (vector + graph) against the document index."""
    ctx = _ctx(args)
    ctx.ensure_ready()
    result = ctx.retriever.retrieve(
        args.query, top_k=args.top_k, use_rag=not args.no_rag, use_graph=not args.no_graph
    )
    _print(result.to_dict())
    ctx.close()
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------
def _ask(prompt: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        value = ""
    return value or default


def _safe_models(base_url: str, api_key: str) -> dict:
    from minics.llm.client import LLMError, list_models, split_models

    if not base_url:
        return {"chat": [], "embedding": []}
    try:
        return split_models(list_models(base_url=base_url, api_key=api_key))
    except LLMError:
        return {"chat": [], "embedding": []}


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--home", default=None, help="Override the MiniCS home directory.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="minics", description="MiniCS Lite — build high quality LLM datasets locally."
    )
    parser.add_argument("--version", action="version", version=f"minics {__version__}")
    parser.add_argument(
        "--home",
        default=None,
        help="Override the MiniCS home directory (also accepted after a command).",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def add(name: str, func: Callable, help_text: str):
        sp = sub.add_parser(name, help=help_text)
        _add_common(sp)
        sp.set_defaults(func=func)
        return sp

    # config
    sp = add("config", cmd_config, "Show or update configuration.")
    sp.add_argument("--set", metavar="JSON", help="Deep-merge a JSON object into the config.")

    add("version", cmd_version, "Print the version.")
    add("info", cmd_info, "Show resolved paths.")
    add("init", cmd_init, "Create the ~/.minics structure.")

    sp = add("app", cmd_app, "Launch the desktop app (default).")
    sp.add_argument("--port", type=int, default=None)
    sp.add_argument("--debug", action="store_true")

    sp = add("serve", cmd_serve, "Run the web server in a browser.")
    sp.add_argument("--host", default=None)
    sp.add_argument("--port", type=int, default=None)
    sp.add_argument("--debug", action="store_true")
    sp.add_argument("--no-browser", action="store_true")

    sp = add("setup", cmd_setup, "Configure LLM and embedding endpoints.")
    sp.add_argument("--base-url")
    sp.add_argument("--api-key")
    sp.add_argument("--model")
    sp.add_argument("--embedding-base-url")
    sp.add_argument("--embedding-api-key")
    sp.add_argument("--embedding-model")
    sp.add_argument("--embedding-dimension", type=int)
    sp.add_argument("--temperature", type=float)
    sp.add_argument("--max-tokens", type=int)
    sp.add_argument("--test", action="store_true")

    sp = add("models", cmd_models, "List available models.")
    sp.add_argument("--base-url")
    sp.add_argument("--api-key")

    sp = add("datasets", cmd_datasets, "List or create datasets.")
    sp.add_argument("--create", metavar="NAME")
    sp.add_argument("--description")

    sp = add("entries", cmd_entries, "List entries.")
    sp.add_argument("--dataset")
    sp.add_argument("--status")
    sp.add_argument("--search")
    sp.add_argument("--limit", type=int)

    sp = add("documents", cmd_documents, "Import, list or index documents.")
    sp.add_argument("--import", dest="import_", nargs="+", metavar="PATH")
    sp.add_argument("--search")
    sp.add_argument("--index-ref", dest="index_ref", metavar="REF", help="Index one document.")
    sp.add_argument(
        "--no-index", dest="index", action="store_false", help="Skip indexing on import."
    )

    add("reindex", cmd_reindex, "Re-index all documents.")

    sp = add("export", cmd_export, "Export a collection.")
    sp.add_argument("collection")
    sp.add_argument("--format", default="chatml")
    sp.add_argument("--output", "-o")
    sp.add_argument("--include-metadata", action="store_true")
    sp.add_argument("--approved", action="store_true")

    sp = add("search", cmd_search, "Hybrid retrieval over the document index.")
    sp.add_argument("query")
    sp.add_argument("--top-k", type=int, default=None)
    sp.add_argument("--no-rag", action="store_true")
    sp.add_argument("--no-graph", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        # No subcommand: launch the desktop application, keeping global options.
        args.func = cmd_app
        args.home = getattr(args, "home", None)
        args.port = getattr(args, "port", None)
        args.debug = getattr(args, "debug", False)
        func = cmd_app
    try:
        return int(func(args) or 0)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
