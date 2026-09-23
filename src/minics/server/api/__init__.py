"""REST API blueprints."""

from __future__ import annotations

from flask import Flask

from minics.server.api import (
    chat,
    collections,
    datasets,
    documents,
    entries,
    jobs,
    retrieval,
    system,
)

BLUEPRINTS = (
    system.bp,
    datasets.bp,
    entries.bp,
    collections.bp,
    documents.bp,
    chat.bp,
    jobs.bp,
    retrieval.bp,
)


def register_blueprints(app: Flask, *, url_prefix: str | None = None) -> None:
    """Register every API blueprint.

    Blueprints already carry their own ``/api/...`` prefix; ``url_prefix`` is
    only used to override it (handy in tests).
    """
    for blueprint in BLUEPRINTS:
        if url_prefix is None:
            app.register_blueprint(blueprint)
        else:
            app.register_blueprint(blueprint, url_prefix=url_prefix)

