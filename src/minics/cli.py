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
from pathlib import Path

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


def cmd_scan(args: argparse.Namespace) -> int:
    """Bulk-import every compatible document under a directory, one by one."""
    from minics.core.utils import sha256_bytes
    from minics.documents.convert import SUPPORTED_EXTENSIONS

    ctx = _ctx(args)
    ctx.ensure_ready()
    tags: list[str] | None = None
    if args.tags:
        tags = [t for raw in args.tags for t in raw.split(",") if t.strip()]

    root = Path(args.directory).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    root = root.resolve()
    if not root.is_dir():
        print(f"Error: '{root}' is not a directory.", file=sys.stderr)
        return 1

    # Format selection: no flag = every compatible format.
    kinds = {kind for ext, kind in SUPPORTED_EXTENSIONS.items()}
    selected: set[str] = set()
    for flag, kind in (
        ("markdown", "markdown"),
        ("txt", "text"),
        ("pdf", "pdf"),
        ("docx", "docx"),
        ("latex", "latex"),
    ):
        if getattr(args, flag):
            selected.add(kind)
    if not selected:
        selected = kinds
    extensions = {ext for ext, kind in SUPPORTED_EXTENSIONS.items() if kind in selected}

    _SKIP_DIRS = {
        ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
        ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
        ".agents", ".idea", ".vscode",
    }
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        parts = path.relative_to(root).parts[:-1]
        if any(part in _SKIP_DIRS or part.startswith(".") for part in parts):
            continue
        if path.suffix.lower() in extensions:
            files.append(path)

    if not files:
        print(
            f"No compatible documents found under {root} "
            f"(looking for {', '.join(sorted(extensions))})."
        )
        ctx.close()
        return 0

    print(
        f"Scanning {root} — {len(files)} document(s) "
        f"[{', '.join(sorted(selected))}]\n"
    )
    if args.dry_run:
        for path in files:
            print(f"  would import {path.relative_to(root)}")
        print(f"\nDry run: {len(files)} file(s) would be imported.")
        ctx.close()
        return 0

    imported, duplicates, failed = 0, 0, 0
    for position, path in enumerate(files, start=1):
        prefix = f"[{position:>3}/{len(files)}]"
        label = str(path.relative_to(root))
        try:
            existing = ctx.documents.repo.by_sha256(sha256_bytes(path.read_bytes()))
            if existing is not None and Path(existing.markdown_path).exists():
                duplicates += 1
                print(f"{prefix} SKIP    {label} (duplicate of '{existing.title}')")
                continue
            document = ctx.documents.import_file(
                path, tags=tags, source="scan", progress=lambda f, msg: None
            )
        except Exception as exc:  # noqa: BLE001 - keep scanning after failures
            failed += 1
            print(f"{prefix} FAILED  {label}: {exc}")
            continue
        if args.index:
            try:
                result = ctx.indexer.index_document(document.id)
                chunks = result.get("chunks", 0)
                graph_note = ""
                if ctx.graph.is_available():
                    try:
                        ctx.graph_indexer.index_document(document.id)
                        graph_note = " + graph"
                    except Exception as exc:  # noqa: BLE001
                        graph_note = f" (graph indexing failed: {exc})"
                print(f"{prefix} OK      {label} — indexed ({chunks} chunks{graph_note})")
            except Exception as exc:  # noqa: BLE001
                print(f"{prefix} PARTIAL {label} — imported but not indexed: {exc}")
        else:
            print(f"{prefix} OK      {label} — imported (not indexed)")
        imported += 1

    print(
        f"\nDone: {imported} imported, {duplicates} duplicate(s) skipped, "
        f"{failed} failed, {len(files)} total."
    )
    if failed:
        print("Tip: fix the failed files and re-run — duplicates are skipped automatically.")
    ctx.close()
    return 0 if failed == 0 else 1


def cmd_skills(args: argparse.Namespace) -> int:
    """Install or list the MiniCS agent skillset bundled with the package."""
    from minics.skills_install import (
        bundled_skills,
        default_target,
        install_skills,
        installed_version,
    )

    if args.action == "list" or args.list:
        target = default_target(args.global_)
        print("Bundled MiniCS skills:\n")
        for skill in bundled_skills():
            status = "installed" if installed_version(target, skill.name) else "not installed"
            print(f"  {skill.name:<18} [{status}] {skill.description}")
        print(f"\nDefault target: {target}")
        return 0

    target = Path(args.dir).expanduser() if args.dir else default_target(args.global_)
    names: list[str] | None = None
    if args.interactive:
        skills = bundled_skills()
        print("Select the skills to install (Enter = all, comma-separated numbers or names):\n")
        for index, skill in enumerate(skills, start=1):
            print(f"  {index:>2}. {skill.name:<18} {skill.description}")
        try:
            answer = input("\nSkills: ").strip()
        except EOFError:
            answer = ""
        if answer:
            chosen: set[str] = set()
            for token in answer.replace(",", " ").split():
                if token.isdigit() and 1 <= int(token) <= len(skills):
                    chosen.add(skills[int(token) - 1].name)
                else:
                    chosen.add(token)
            names = sorted(chosen)

    try:
        installed, skipped = install_skills(
            target,
            names=names,
            force=args.force,
        )
    except KeyError as exc:
        print(f"Error: {exc.args[0]}", file=sys.stderr)
        return 1

    if not installed and not skipped:
        print("Nothing to install.")
        return 0
    print(f"Installing MiniCS skills into {target}\n")
    for name in installed:
        print(f"  + {name}")
    for name in skipped:
        print(f"  = {name} (already installed, use --force to overwrite)")
    print(
        f"\nDone: {len(installed)} installed, {len(skipped)} skipped.\n"
        "Restart your agent so it picks up the new skills."
    )
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

    sp = add("scan", cmd_scan, "Bulk-import every compatible document in a directory tree.")
    sp.add_argument("directory", help="Directory to scan (absolute or relative to cwd).")
    sp.add_argument("--markdown", action="store_true", help="Include Markdown files.")
    sp.add_argument("--txt", action="store_true", help="Include plain text files.")
    sp.add_argument("--pdf", action="store_true", help="Include PDF files.")
    sp.add_argument("--docx", action="store_true", help="Include DOCX files.")
    sp.add_argument("--latex", action="store_true", help="Include LaTeX files.")
    sp.add_argument("--tags", nargs="*", default=None, help="Tags applied to every import.")
    sp.add_argument(
        "--no-index", dest="index", action="store_false", help="Import without indexing."
    )
    sp.add_argument(
        "--dry-run", action="store_true", help="List what would be imported, change nothing."
    )

    sp = add("skills", cmd_skills, "Install the bundled MiniCS agent skillset (.agents/skills).")
    sp.add_argument(
        "action",
        nargs="?",
        default="install",
        choices=["install", "list"],
        help="'install' (default) copies the bundled skills; 'list' shows them.",
    )
    sp.add_argument(
        "--global",
        dest="global_",
        action="store_true",
        help="Install to ~/.agents/skills instead of ./.agents/skills.",
    )
    sp.add_argument(
        "--interactive",
        action="store_true",
        help="Interactively pick which skills to install.",
    )
    sp.add_argument("--force", action="store_true", help="Overwrite already-installed skills.")
    sp.add_argument("--dir", metavar="PATH", help="Install into a custom directory.")
    sp.add_argument("--list", action="store_true", help="List bundled skills and exit.")

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
    # Windows consoles default to a legacy codepage (cp1252); keep the CLI
    # output encoding-safe instead of crashing on arrows and dashes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:  # noqa: BLE001 - best effort only
                pass
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
