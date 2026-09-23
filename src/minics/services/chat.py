"""Chat with the LLM, with per-conversation RAG / graph / grounding control.

A conversation is a persisted transcript with three independent switches:

``use_rag``        include semantically similar passages
``use_graph``      include passages selected through the entity graph
``use_grounding``  actually inject the retrieved material into the prompt

Retrieval and grounding are separate so the user can *see* what would be used
without forcing it into the answer.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from minics.domain.entities import Citation, Conversation, ConversationMessage, Role
from minics.llm.client import build_chat_model
from minics.rag.retriever import RetrievalResult
from minics.services.base import NotFoundError, Service
from minics.services.repositories import (
    ConversationMessageRepository,
    ConversationRepository,
)

GROUNDING_TEMPLATE = """Use the reference material below to answer.

- Cite sources inline as [n] matching the numbered references.
- If the material does not contain the answer, say so and answer from general knowledge.
- Never contradict the reference material.

References:
{context}
"""


class ChatService(Service):
    """Conversations with optional retrieval grounding."""

    name = "chat"

    def __init__(self, ctx) -> None:  # noqa: D401 - simple
        super().__init__(ctx)
        self.conversations = ConversationRepository(ctx.db)
        self.messages = ConversationMessageRepository(ctx.db)

    # -- conversation CRUD ----------------------------------------------
    def list(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        output = []
        for conversation in self.conversations.list(limit=limit):
            count = self.messages.count(
                where="conversation_id = ?", params=(conversation.id,)
            )
            output.append({"conversation": conversation, "message_count": count})
        return output

    def get(self, ref: int | str) -> Conversation:
        conversation = self.conversations.get(self.resolve_id(self.conversations, ref))
        if conversation is None:
            raise NotFoundError(f"Conversation '{ref}' not found")
        return conversation

    def create(
        self,
        title: str = "New conversation",
        *,
        system_prompt: str = "",
        use_rag: bool | None = None,
        use_graph: bool | None = None,
        use_grounding: bool | None = None,
        dataset: int | str | None = None,
    ) -> Conversation:
        settings = self.config.retrieval
        dataset_id = None
        if dataset is not None:
            dataset_id = self.resolve_id(self.ctx.datasets.repo, dataset)
        conversation = Conversation(
            title=title or "New conversation",
            system_prompt=system_prompt,
            use_rag=settings.use_rag if use_rag is None else use_rag,
            use_graph=settings.use_graph if use_graph is None else use_graph,
            use_grounding=settings.use_grounding if use_grounding is None else use_grounding,
            dataset_id=dataset_id,
        )
        self.conversations.insert(conversation)
        self.emit("chat.created", f"Conversation '{conversation.title}' created")
        return conversation

    def update(self, ref: int | str, patch: dict[str, Any]) -> Conversation:
        conversation = self.get(ref)
        for field in ("title", "system_prompt", "use_rag", "use_graph", "use_grounding"):
            if field in patch and patch[field] is not None:
                setattr(conversation, field, patch[field])
        self.conversations.update(conversation)
        return conversation

    def delete(self, ref: int | str) -> bool:
        conversation = self.get(ref)
        deleted = self.conversations.delete(int(conversation.id))
        if deleted:
            self.emit("chat.deleted", f"Conversation '{conversation.title}' deleted")
        return deleted

    def history(self, ref: int | str) -> list[ConversationMessage]:
        return self.messages.list_for_conversation(self.resolve_id(self.conversations, ref))

    def append(
        self,
        ref: int | str,
        role: Role | str,
        content: str,
        *,
        citations: Sequence[Citation] | None = None,
        model: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        conversation_id = self.resolve_id(self.conversations, ref)
        message = ConversationMessage(
            conversation_id=conversation_id,
            index=self.messages.next_index(conversation_id),
            role=Role(role),
            content=content,
            citations=list(citations or []),
            model=model,
            usage=dict(usage or {}),
        )
        self.messages.insert(message)
        return message

    # -- sending ---------------------------------------------------------
    def retrieve(
        self,
        ref: int | str,
        query: str,
        *,
        use_rag: bool | None = None,
        use_graph: bool | None = None,
        top_k: int | None = None,
    ) -> RetrievalResult:
        conversation = self.get(ref)
        return self.ctx.retriever.retrieve(
            query,
            top_k=top_k,
            use_rag=conversation.use_rag if use_rag is None else use_rag,
            use_graph=conversation.use_graph if use_graph is None else use_graph,
        )

    def send(
        self,
        ref: int | str,
        content: str,
        *,
        use_rag: bool | None = None,
        use_graph: bool | None = None,
        use_grounding: bool | None = None,
        persist: bool = True,
        model: str | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Non-streaming send; returns the assistant message and retrieval info."""
        conversation = self.get(ref)
        retrieval = self._maybe_retrieve(conversation, content, use_rag, use_graph)
        grounding = conversation.use_grounding if use_grounding is None else use_grounding

        if persist:
            self.append(conversation.id, Role.USER, content)

        messages = self._build_prompt(conversation, content, retrieval, grounding)
        chat = build_chat_model(
            self.config, model=model, temperature=temperature
        )
        response = chat.invoke(messages)
        text = _content_to_text(getattr(response, "content", ""))
        usage = _usage_dict(response)
        citations = retrieval.citations() if (grounding and retrieval.chunks) else []

        if persist:
            assistant = self.append(
                conversation.id,
                Role.ASSISTANT,
                text,
                citations=citations,
                model=model or self.config.llm.model,
                usage=usage,
            )
            self._maybe_autotitle(conversation, content)
        else:
            assistant = None

        return {
            "conversation": conversation.public_id,
            "content": text,
            "citations": [c.model_dump() for c in citations],
            "usage": usage,
            "retrieval": retrieval.to_dict(),
            "message": assistant.to_dict() if assistant else None,
        }

    def stream(
        self,
        ref: int | str,
        content: str,
        *,
        use_rag: bool | None = None,
        use_graph: bool | None = None,
        use_grounding: bool | None = None,
        persist: bool = True,
        model: str | None = None,
        temperature: float | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield ``{"type": ...}`` events suitable for SSE."""
        conversation = self.get(ref)
        retrieval = self._maybe_retrieve(conversation, content, use_rag, use_graph)
        grounding = conversation.use_grounding if use_grounding is None else use_grounding
        citations = retrieval.citations() if (grounding and retrieval.chunks) else []

        if persist:
            self.append(conversation.id, Role.USER, content)

        yield {
            "type": "retrieval",
            "retrieval": retrieval.to_dict(),
            "grounding": bool(grounding and retrieval.chunks),
        }

        messages = self._build_prompt(conversation, content, retrieval, grounding)
        chat = build_chat_model(self.config, model=model, temperature=temperature)
        collected: list[str] = []
        usage: dict[str, Any] = {}
        try:
            for chunk in chat.stream(messages):
                piece = _content_to_text(getattr(chunk, "content", ""))
                if piece:
                    collected.append(piece)
                    yield {"type": "token", "text": piece}
                chunk_usage = _usage_dict(chunk)
                if chunk_usage:
                    usage.update(chunk_usage)
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            yield {"type": "error", "error": f"{type(exc).__name__}: {exc}"}
            return

        text = "".join(collected)
        message = None
        if persist:
            appended = self.append(
                conversation.id,
                Role.ASSISTANT,
                text,
                citations=citations,
                model=model or self.config.llm.model,
                usage=usage,
            )
            self._maybe_autotitle(conversation, content)
            message = appended.to_dict()
        yield {
            "type": "done",
            "content": text,
            "citations": [c.model_dump() for c in citations],
            "usage": usage,
            "message": message,
        }

    # -- internals -------------------------------------------------------
    def _maybe_retrieve(
        self,
        conversation: Conversation,
        content: str,
        use_rag: bool | None,
        use_graph: bool | None,
    ) -> RetrievalResult:
        rag = conversation.use_rag if use_rag is None else use_rag
        graph = conversation.use_graph if use_graph is None else use_graph
        if not (rag or graph):
            return RetrievalResult(query=content, used_rag=False, used_graph=False)
        try:
            return self.ctx.retriever.retrieve(content, use_rag=rag, use_graph=graph)
        except Exception as exc:  # noqa: BLE001 - chat must still work
            self.emit("chat.retrieval_failed", str(exc), level="warning")
            return RetrievalResult(query=content, used_rag=rag, used_graph=graph)

    def _build_prompt(
        self,
        conversation: Conversation,
        content: str,
        retrieval: RetrievalResult,
        grounding: bool,
    ) -> list[Any]:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        messages: list[Any] = []
        system_parts: list[str] = []
        if conversation.system_prompt:
            system_parts.append(conversation.system_prompt.strip())
        if grounding and retrieval.chunks:
            context = retrieval.context_text(max_chars=8000)
            system_parts.append(GROUNDING_TEMPLATE.format(context=context))
        if system_parts:
            messages.append(SystemMessage(content="\n\n".join(system_parts)))

        for item in self.history(conversation.id)[-16:]:
            role = item.role.value if hasattr(item.role, "value") else str(item.role)
            if role == Role.USER.value:
                messages.append(HumanMessage(content=item.content))
            elif role == Role.ASSISTANT.value:
                messages.append(AIMessage(content=item.content))
        messages.append(HumanMessage(content=content))
        return messages

    def _maybe_autotitle(self, conversation: Conversation, first_user_message: str) -> None:
        if conversation.title not in ("", "New conversation"):
            return
        title = first_user_message.strip().splitlines()[0][:60] or "New conversation"
        conversation.title = title
        self.conversations.update(conversation)


def _content_to_text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content or "")


def _usage_dict(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict) and usage:
        return dict(usage)
    metadata = getattr(response, "response_metadata", None)
    if isinstance(metadata, dict) and metadata.get("token_usage"):
        return dict(metadata["token_usage"])
    return {}
