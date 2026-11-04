"""Pydantic schemas for the OpenAI-compatible proxy.

Only the fields the proxy actually needs are modelled; everything else is
tolerated (extra fields) so real OpenAI clients keep working unchanged.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MinicsOptions(BaseModel):
    """Per-request MiniCS grounding options (top-level ``minics`` body field)."""

    model_config = ConfigDict(extra="forbid")

    use_rag: bool = True
    use_graph: bool = True
    use_grounding: bool = True
    top_k: int | None = Field(default=None, ge=1, le=100)
    document_ids: list[int] | None = None
    max_context_chars: int = Field(default=8000, ge=200, le=200_000)


class ChatMessage(BaseModel):
    """OpenAI chat message (content kept permissive for multimodal parts)."""

    model_config = ConfigDict(extra="allow")

    role: str
    content: Any = None
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    """Subset of the OpenAI chat completion request the proxy understands."""

    model_config = ConfigDict(extra="allow")

    model: str | None = None
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: str | list[str] | None = None
    user: str | None = None
    #: MiniCS extension — grounding/retrieval options for this request.
    minics: MinicsOptions | None = None


class ModelObject(BaseModel):
    id: str
    object: Literal["model"] = "model"  # type: ignore[assignment]
    created: int = 0
    owned_by: str = "minics"


class ModelListResponse(BaseModel):
    object: Literal["list"] = "list"  # type: ignore[assignment]
    data: list[ModelObject]
