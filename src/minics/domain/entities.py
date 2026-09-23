"""Domain entities.

These pydantic models are the vocabulary of MiniCS.  They are deliberately
storage-agnostic: the SQLite layer serialises them to rows, while the API layer
serialises them to JSON, and both use the same objects.

The ChatML entry format is represented faithfully: an entry is an ordered list
of :class:`ChatMessage` (``role`` + ``content``, optional ``name``).
"""

from __future__ import annotations

import enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from minics.core.utils import new_id, slugify, utcnow_iso


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class Role(str, enum.Enum):
    """ChatML roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    DEVELOPER = "developer"


class EntryStatus(str, enum.Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    CONVERTING = "converting"
    INDEXING = "indexing"
    READY = "ready"
    ERROR = "error"


class SourceKind(str, enum.Enum):
    MANUAL = "manual"
    IMPORT = "import"
    GENERATED = "generated"
    SYNTHETIC = "synthetic"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
def _timestamp() -> str:
    return utcnow_iso()


class Entity(BaseModel):
    """Common fields for every persisted entity."""

    model_config = {"populate_by_name": True}

    id: int | None = None
    public_id: str = Field(default_factory=new_id)
    created_at: str = Field(default_factory=_timestamp)
    updated_at: str = Field(default_factory=_timestamp)

    def touch(self) -> None:
        self.updated_at = _timestamp()

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready representation (enums, nested models flattened)."""
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    """A single ChatML message."""

    role: Role
    content: str = ""
    name: str | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

    @property
    def role_name(self) -> str:
        return self.role.value if isinstance(self.role, Role) else str(self.role)

    def is_empty(self) -> bool:
        return not self.content.strip()


class Evaluation(BaseModel):
    """Global, LLM- or human-produced assessment of an entry."""

    score: float = Field(default=0.0, ge=0.0, le=1.0)
    dimensions: dict[str, float] = Field(default_factory=dict)
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    evaluator: Literal["llm", "human"] = "llm"
    model: str | None = None


class Entry(Entity):
    """A ChatML training sample."""

    dataset_id: int | None = None
    status: EntryStatus = EntryStatus.DRAFT
    messages: list[ChatMessage] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    quality: float | None = None
    evaluation: Evaluation | None = None
    source: SourceKind = SourceKind.MANUAL
    metadata: dict[str, Any] = Field(default_factory=dict)
    position: int = 0
    version: int = 1

    # -- ChatML helpers --------------------------------------------------
    def first(self, role: Role) -> ChatMessage | None:
        for message in self.messages:
            if message.role_name == role.value:
                return message
        return None

    @property
    def system(self) -> str:
        message = self.first(Role.SYSTEM)
        return message.content if message else ""

    @property
    def user(self) -> str:
        message = self.first(Role.USER)
        return message.content if message else ""

    @property
    def assistant(self) -> str:
        message = self.first(Role.ASSISTANT)
        return message.content if message else ""

    def validate_chatml(self) -> list[str]:
        """Return a list of structural problems (empty list means valid)."""
        problems: list[str] = []
        if not self.messages:
            problems.append("Entry has no messages.")
            return problems
        roles = [m.role_name for m in self.messages]
        if Role.USER.value not in roles:
            problems.append("Entry has no user message.")
        if Role.ASSISTANT.value not in roles:
            problems.append("Entry has no assistant message.")
        if roles.count(Role.SYSTEM.value) > 1:
            problems.append("Entry has more than one system message.")
        if roles[0] == Role.ASSISTANT.value:
            problems.append("Entry starts with an assistant message.")
        for index, message in enumerate(self.messages):
            if message.is_empty() and message.role_name in (Role.USER.value, Role.ASSISTANT.value):
                problems.append(f"Message #{index + 1} ({message.role_name}) is empty.")
        return problems

    def to_chatml(self) -> dict[str, Any]:
        return {"messages": [m.model_dump(exclude_none=True) for m in self.messages]}


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
class Dataset(Entity):
    name: str
    slug: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    source: SourceKind = SourceKind.MANUAL
    metadata: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ensure_slug(self) -> Dataset:
        if not self.slug:
            self.slug = slugify(self.name, fallback="dataset")
        return self


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
class Collection(Entity):
    """A curated, exportable selection of entries (optionally dataset-scoped)."""

    name: str
    slug: str = ""
    description: str = ""
    dataset_id: int | None = None
    tags: list[str] = Field(default_factory=list)
    entry_ids: list[int] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ensure_slug(self) -> Collection:
        if not self.slug:
            self.slug = slugify(self.name, fallback="collection")
        return self


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class Document(Entity):
    title: str
    source: str = ""
    kind: str = ""
    original_path: str = ""
    markdown_path: str = ""
    size_bytes: int = 0
    sha256: str = ""
    status: DocumentStatus = DocumentStatus.PENDING
    error: str = ""
    chunk_count: int = 0
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentChunk(Entity):
    document_id: int
    index: int = 0
    text: str = ""
    tokens: int = 0
    heading: str = ""
    vector_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
class Citation(BaseModel):
    kind: Literal["vector", "graph", "document"] = "vector"
    ref: str = ""
    title: str = ""
    snippet: str = ""
    score: float = 0.0
    document_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Conversation(Entity):
    title: str = "New conversation"
    system_prompt: str = ""
    use_rag: bool = True
    use_graph: bool = True
    use_grounding: bool = True
    dataset_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationMessage(Entity):
    conversation_id: int
    index: int = 0
    role: Role = Role.USER
    content: str = ""
    citations: list[Citation] = Field(default_factory=list)
    model: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------
class ExportRequest(BaseModel):
    format: Literal["chatml", "jsonl", "alpaca", "sharegpt", "markdown"] = "chatml"
    include_metadata: bool = False
    statuses: list[EntryStatus] = Field(default_factory=list)
