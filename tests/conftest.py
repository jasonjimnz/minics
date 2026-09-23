"""Shared pytest fixtures.

Every test runs against an isolated ``MINICS_HOME`` (a tmp dir) and uses
deterministic fake embeddings so no model server is required.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def fake_embed(monkeypatch):
    """Deterministic 8-dimension embeddings, monkeypatched everywhere."""

    def _embed(texts, config=None, **kwargs):
        vectors = []
        for text in texts:
            vector = [0.0] * 8
            for index, char in enumerate(text[:16]):
                vector[index % 8] += ord(char) % 17
            vectors.append(vector)
        return vectors

    import minics.rag.indexer as indexer
    import minics.rag.retriever as retriever

    monkeypatch.setattr(indexer, "embed_texts", _embed)
    monkeypatch.setattr(retriever, "embed_texts", _embed)
    return _embed


@pytest.fixture()
def home(tmp_path, monkeypatch) -> Path:
    target = tmp_path / "minics-home"
    monkeypatch.setenv("MINICS_HOME", str(target))
    return target


@pytest.fixture()
def ctx(home, fake_embed):
    from minics.services.context import AppContext, set_context

    context = AppContext(str(home))
    set_context(context)
    context.ensure_ready()
    yield context
    context.close()
    set_context(None)


@pytest.fixture()
def client(ctx):
    from minics.server.app import create_app

    app = create_app(ctx)
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _cleanup_managers():
    yield
    try:
        from minics.core.jobs import reset_job_manager

        reset_job_manager()
    except Exception:  # noqa: BLE001
        pass
    os.environ.pop("MINICS_HOME", None)
