"""LLM-powered authoring helpers.

Every helper returns a validated pydantic object (see
:mod:`minics.llm.structured`) so the service layer can persist results directly.

Available helpers:

======================  ====================================================
:func:`enhance_field`   Rewrite a single ChatML field.
:func:`suggest_tags`    Propose reusable tags for an entry.
:func:`evaluate`        Score an entry globally with per-dimension detail.
:func:`generate_entry`  Draft a brand new entry from a topic (+ grounding).
:func:`clean_markdown`  Repair document text into clean Markdown.
:func:`extract_entities`  LLM entity extraction for the graph.
======================  ====================================================
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from minics.core.config import Config
from minics.llm.prompts import (
    ENTITY_SYSTEM,
    EVALUATION_SYSTEM,
    FIELD_ENHANCE_SYSTEM,
    GENERATE_ENTRY_SYSTEM,
    MARKDOWN_CLEAN_SYSTEM,
    TAG_SYSTEM,
    entry_as_text,
)
from minics.llm.structured import (
    OutputTruncatedError,
    invoke_structured,
    invoke_text,
)

#: Output token budget for helpers that echo (most of) the input back.
CLEAN_MAX_TOKENS = 8192
#: Output token budget for entity extraction (small, but reasoning models vary).
ENTITY_MAX_TOKENS = 4096


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class FieldEnhancement(BaseModel):
    """Result of improving one field."""

    improved: str = Field(description="The rewritten field content.")
    rationale: str = Field(default="", description="One sentence explaining the change.")
    changes: list[str] = Field(default_factory=list, description="Short bullet points.")


class TagSuggestions(BaseModel):
    tags: list[str] = Field(default_factory=list, description="Suggested tags.")
    rationale: str = Field(default="", description="One sentence explaining the tags.")


class EvaluationResult(BaseModel):
    """Structured global evaluation of an entry."""

    score: float = Field(description="Overall quality score between 0 and 1.")
    dimensions: dict[str, float] = Field(
        default_factory=dict, description="Per-dimension scores between 0 and 1."
    )
    summary: str = Field(default="", description="Two sentence verdict.")
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class GeneratedEntry(BaseModel):
    """A freshly generated ChatML entry."""

    system: str = Field(default="", description="System prompt, may be empty.")
    user: str = Field(description="The user request.")
    assistant: str = Field(description="The assistant response.")
    tags: list[str] = Field(default_factory=list)


class MarkdownCleanup(BaseModel):
    """Cleaned markdown plus a changelog."""

    markdown: str = Field(description="The repaired Markdown.")
    fixes: list[str] = Field(default_factory=list, description="What was repaired.")


class ExtractedEntity(BaseModel):
    name: str
    kind: str = "other"
    salience: float = Field(default=0.5, description="Importance between 0 and 1.")


class EntityExtraction(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------
def enhance_field(
    role: str,
    content: str,
    *,
    system: str = "",
    user: str = "",
    assistant: str = "",
    instruction: str = "",
    config: Config | None = None,
    model: str | None = None,
    temperature: float = 0.4,
) -> FieldEnhancement:
    """Improve ``content`` for the given ``role`` given the rest of the entry."""
    context = entry_as_text(system=system, user=user, assistant=assistant)
    prompt = [
        f"Field to improve: **{role}**",
        f"Current content:\n<{role}>\n{content.strip()}\n</{role}>",
    ]
    if context:
        prompt.append(f"Rest of the entry (for context):\n{context}")
    if instruction:
        prompt.append(f"Extra instruction from the user: {instruction}")
    prompt.append("Return the improved field.")
    return invoke_structured(
        FieldEnhancement,
        system=FIELD_ENHANCE_SYSTEM,
        user="\n\n".join(prompt),
        config=config,
        model=model,
        temperature=temperature,
    )


def suggest_tags(
    *,
    system: str = "",
    user: str = "",
    assistant: str = "",
    existing_tags: list[str] | None = None,
    max_tags: int = 6,
    config: Config | None = None,
    model: str | None = None,
) -> TagSuggestions:
    """Suggest up to ``max_tags`` reusable tags."""
    existing = list(existing_tags or [])
    prompt = [
        f"Entry:\n{entry_as_text(system=system, user=user, assistant=assistant)}",
        f"Existing tags to avoid: {', '.join(existing) if existing else '(none)'}",
        f"Suggest at most {max_tags} tags.",
    ]
    return invoke_structured(
        TagSuggestions,
        system=TAG_SYSTEM,
        user="\n\n".join(prompt),
        config=config,
        model=model,
        temperature=0.3,
    )


def evaluate(
    *,
    system: str = "",
    user: str = "",
    assistant: str = "",
    context: str = "",
    config: Config | None = None,
    model: str | None = None,
) -> EvaluationResult:
    """Score an entry globally."""
    prompt = [f"Entry:\n{entry_as_text(system=system, user=user, assistant=assistant)}"]
    if context:
        prompt.append(f"Optional reference material:\n{context[:4000]}")
    result = invoke_structured(
        EvaluationResult,
        system=EVALUATION_SYSTEM,
        user="\n\n".join(prompt),
        config=config,
        model=model,
        temperature=0.0,
    )
    result.score = max(0.0, min(1.0, float(result.score)))
    result.dimensions = {
        key: max(0.0, min(1.0, float(value))) for key, value in result.dimensions.items()
    }
    return result


def generate_entry(
    topic: str,
    *,
    grounding: str = "",
    system_hint: str = "",
    count: int = 1,
    config: Config | None = None,
    model: str | None = None,
) -> GeneratedEntry:
    """Draft a new entry about ``topic``, optionally grounded in material."""
    prompt = [f"Topic: {topic}"]
    if system_hint:
        prompt.append(f"System prompt guidance: {system_hint}")
    if grounding:
        prompt.append(
            "Ground every factual claim in this material and do not contradict it:\n"
            f"{grounding[:6000]}"
        )
    if count > 1:
        prompt.append(f"Produce the single best of {count} candidate entries.")
    return invoke_structured(
        GeneratedEntry,
        system=GENERATE_ENTRY_SYSTEM,
        user="\n\n".join(prompt),
        config=config,
        model=model,
        temperature=0.8,
    )


# ---------------------------------------------------------------------------
# Markdown cleanup
# ---------------------------------------------------------------------------
def _segments(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    segments: list[str] = []
    current: list[str] = []
    length = 0
    for paragraph in text.split("\n\n"):
        block = paragraph + "\n\n"
        if length + len(block) > size and current:
            segments.append("".join(current).rstrip())
            current, length = [], 0
        current.append(block)
        length += len(block)
    if current:
        segments.append("".join(current).rstrip())
    return segments


def clean_markdown(
    markdown: str,
    *,
    title: str = "",
    config: Config | None = None,
    model: str | None = None,
    max_chars: int = 16000,
    max_tokens: int = CLEAN_MAX_TOKENS,
) -> str:
    """Repair extracted document text into clean Markdown using the LLM.

    Cleaning echoes the whole document back, so it needs a large output budget.
    If a segment is still truncated, it is split further and retried.
    """
    text = (markdown or "").strip()
    if not text:
        return ""
    if len(text) > max_chars:
        cleaned = [
            clean_markdown(
                segment,
                title=title,
                config=config,
                model=model,
                max_chars=max_chars,
                max_tokens=max_tokens,
            )
            for segment in _segments(text, max_chars)
        ]
        return "\n\n".join(part.strip() for part in cleaned if part)

    prompt = [
        f"Document title: {title or '(untitled)'}",
        f"Extracted text:\n---\n{text}\n---",
        "Return the cleaned Markdown.",
    ]
    try:
        result = invoke_structured(
            MarkdownCleanup,
            system=MARKDOWN_CLEAN_SYSTEM,
            user="\n\n".join(prompt),
            config=config,
            model=model,
            temperature=0.0,
            max_tokens=max_tokens,
        )
    except OutputTruncatedError:
        parts = _segments(text, max(len(text) // 2, 1000))
        if len(parts) <= 1:
            raise
        cleaned = [
            clean_markdown(
                part,
                title=title,
                config=config,
                model=model,
                max_chars=max_chars,
                max_tokens=max_tokens,
            )
            for part in parts
        ]
        return "\n\n".join(part.strip() for part in cleaned if part)
    return (result.markdown or text).strip() + "\n"


def extract_entities(
    text: str,
    *,
    max_entities: int = 12,
    config: Config | None = None,
    model: str | None = None,
    max_tokens: int = ENTITY_MAX_TOKENS,
) -> list[ExtractedEntity]:
    """LLM entity extraction for graph enrichment."""
    prompt = [
        f"Passage:\n---\n{text[:6000]}\n---",
        f"Extract at most {max_entities} entities.",
    ]
    result = invoke_structured(
        EntityExtraction,
        system=ENTITY_SYSTEM,
        user="\n\n".join(prompt),
        config=config,
        model=model,
        temperature=0.0,
        max_tokens=max_tokens,
    )
    return result.entities[:max_entities]


# ---------------------------------------------------------------------------
# Convenience: entry-level operations
# ---------------------------------------------------------------------------
def enhance_entry(
    entry: Any,
    *,
    fields: list[str] | None = None,
    instruction: str = "",
    config: Config | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Enhance several fields of an :class:`~minics.domain.entities.Entry`."""
    fields = fields or ["assistant"]
    context = {
        "system": entry.system,
        "user": entry.user,
        "assistant": entry.assistant,
    }
    output: dict[str, Any] = {}
    for role in fields:
        current = context.get(role, "")
        if not current.strip():
            continue
        others = {key: value for key, value in context.items() if key != role}
        result = enhance_field(
            role,
            current,
            instruction=instruction,
            config=config,
            model=model,
            **others,
        )
        output[role] = result.model_dump()
    return output


def summarize_text(
    text: str, *, instruction: str = "", config: Config | None = None, model: str | None = None
) -> str:
    """Generic text helper used by the chat UI."""
    return invoke_text(
        system="You are a precise assistant. Answer using only the provided material when present.",
        user=f"{instruction}\n\n{text}".strip(),
        config=config,
        model=model,
    )
