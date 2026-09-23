"""Structured LLM calls via LangChain.

Different OpenAI-compatible servers support different structured-output
mechanisms (native JSON schema / tool calling / plain prompting).  Rather than
guessing, :func:`invoke_structured` tries the strongest method first and falls
back gracefully, so the same code works against OpenAI, vLLM, llama.cpp, LM
Studio and Ollama.

The result is always a validated pydantic object — callers never parse JSON.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from minics.core.config import Config, get_config
from minics.llm.client import LLMError, build_chat_model

M = TypeVar("M", bound=BaseModel)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class StructuredOutputError(LLMError):
    """Raised when no structured-output strategy produced a valid object."""


class OutputTruncatedError(StructuredOutputError):
    """Raised when the model hit its output token limit mid-response."""


def _is_truncation(exc: BaseException) -> bool:
    """Detect the "finish_reason=length" errors servers surface on truncation."""
    text = str(exc).lower()
    return (
        "length limit" in text
        or "finish_reason='length'" in text
        or 'finish_reason="length"' in text
    )


def _finish_reason(response: Any) -> str:
    metadata = getattr(response, "response_metadata", None)
    if isinstance(metadata, dict) and metadata.get("finish_reason"):
        return str(metadata["finish_reason"])
    for generation in getattr(response, "generations", None) or []:
        info = getattr(generation, "generation_info", None)
        if isinstance(info, dict) and info.get("finish_reason"):
            return str(info["finish_reason"])
    return ""


def _truncation_error(limit: int, strategy: str) -> OutputTruncatedError:
    return OutputTruncatedError(
        f"The model hit its output token limit (max_tokens={limit}) during the "
        f"'{strategy}' step, so the structured response was cut off. "
        "Increase llm.max_tokens or reduce the input size."
    )


def _extract_json(text: str) -> str | None:
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    match = _JSON_BLOCK.search(text)
    return match.group(0) if match else None


def _schema_hint(schema: type[BaseModel]) -> str:
    lines = ["Respond with a single JSON object with these fields:"]
    for name, field in schema.model_fields.items():
        description = field.description or ""
        lines.append(f'- "{name}": {description}'.rstrip(": "))
    return "\n".join(lines)


def invoke_structured(
    schema: type[M],
    *,
    system: str,
    user: str,
    config: Config | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> M:
    """Call the configured chat model and return a validated ``schema`` instance."""
    from langchain_core.messages import HumanMessage, SystemMessage

    chat = build_chat_model(
        config,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    errors: list[str] = []
    limit = (
        max_tokens
        if max_tokens is not None
        else (config or get_config()).llm.max_tokens
    )

    # 1) Native structured output (tool / json_schema depending on server).
    try:
        return chat.with_structured_output(schema).invoke(messages)
    except Exception as exc:  # noqa: BLE001 - try the next strategy
        if _is_truncation(exc):
            raise _truncation_error(limit, "structured") from exc
        errors.append(f"structured: {exc}")

    # 2) JSON mode.
    try:
        structured = chat.with_structured_output(schema, method="json_mode")
        return structured.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=f"{user}\n\n{_schema_hint(schema)}"),
            ]
        )
    except Exception as exc:  # noqa: BLE001 - try the next strategy
        if _is_truncation(exc):
            raise _truncation_error(limit, "json_mode") from exc
        errors.append(f"json_mode: {exc}")

    # 3) Prompt for JSON and parse it ourselves.
    try:
        response = chat.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=f"{user}\n\n{_schema_hint(schema)}"),
            ]
        )
        if _finish_reason(response) == "length":
            raise _truncation_error(limit, "text")
        content = getattr(response, "content", "") or ""
        block = _extract_json(str(content))
        if block is None:
            raise ValueError("no JSON object found in the response")
        return schema.model_validate(json.loads(block))
    except OutputTruncatedError:
        raise
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"text: {exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"text: {exc}")

    raise StructuredOutputError(
        "The model could not produce a valid structured response. "
        + " | ".join(errors)
    )


def invoke_text(
    *,
    system: str,
    user: str,
    config: Config | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Plain text completion through the same OpenAI-compatible path."""
    from langchain_core.messages import HumanMessage, SystemMessage

    chat = build_chat_model(
        config, model=model, temperature=temperature, max_tokens=max_tokens
    )
    response = chat.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    content = getattr(response, "content", "")
    if isinstance(content, list):  # some servers return content blocks
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content).strip()


def model_info(config: Config | None = None) -> dict[str, Any]:
    """Small diagnostic helper used by the UI."""
    from minics.core.config import get_config

    cfg = config or get_config()
    return {
        "model": cfg.llm.model,
        "base_url": cfg.llm.base_url,
        "temperature": cfg.llm.temperature,
        "max_tokens": cfg.llm.max_tokens,
    }
