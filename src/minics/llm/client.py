"""OpenAI-compatible LLM and embedding access.

Everything (chat, embeddings, structured output, model discovery) goes through
the **OpenAI protocol**.  That one decision means MiniCS works with OpenAI,
Azure-style gateways, llama.cpp, vLLM, LM Studio, Ollama's OpenAI shim and any
other compatible server without provider-specific code.

LangChain wrappers are built on top of the same client for higher level needs
(structured output, chains, callbacks).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from minics.core.config import Config, get_config

#: Sent when a local endpoint does not require a key but the SDK insists on one.
PLACEHOLDER_KEY = "not-needed"


class LLMError(RuntimeError):
    """Raised when the LLM/embedding endpoint cannot be reached or misbehaves."""


@dataclass
class ModelInfo:
    id: str
    owned_by: str = ""
    created: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "owned_by": self.owned_by, "created": self.created}


def _resolve(config: Config | None) -> Config:
    return config or get_config()


def _key(value: str) -> str:
    return value or PLACEHOLDER_KEY


# ---------------------------------------------------------------------------
# Raw OpenAI clients
# ---------------------------------------------------------------------------
def build_openai_client(config: Config | None = None, *, timeout: float | None = None):
    """Return a synchronous ``openai.OpenAI`` for the chat/LLM endpoint."""
    from openai import OpenAI

    cfg = _resolve(config)
    return OpenAI(
        base_url=cfg.llm.base_url or None,
        api_key=_key(cfg.llm.api_key),
        timeout=timeout or cfg.llm.timeout,
    )


def build_async_openai_client(config: Config | None = None, *, timeout: float | None = None):
    """Return an ``openai.AsyncOpenAI`` for the chat/LLM endpoint."""
    from openai import AsyncOpenAI

    cfg = _resolve(config)
    return AsyncOpenAI(
        base_url=cfg.llm.base_url or None,
        api_key=_key(cfg.llm.api_key),
        timeout=timeout or cfg.llm.timeout,
    )


def build_embeddings_client(config: Config | None = None, *, timeout: float | None = None):
    """Return a synchronous ``openai.OpenAI`` for the embedding endpoint.

    Falls back to the LLM base URL / key when the embedding section leaves them
    empty, which is how most single-endpoint setups are configured.
    """
    from openai import OpenAI

    cfg = _resolve(config)
    return OpenAI(
        base_url=cfg.embedding_base_url or None,
        api_key=_key(cfg.embedding_api_key),
        timeout=timeout or cfg.embedding.timeout,
    )


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------
def list_models(
    *,
    base_url: str,
    api_key: str = "",
    timeout: float = 30.0,
    client: Any | None = None,
) -> list[ModelInfo]:
    """List models exposed by an OpenAI-compatible endpoint.

    Returns an empty list (never raises) when the server does not implement
    ``GET /models`` — many local servers do not.
    """
    from openai import OpenAI

    try:
        client = client or OpenAI(
            base_url=base_url or None, api_key=_key(api_key), timeout=timeout
        )
        response = client.models.list()
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI as "unavailable"
        raise LLMError(f"Could not list models from {base_url or 'default'}: {exc}") from exc

    models: list[ModelInfo] = []
    for item in getattr(response, "data", []) or []:
        if isinstance(item, dict):
            models.append(
                ModelInfo(
                    id=item.get("id", ""),
                    owned_by=item.get("owned_by", "") or "",
                    created=int(item.get("created") or 0),
                    raw=item,
                )
            )
        else:
            models.append(
                ModelInfo(
                    id=getattr(item, "id", ""),
                    owned_by=getattr(item, "owned_by", "") or "",
                    created=int(getattr(item, "created", 0) or 0),
                )
            )
    return sorted(models, key=lambda m: m.id.lower())


#: Heuristics for separating embedding models from chat models in a model list.
_EMBED_HINTS = ("embed", "embedding", "bge", "e5", "gte", "nomic", "mxbai", "voyage")


def is_embedding_model(model_id: str) -> bool:
    return any(hint in model_id.lower() for hint in _EMBED_HINTS)


def is_chat_model(model_id: str) -> bool:
    """Anything that is not obviously an embedding model is treated as chat."""
    return not is_embedding_model(model_id)


def split_models(models: Iterable[ModelInfo]) -> dict[str, list[str]]:
    """Split a model list into ``{"chat": [...], "embedding": [...]}``."""
    chat, embed = [], []
    for model in models:
        (embed if is_embedding_model(model.id) else chat).append(model.id)
    return {"chat": chat, "embedding": embed}


def list_available_models(config: Config | None = None) -> dict[str, list[str]]:
    """List models for the chat and embedding endpoints.

    The two endpoints may be different servers (e.g. llama-server for chat and
    Ollama for embeddings), so each is queried and classified independently.
    """
    cfg = _resolve(config)
    chat: list[str] = []
    embedding: list[str] = []
    llm_models: list[ModelInfo] = []

    try:
        llm_models = list_models(base_url=cfg.llm.base_url, api_key=cfg.llm.api_key)
        chat = split_models(llm_models)["chat"]
    except LLMError:
        pass

    if cfg.embedding_base_url and cfg.embedding_base_url != cfg.llm.base_url:
        try:
            embedding = split_models(
                list_models(
                    base_url=cfg.embedding_base_url, api_key=cfg.embedding_api_key
                )
            )["embedding"]
        except LLMError:
            pass
    elif llm_models:
        embedding = split_models(llm_models)["embedding"]

    return {"chat": chat, "embedding": embedding}


# ---------------------------------------------------------------------------
# LangChain wrappers
# ---------------------------------------------------------------------------
def build_chat_model(
    config: Config | None = None,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    **overrides: Any,
):
    """Build a :class:`langchain_openai.ChatOpenAI` from the config."""
    from langchain_openai import ChatOpenAI

    cfg = _resolve(config)
    settings = cfg.llm
    params: dict[str, Any] = {
        "model": model or settings.model,
        "base_url": settings.base_url or None,
        "api_key": _key(settings.api_key),
        "temperature": settings.temperature if temperature is None else temperature,
        "max_tokens": settings.max_tokens if max_tokens is None else max_tokens,
        "top_p": settings.top_p,
        "timeout": settings.timeout,
        "max_retries": 2,
    }
    if settings.extra:
        params["model_kwargs"] = dict(settings.extra)
    params.update(overrides)
    return ChatOpenAI(**params)


def build_embeddings(config: Config | None = None, **overrides: Any):
    """Build a :class:`langchain_openai.OpenAIEmbeddings` from the config.

    ``check_embedding_ctx_length=False`` is important: it stops LangChain from
    tokenising with tiktoken, which does not know about local embedding models.
    """
    from langchain_openai import OpenAIEmbeddings

    cfg = _resolve(config)
    settings = cfg.embedding
    params: dict[str, Any] = {
        "model": settings.model,
        "openai_api_base": cfg.embedding_base_url or None,
        "openai_api_key": _key(cfg.embedding_api_key),
        "chunk_size": settings.batch_size,
        "check_embedding_ctx_length": False,
        "timeout": settings.timeout,
        "max_retries": 2,
    }
    params.update(overrides)
    return OpenAIEmbeddings(**params)


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------
def embed_texts(
    texts: Sequence[str],
    config: Config | None = None,
    *,
    client: Any | None = None,
) -> list[list[float]]:
    """Embed ``texts`` using the configured embedding endpoint.

    Batching is handled explicitly so progress can be reported by callers.
    """
    if not texts:
        return []
    cfg = _resolve(config)
    if not cfg.embedding.model:
        raise LLMError("No embedding model configured.")
    client = client or build_embeddings_client(cfg)
    try:
        response = client.embeddings.create(
            model=cfg.embedding.model,
            input=list(texts),
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"Embedding request failed: {exc}") from exc
    # Preserve input order regardless of server behaviour.
    ordered = sorted(response.data, key=lambda d: getattr(d, "index", 0))
    return [list(item.embedding) for item in ordered]


def probe_embedding_dimension(text: str = "dimension probe", config: Config | None = None) -> int:
    """Embed a single short string and return the vector size."""
    vectors = embed_texts([text], config)
    if not vectors:
        raise LLMError("Embedding endpoint returned no vectors.")
    return len(vectors[0])


def test_connection(config: Config | None = None) -> dict[str, Any]:
    """Check chat + embedding reachability and detect the embedding dimension.

    Returns a structured report instead of raising so the setup wizard can show
    partial success.
    """
    cfg = _resolve(config)
    report: dict[str, Any] = {
        "ok": False,
        "chat": {"ok": False, "error": None, "model": cfg.llm.model},
        "embedding": {"ok": False, "error": None, "model": cfg.embedding.model,
                      "dimension": cfg.embedding.dimension},
        "models": {"chat": [], "embedding": []},
    }

    try:
        client = build_openai_client(cfg, timeout=20.0)
        client.chat.completions.create(
            model=cfg.llm.model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        report["chat"]["ok"] = True
    except Exception as exc:  # noqa: BLE001
        report["chat"]["error"] = str(exc)

    try:
        dimension = probe_embedding_dimension(config=cfg)
        report["embedding"]["ok"] = True
        report["embedding"]["dimension"] = dimension
    except Exception as exc:  # noqa: BLE001
        report["embedding"]["error"] = str(exc)

    try:
        report["models"] = list_available_models(cfg)
    except LLMError:
        pass

    report["ok"] = bool(report["chat"]["ok"] and report["embedding"]["ok"])
    return report
