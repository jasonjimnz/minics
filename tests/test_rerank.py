"""Rerank configuration, client and retrieval integration."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from minics.core.config import Config


@pytest.fixture()
def rerank_server():
    """Cohere-compatible /rerank mock scoring docs by keyword overlap."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib naming
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            query = set(body["query"].lower().split())
            results = [
                {
                    "index": index,
                    "relevance_score": len(query & set(doc.lower().split())) / max(1, len(query)),
                }
                for index, doc in enumerate(body["documents"])
            ]
            results.sort(key=lambda item: -item["relevance_score"])
            if "top_n" in body:
                results = results[: body["top_n"]]
            payload = json.dumps({"results": results}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # pragma: no cover
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", server
    server.shutdown()


def test_rerank_disabled_by_default():
    config = Config()
    assert config.retrieval.rerank.enabled is False
    assert config.rerank_ready is False


def test_rerank_ready_requires_model_and_url():
    config = Config()
    config.retrieval.rerank.enabled = True
    config.llm.base_url = "http://localhost:1234/v1"
    assert config.rerank_ready is False  # no model yet
    config.retrieval.rerank.model = "bge-reranker-v2-m3"
    assert config.rerank_ready is True
    assert config.rerank_base_url == "http://localhost:1234/v1"  # falls back to LLM URL


def test_rerank_key_masking_and_roundtrip(tmp_path):
    from minics.core.config import ConfigManager
    from minics.core.paths import MinicsPaths

    paths = MinicsPaths(root=tmp_path / "home")
    paths.ensure()
    manager = ConfigManager(paths)
    manager.update({"retrieval": {"rerank": {"enabled": True, "model": "m", "api_key": "sk-1"}}})
    masked = manager.load().public_dict()["retrieval"]["rerank"]
    assert masked["api_key"] == "********" and masked["api_key_set"] is True
    # Submitting the mask back keeps the stored secret.
    manager.update({"retrieval": {"rerank": {"api_key": "********"}}})
    assert manager.load().retrieval.rerank.api_key == "sk-1"


def test_rerank_docs_against_cohere_compatible_endpoint(rerank_server):
    from minics.llm.client import LLMError, rerank_docs

    url, _ = rerank_server
    config = Config()
    config.retrieval.rerank.model = "mock"
    config.retrieval.rerank.base_url = url
    ranked = rerank_docs("scoring dims", ["about scoring dimensions", "unrelated"], config)
    assert ranked[0]["index"] == 0 and ranked[0]["score"] > ranked[-1]["score"]

    config.retrieval.rerank.model = ""
    with pytest.raises(LLMError):
        rerank_docs("q", ["a"], config)


def test_retriever_applies_rerank(ctx, fake_embed, rerank_server):
    url, _ = rerank_server
    ctx.update_config(
        {
            "retrieval": {
                "rerank": {
                    "enabled": True,
                    "model": "mock",
                    "base_url": url,
                    "pool": 8,
                }
            }
        }
    )
    document = ctx.documents.add_text(
        "# Reranking\n\nA cross-encoder reranker reorders fused retrieval candidates "
        "by relevance.\n\n## Fallback\n\nOn failure MiniCS keeps the fused order.",
        title="Rerank Notes",
    )
    ctx.indexer.index_document(document.id)
    result = ctx.retriever.retrieve("reranker reorders candidates")
    assert result.diagnostics.get("rerank") is True
    assert all(chunk.rerank_score >= 0 for chunk in result.chunks)
    assert any("rerank" in chunk.sources for chunk in result.chunks)
    assert any("rerank" in chunk.ranks for chunk in result.chunks)
    serialized = result.to_dict()["chunks"][0]
    assert "rerank_score" in serialized


def test_retriever_degrades_gracefully_on_rerank_failure(ctx, fake_embed):
    ctx.update_config(
        {
            "retrieval": {
                "rerank": {
                    "enabled": True,
                    "model": "mock",
                    "base_url": "http://127.0.0.1:1",  # nothing listens here
                }
            }
        }
    )
    document = ctx.documents.add_text(
        "# Resilience\n\nRetrieval still returns results when the reranker is down.",
        title="Resilience Notes",
    )
    ctx.indexer.index_document(document.id)
    result = ctx.retriever.retrieve("resilience reranker down")
    assert result.chunks  # still answered by the fused ranking
    assert result.diagnostics.get("rerank") is False
