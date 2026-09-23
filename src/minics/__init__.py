"""minics — a local-first studio for building high quality LLM datasets.

The public surface is intentionally small: everything is re-exported from this
package so the project can be used as a library, not only as a web app.

    >>> import minics
    >>> minics.__version__

"""

from __future__ import annotations

__all__ = ["__version__", "get_paths", "MinicsPaths"]

try:  # pragma: no cover - trivial metadata lookup
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _version

    try:
        __version__ = _version("minichat-studio")
    except PackageNotFoundError:
        __version__ = "0.3.0"
except Exception:  # pragma: no cover
    __version__ = "0.3.0"


from minics.core.paths import MinicsPaths, get_paths

__all__ += ["__version__"]




