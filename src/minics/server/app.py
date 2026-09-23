"""Flask application factory.

The server is deliberately thin: every endpoint delegates to the service layer on
an :class:`~minics.services.context.AppContext`, so the exact same behaviour is
available from Python without touching Flask.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify, render_template

from minics import __version__
from minics.core.paths import get_paths
from minics.server.api import register_blueprints
from minics.server.deps import CTX_KEY, register_error_handlers
from minics.services.context import AppContext, get_context

LOGGER = logging.getLogger("minics.server")


def create_app(
    ctx: AppContext | None = None,
    *,
    home: str | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> Flask:
    """Build the Flask app around an :class:`AppContext`."""
    app = Flask(
        __name__,
        static_folder="static",
        static_url_path="/static",
        template_folder="templates",
    )
    app.config["JSON_SORT_KEYS"] = False
    app.config["MINICS_VERSION"] = __version__

    if ctx is None:
        ctx = get_context()
    if config_overrides:
        ctx.update_config(config_overrides)
    app.config[CTX_KEY] = ctx

    register_blueprints(app)
    register_error_handlers(app)

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            version=__version__,
            bootstrap=ctx.config.public_dict(),
        )

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "version": __version__})

    LOGGER.info("MiniCS %s ready at %s", __version__, get_paths().root)
    return app


def run_server(
    host: str | None = None,
    port: int | None = None,
    *,
    debug: bool = False,
    ctx: AppContext | None = None,
    open_browser: bool | None = None,
) -> None:
    """Run the development server (blocking)."""
    import threading
    import webbrowser

    ctx = ctx or get_context()
    ctx.ensure_ready()
    host = host or ctx.config.app.host
    port = port or ctx.config.app.port
    app = create_app(ctx)

    should_open = ctx.config.app.open_browser if open_browser is None else open_browser
    url = f"http://{host}:{port}/"
    if should_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)
