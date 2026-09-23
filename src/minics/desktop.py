"""Desktop shell: serve Flask locally and wrap it in a native window.

The default ``minics`` command lands here.  A ``werkzeug`` server runs on a
background thread bound to ``127.0.0.1``, and PyWebView renders the UI in a
native window.  If no GUI backend is available we fall back to the system
browser so the app is never unusable.
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Any

from minics.services.context import AppContext, get_context

LOGGER = logging.getLogger("minics.desktop")


def find_free_port(host: str = "127.0.0.1", preferred: int = 8765) -> int:
    """Return ``preferred`` if it is free, otherwise an arbitrary free port."""
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, candidate))
                return sock.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Could not find a free port.")


class ServerThread(threading.Thread):
    """Runs a werkzeug WSGI server until :meth:`stop` is called."""

    def __init__(self, app: Any, host: str, port: int) -> None:
        super().__init__(name="minics-http", daemon=True)
        from werkzeug.serving import make_server

        self._server = make_server(host, port, app, threaded=True)
        self.host = host
        self.port = port

    def run(self) -> None:  # pragma: no cover - thread body
        self._server.serve_forever()

    def stop(self) -> None:
        self._server.shutdown()


def run_app(
    home: str | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    debug: bool = False,
    width: int | None = None,
    height: int | None = None,
    title: str = "MiniCS Lite",
    ctx: AppContext | None = None,
) -> int:
    """Launch the desktop application (blocking)."""
    from minics.server.app import create_app

    ctx = ctx or get_context(home)
    ctx.ensure_ready()
    host = host or ctx.config.app.host or "127.0.0.1"
    port = port or find_free_port(host, ctx.config.app.port or 8765)
    width = width or ctx.config.app.window_width
    height = height or ctx.config.app.window_height

    app = create_app(ctx)
    server = ServerThread(app, host, port)
    server.start()
    url = f"http://{host}:{port}/"
    LOGGER.info("MiniCS desktop serving %s", url)

    try:
        import webview  # type: ignore
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception as exc:  # noqa: BLE001 - no GUI backend
        LOGGER.warning("PyWebView unavailable (%s); falling back to the browser.", exc)
        import webbrowser

        webbrowser.open(url)
        try:
            server.join()
        except KeyboardInterrupt:  # pragma: no cover
            pass
        finally:
            server.stop()
        return 0

    webview.create_window(
        title,
        url,
        width=width,
        height=height,
        min_size=(900, 600),
        text_select=True,
    )
    try:
        webview.start(debug=debug)
    finally:
        server.stop()
        ctx.close()
    return 0


def run_browser(
    home: str | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    debug: bool = False,
    open_browser: bool = True,
) -> int:
    """Run the plain web server (blocking) without the native window."""
    from minics.server.app import run_server
    from minics.services.context import get_context

    ctx = get_context(home)
    ctx.ensure_ready()
    run_server(host=host, port=port, debug=debug, open_browser=open_browser, ctx=ctx)
    return 0
