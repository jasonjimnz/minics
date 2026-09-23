"""Model discovery across separate chat and embedding endpoints."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from minics.core.config import Config
from minics.llm.client import ModelInfo, list_available_models, split_models
from minics.llm.structured import (
    OutputTruncatedError,
    StructuredOutputError,
    invoke_structured,
)


def _config(llm: str, embedding: str) -> Config:
    config = Config()
    config.llm.base_url = llm
    config.embedding.base_url = embedding
    return config


def test_split_models_classification():
    models = [
        ModelInfo(id="llama-3.1-8b"),
        ModelInfo(id="nomic-embed-text"),
        ModelInfo(id="bge-m3"),
    ]
    split = split_models(models)
    assert split["chat"] == ["llama-3.1-8b"]
    assert split["embedding"] == ["nomic-embed-text", "bge-m3"]


def test_list_available_models_queries_both_endpoints(monkeypatch):
    calls: list[str] = []

    def fake_list_models(*, base_url, api_key="", timeout=30.0, client=None):
        calls.append(base_url)
        if "11434" in base_url:
            return [ModelInfo(id="nomic-embed-text"), ModelInfo(id="mxbai-embed-large")]
        return [ModelInfo(id="llama-3.1-8b-instruct")]

    monkeypatch.setattr("minics.llm.client.list_models", fake_list_models)

    config = _config("http://192.168.1.135:8000/v1", "http://192.168.1.130:11434/v1")
    result = list_available_models(config)

    assert result["chat"] == ["llama-3.1-8b-instruct"]
    assert result["embedding"] == ["nomic-embed-text", "mxbai-embed-large"]
    assert set(calls) == {"http://192.168.1.135:8000/v1", "http://192.168.1.130:11434/v1"}


def test_embedding_falls_back_to_llm_endpoint(monkeypatch):
    calls: list[str] = []

    def fake_list_models(*, base_url, api_key="", timeout=30.0, client=None):
        calls.append(base_url)
        return [ModelInfo(id="llama-3.1-8b"), ModelInfo(id="nomic-embed-text")]

    monkeypatch.setattr("minics.llm.client.list_models", fake_list_models)

    config = _config("http://llm:8000/v1", "")
    assert config.embedding_base_url == "http://llm:8000/v1"

    result = list_available_models(config)
    assert result["embedding"] == ["nomic-embed-text"]
    # Same server: the endpoint is only queried once.
    assert calls == ["http://llm:8000/v1"]


# ---------------------------------------------------------------------------
# Truncation handling in structured output
# ---------------------------------------------------------------------------
class _Schema(BaseModel):
    value: str


class _Truncated(Exception):
    def __init__(self):
        super().__init__("Could not parse response content as the length limit was reached")


class _Response:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.content = content
        self.response_metadata = {"finish_reason": finish_reason}


class _StructuredPath:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def invoke(self, messages):
        raise self.error


class _FakeChat:
    """Minimal stand-in for a LangChain chat model."""

    def __init__(self, *, structured_error: Exception, response: _Response) -> None:
        self.structured_error = structured_error
        self.response = response

    def with_structured_output(self, schema, method=None):
        return _StructuredPath(self.structured_error)

    def invoke(self, messages):
        return self.response


def _patch_chat(monkeypatch, fake: _FakeChat) -> None:
    monkeypatch.setattr("minics.llm.structured.build_chat_model", lambda *a, **k: fake)


def test_invoke_structured_raises_on_truncated_structured_output(monkeypatch):
    fake = _FakeChat(structured_error=_Truncated(), response=_Response('{"value": "ok"}'))
    _patch_chat(monkeypatch, fake)

    with pytest.raises(OutputTruncatedError, match="max_tokens=2048"):
        invoke_structured(_Schema, system="s", user="u", config=Config())


def test_invoke_structured_raises_on_truncated_text_fallback(monkeypatch):
    fake = _FakeChat(
        structured_error=ValueError("no tools"),
        response=_Response('{"value": "ok"}', finish_reason="length"),
    )
    _patch_chat(monkeypatch, fake)

    with pytest.raises(OutputTruncatedError, match="text"):
        invoke_structured(_Schema, system="s", user="u", config=Config())


def test_invoke_structured_still_raises_generic_error_without_json(monkeypatch):
    fake = _FakeChat(
        structured_error=ValueError("no tools"),
        response=_Response("no json here", finish_reason="stop"),
    )
    _patch_chat(monkeypatch, fake)

    with pytest.raises(StructuredOutputError):
        invoke_structured(_Schema, system="s", user="u", config=Config())


def test_clean_markdown_splits_and_retries_on_truncation(monkeypatch):
    from minics.llm import enhance

    calls: list[str] = []

    def fake_invoke(schema, *, user, **kwargs):
        calls.append(user)
        if len(calls) == 1:
            raise OutputTruncatedError("truncated")
        return enhance.MarkdownCleanup(markdown="cleaned", fixes=[])

    monkeypatch.setattr(enhance, "invoke_structured", fake_invoke)

    text = "\n\n".join(
        f"Paragraph {i} with a reasonable amount of words in it." for i in range(120)
    )
    result = enhance.clean_markdown(text, title="Doc")

    assert result.startswith("cleaned")
    assert len(calls) > 1
