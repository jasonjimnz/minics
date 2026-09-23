"""Application configuration.

The config lives in ``~/.minics/config.json`` and is the single source of truth
for how MiniCS talks to the LLM/embedding endpoints and how it behaves.

Design choices:

* **pydantic v2 models** so validation and JSON (de)serialisation are free.
* **OpenAI-first** — every provider is reached through an OpenAI-compatible
  ``base_url`` + ``api_key`` + model name.  Local servers (llama.cpp, vLLM,
  Ollama's OpenAI shim, LM Studio, ...) all work.
* **Masking** — :meth:`Config.public_dict` hides secrets before the config is
  sent to the browser.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from minics.core.paths import MinicsPaths, get_paths

#: Placeholder returned to the UI instead of a real key.
SECRET_MASK = "********"


class LLMSettings(BaseModel):
    """Chat completion endpoint settings."""

    base_url: str = Field(default="", description="OpenAI-compatible base URL.")
    api_key: str = Field(default="", description="API key (may be empty for local).")
    model: str = Field(default="", description="Default chat model name.")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: int = Field(default=2048, ge=1)
    timeout: float = Field(default=120.0, ge=1.0)
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra body params forwarded verbatim to the endpoint.",
    )

    @field_validator("base_url")
    @classmethod
    def _strip_url(cls, value: str) -> str:
        return value.strip().rstrip("/")


class EmbeddingSettings(BaseModel):
    """Embedding endpoint settings.

    ``dimension`` is required: ChromaDB collections are created with an explicit
    dimensionality and it must match whatever the embedding model returns.
    """

    base_url: str = Field(default="", description="OpenAI-compatible base URL.")
    api_key: str = Field(default="", description="API key (may be empty for local).")
    model: str = Field(default="", description="Embedding model name.")
    dimension: int = Field(default=0, ge=0, description="Embedding vector size.")
    batch_size: int = Field(default=64, ge=1, le=2048)
    chunk_size: int = Field(default=1000, ge=100, le=8000)
    chunk_overlap: int = Field(default=150, ge=0, le=2000)
    timeout: float = Field(default=120.0, ge=1.0)

    @field_validator("base_url")
    @classmethod
    def _strip_url(cls, value: str) -> str:
        return value.strip().rstrip("/")


class RetrievalSettings(BaseModel):
    """Retrieval / grounding behaviour."""

    top_k: int = Field(default=8, ge=1, le=100)
    candidates: int = Field(default=24, ge=1, le=500, description="Per-retriever pool size.")
    rrf_k: int = Field(default=60, ge=1, le=1000, description="RRF smoothing constant.")
    vector_weight: float = Field(default=1.0, ge=0.0)
    graph_weight: float = Field(default=1.0, ge=0.0)
    graph_hops: int = Field(default=1, ge=1, le=3)
    use_rag: bool = True
    use_graph: bool = True
    use_grounding: bool = True


class AppSettings(BaseModel):
    """Desktop / server behaviour and look & feel."""

    theme: str = Field(default="system", description="Theme id (see the UI theme list).")
    language: str = Field(default="en")
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8765, ge=1, le=65535)
    open_browser: bool = Field(default=False, description="Open a browser for `minics serve`.")
    window_width: int = Field(default=1360, ge=640)
    window_height: int = Field(default=900, ge=480)
    log_level: str = Field(default="INFO")
    max_workers: int = Field(default=4, ge=1, le=32, description="Background job workers.")
    sqlite_busy_timeout: float = Field(default=5.0, ge=0.0)
    clean_imports_with_llm: bool = Field(
        default=True, description="Run the LLM cleanup pass on imported markdown."
    )


class Config(BaseModel):
    """Root configuration document."""

    version: int = 1
    setup_complete: bool = False
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    app: AppSettings = Field(default_factory=AppSettings)

    # -- validation ------------------------------------------------------
    # -- effective endpoints --------------------------------------------
    @property
    def embedding_base_url(self) -> str:
        """Embedding URL, falling back to the LLM URL when left blank."""
        return self.embedding.base_url or self.llm.base_url

    @property
    def embedding_api_key(self) -> str:
        """Embedding key, falling back to the LLM key when left blank."""
        return self.embedding.api_key or self.llm.api_key

    def missing_requirements(self) -> list[str]:
        """Return a list of human readable requirements that are not met."""
        missing: list[str] = []
        if not self.llm.base_url:
            missing.append("LLM base URL")
        if not self.llm.model:
            missing.append("LLM model")
        if not self.embedding.model:
            missing.append("Embedding model")
        elif not self.embedding_base_url:
            missing.append("Embedding base URL")
        if self.embedding.dimension <= 0:
            missing.append("Embedding dimension")
        return missing

    def is_ready(self) -> bool:
        return not self.missing_requirements()

    # -- serialisation ---------------------------------------------------
    def public_dict(self) -> dict[str, Any]:
        """Config safe to hand to the front-end (secrets replaced)."""
        data = self.model_dump()
        for section in ("llm", "embedding"):
            key = data[section].get("api_key")
            data[section]["api_key_set"] = bool(key)
            data[section]["api_key"] = SECRET_MASK if key else ""
        data["embedding"]["effective_base_url"] = self.embedding_base_url
        data["missing_requirements"] = self.missing_requirements()
        data["ready"] = self.is_ready()
        return data


class ConfigManager:
    """Load, cache and persist :class:`Config`.

    The manager never leaves a half-written file behind: writes go to a temp
    file in the same directory, then get atomically replaced.
    """

    def __init__(self, paths: MinicsPaths | None = None) -> None:
        self.paths = paths or get_paths()
        self._config: Config | None = None

    # -- loading ---------------------------------------------------------
    @property
    def file(self) -> Path:
        return self.paths.config_file

    def load(self, *, force: bool = False) -> Config:
        if self._config is not None and not force:
            return self._config
        if self.file.exists():
            raw = json.loads(self.file.read_text(encoding="utf-8") or "{}")
            self._config = Config.model_validate(raw)
        else:
            self._config = Config()
        return self._config

    # -- saving ----------------------------------------------------------
    def save(self, config: Config | None = None) -> Config:
        config = config or self.load()
        self.paths.ensure()
        payload = config.model_dump()
        self._atomic_write(self.file, json.dumps(payload, indent=2, ensure_ascii=False))
        self._config = config
        return config

    def update(self, patch: dict[str, Any], *, apply: bool = True) -> Config:
        """Deep-merge ``patch`` into the current config and persist it.

        A ``api_key`` value equal to :data:`SECRET_MASK` means "unchanged", which
        lets the UI submit the whole settings form without ever seeing the key.
        """
        current = self.load().model_dump()
        merged = _deep_merge(current, patch)
        for section in ("llm", "embedding"):
            if merged.get(section, {}).get("api_key") == SECRET_MASK:
                merged[section]["api_key"] = current.get(section, {}).get("api_key", "")
        config = Config.model_validate(merged)
        if apply:
            self.save(config)
        else:
            self._config = config
        return config

    def mark_setup_complete(self) -> Config:
        config = self.load()
        config.setup_complete = config.is_ready()
        return self.save(config)

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _atomic_write(target: Path, text: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):  # pragma: no cover - best effort cleanup
                os.unlink(tmp)


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


_default_manager: ConfigManager | None = None


def get_config_manager(paths: MinicsPaths | None = None) -> ConfigManager:
    global _default_manager
    if paths is None and _default_manager is not None:
        return _default_manager
    manager = ConfigManager(paths)
    if paths is None:
        _default_manager = manager
    return manager


def get_config() -> Config:
    return get_config_manager().load()
