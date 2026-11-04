"""OpenAI-compatible proxy server tests (mocked LLM + fake embeddings)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from minics.proxy.app import create_proxy_app
from minics.proxy.schemas import ChatCompletionRequest


class FakeCompletions:
    """Mimics ``openai`` chat completions for the upstream call."""

    def __init__(self, captured):
        self.captured = captured

    def create(self, **kwargs):
        self.captured.append(kwargs)
        content = f"answer to: {kwargs['messages'][-1]['content']}"
        if kwargs.get("stream"):
            return iter(
                _chunk({"delta": {"content": piece}, "index": 0}) for piece in ("hel", "lo ")
            )

        return _response({"role": "assistant", "content": content})


class _Obj:
    def __init__(self, data):
        self._data = data

    def model_dump(self, exclude_none=True):
        return self._data


def _response(message):
    return _Obj(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": "fake",
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        }
    )


def _chunk(delta):
    return _Obj(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "fake",
            "choices": [delta],
        }
    )


@pytest.fixture()
def proxy(ctx, monkeypatch):
    import minics.proxy.app as proxy_app

    captured: list[dict] = []

    class _FakeClient:
        def __init__(self, captured):
            self.chat = type("Chat", (), {})()
            self.chat.completions = FakeCompletions(captured)

    monkeypatch.setattr(
        proxy_app, "build_openai_client", lambda config=None, **kw: _FakeClient(captured)
    )

    ctx.update_config(
        {
            "llm": {"base_url": "http://fake.local/v1", "model": "fake", "api_key": "test"},
            "embedding": {"model": "fake-embed", "dimension": 8},
        }
    )
    document = ctx.documents.add_text(
        "# Proxy Doc\n\nThe proxy injects retrieved context before calling the LLM.",
        title="Proxy Doc",
    )
    ctx.indexer.index_document(document.id)
    app = create_proxy_app(ctx)
    return TestClient(app), captured


def test_chat_completion_grounded_with_metadata(proxy):
    client, captured = proxy
    response = client.post(
        "/v1/chat/completions",
        json={"model": "fake", "messages": [{"role": "user", "content": "proxy injects?"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"].startswith("answer to")
    metadata = body["minics"]
    assert metadata["version"]
    assert metadata["grounded"] is True
    assert metadata["retrieval"]["used"] is True
    assert metadata["retrieval"]["documents"][0]["title"] == "Proxy Doc"
    assert metadata["retrieval"]["citations"]
    # The upstream call must contain the grounding system prompt.
    upstream_messages = captured[0]["messages"]
    assert upstream_messages[0]["role"] == "system"
    assert "References:" in upstream_messages[0]["content"]


def test_chat_completion_without_grounding(proxy):
    client, captured = proxy
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hello"}],
            "minics": {"use_grounding": False},
        },
    )
    assert response.status_code == 200
    assert response.json()["minics"]["grounded"] is False
    assert captured[0]["messages"][0]["role"] == "user"


def test_streaming_chunks_carry_metadata_first(proxy):
    client, _ = proxy
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "proxy injects?"}],
            "stream": True,
        },
    ) as response:
        assert response.status_code == 200
        events = [
            line.removeprefix("data: ")
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]
    assert events[-1] == "[DONE]"
    payloads = [json.loads(event) for event in events[:-1]]
    first = payloads[0]
    assert first["minics"]["grounded"] is True
    assert first["choices"][0]["delta"]["content"] == "hel"
    assert payloads[1]["choices"][0]["delta"]["content"] == "lo "
    assert "minics" not in payloads[1]


def test_models_and_health(proxy):
    client, _ = proxy
    health = client.get("/health").json()
    assert health["service"] == "minics-proxy"
    assert health["version"]
    models = client.get("/v1/models").json()
    assert models["object"] == "list"
    assert models["data"][0]["id"]


def test_request_schema_tolerates_openai_extras():
    request = ChatCompletionRequest.model_validate(
        {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "frequency_penalty": 0.5,
            "unknown_future_field": {"a": 1},
        }
    )
    assert request.messages[0].content == "hi"
    assert request.minics is None
