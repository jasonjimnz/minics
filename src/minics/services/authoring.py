"""LLM-assisted authoring: enhance, tag, evaluate, generate.

This service is the bridge between the entry library and the LLM helpers in
:mod:`minics.llm.enhance`.  It knows how to load an entry, optionally ground the
request in retrieved documents, call the model and persist the result.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from minics.domain.entities import ChatMessage, Entry, Evaluation, Role
from minics.services.base import NotFoundError, Service


class AuthoringService(Service):
    """High-level LLM operations over entries and documents."""

    name = "authoring"

    # -- entries ---------------------------------------------------------
    def enhance_entry_fields(
        self,
        ref: int | str,
        *,
        fields: Sequence[str] | None = None,
        instruction: str = "",
        use_grounding: bool = False,
        model: str | None = None,
        persist: bool = False,
    ) -> dict[str, Any]:
        from minics.llm.enhance import enhance_field

        entry = self.ctx.entries.get(ref)
        fields = list(fields or ["assistant"])
        context = {
            "system": entry.system,
            "user": entry.user,
            "assistant": entry.assistant,
        }
        grounding = self._grounding_for(entry) if use_grounding else ""

        results: dict[str, Any] = {}
        for role in fields:
            current = context.get(role, "")
            if not current.strip():
                results[role] = {
                    "improved": current,
                    "rationale": "Nothing to improve.",
                    "changes": [],
                    "skipped": True,
                }
                continue
            others = {key: value for key, value in context.items() if key != role}
            extra = (
                f"{instruction}\n\nGrounding material:\n{grounding}"
                if grounding
                else instruction
            )
            result = enhance_field(
                role, current, instruction=extra, config=self.config, model=model, **others
            )
            results[role] = result.model_dump()

        if persist:
            messages = [message.model_copy() for message in entry.messages]
            for role, data in results.items():
                if data.get("skipped") or data.get("improved") is None:
                    continue
                improved = data["improved"]
                replaced = False
                for message in messages:
                    if message.role_name == role:
                        message.content = improved
                        replaced = True
                        break
                if not replaced:
                    messages.append(ChatMessage(role=Role(role), content=improved))
            self.ctx.entries.update(
                entry.id,
                {"messages": [message.model_dump() for message in messages]},
                reason="llm enhance",
            )
        return {"entry": entry.public_id, "fields": results, "grounding": bool(grounding)}

    def suggest_tags(
        self,
        ref: int | str,
        *,
        max_tags: int = 6,
        add: bool = False,
        model: str | None = None,
    ) -> dict[str, Any]:
        from minics.llm.enhance import suggest_tags

        entry = self.ctx.entries.get(ref)
        suggestion = suggest_tags(
            system=entry.system,
            user=entry.user,
            assistant=entry.assistant,
            existing_tags=entry.tags,
            max_tags=max_tags,
            config=self.config,
            model=model,
        )
        tags = [tag.strip().lower() for tag in suggestion.tags if tag and tag.strip()]
        tags = [tag for tag in tags if tag not in entry.tags][:max_tags]
        if add and tags:
            self.ctx.entries.add_tags(entry.id, tags)
        return {
            "entry": entry.public_id,
            "tags": tags,
            "rationale": suggestion.rationale,
            "applied": bool(add),
        }

    def evaluate_entry(
        self,
        ref: int | str,
        *,
        use_grounding: bool = False,
        persist: bool = True,
        model: str | None = None,
    ) -> Evaluation:
        from minics.llm.enhance import evaluate

        entry = self.ctx.entries.get(ref)
        grounding = self._grounding_for(entry) if use_grounding else ""
        result = evaluate(
            system=entry.system,
            user=entry.user,
            assistant=entry.assistant,
            context=grounding,
            config=self.config,
            model=model,
        )
        evaluation = Evaluation(
            score=result.score,
            dimensions=result.dimensions,
            summary=result.summary,
            strengths=result.strengths,
            issues=result.issues,
            suggestions=result.suggestions,
            evaluator="llm",
            model=model or self.config.llm.model,
        )
        if persist:
            self.ctx.entries.set_evaluation(entry.id, evaluation)
            self.emit(
                "entry.evaluated",
                f"Entry '{entry.public_id}' scored {evaluation.score:.2f}",
                level="success",
                entry=entry.public_id,
                score=evaluation.score,
            )
        return evaluation

    def generate_entry(
        self,
        *,
        topic: str,
        dataset: int | str | None = None,
        system_hint: str = "",
        use_grounding: bool = True,
        persist: bool = True,
        tags: Sequence[str] | None = None,
        model: str | None = None,
    ) -> Entry | dict[str, Any]:
        from minics.llm.enhance import generate_entry

        grounding = ""
        if use_grounding:
            grounding = self.ctx.retriever.retrieve(topic).context_text(max_chars=4000)
        draft = generate_entry(
            topic,
            grounding=grounding,
            system_hint=system_hint,
            config=self.config,
            model=model,
        )
        if not persist:
            return draft.model_dump()
        entry = self.ctx.entries.create(
            dataset,
            system=draft.system,
            user=draft.user,
            assistant=draft.assistant,
            tags=list(tags or draft.tags),
            source="generated",
            metadata={"topic": topic, "grounded": bool(grounding)},
        )
        self.emit(
            "entry.generated",
            f"Generated entry '{entry.public_id}' about {topic}",
            level="success",
            entry=entry.public_id,
        )
        return entry

    # -- documents -------------------------------------------------------
    def clean_document(self, ref: int | str, *, model: str | None = None) -> dict[str, Any]:
        from minics.llm.enhance import clean_markdown

        document = self.ctx.documents.get(ref)
        current = self.ctx.documents.read_markdown(document.id)
        cleaned = clean_markdown(
            current, title=document.title, config=self.config, model=model
        )
        self.ctx.documents.write_markdown(document.id, cleaned)
        return {"document": document.public_id, "chars": len(cleaned)}

    def enrich_graph(
        self, ref: int | str, *, max_entities: int = 12, model: str | None = None
    ) -> dict[str, Any]:
        """Add LLM-extracted, higher quality entities to the graph."""
        from minics.llm.enhance import extract_entities

        document = self.ctx.documents.get(ref)
        markdown = self.ctx.documents.read_markdown(document.id)
        store = self.ctx.graph
        if not store.is_available():
            raise NotFoundError("Graph store is not available.")
        from minics.rag.chunking import split_markdown
        from minics.rag.entities import Entity
        from minics.rag.indexer import vector_id_for

        settings = self.config.embedding
        chunks = split_markdown(
            markdown, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
        )
        added = 0
        for chunk in chunks:
            entities = extract_entities(
                chunk.text, max_entities=max_entities, config=self.config, model=model
            )
            chunk_id = vector_id_for(int(document.id), chunk.index)
            for item in entities:
                if not item.name.strip():
                    continue
                store.add_mention(
                    chunk_id,
                    Entity(
                        name=item.name.strip(),
                        kind=item.kind or "other",
                        weight=max(0.1, float(item.salience)),
                    ),
                )
                added += 1
        self.emit(
            "graph.enriched",
            f"LLM added {added} entity mentions for '{document.title}'",
            level="success",
        )
        return {"document": document.public_id, "entities": added}

    # -- internals -------------------------------------------------------
    def _grounding_for(self, entry: Entry, *, max_chars: int = 4000) -> str:
        query = " ".join(part for part in (entry.system, entry.user) if part).strip()
        if not query:
            return ""
        try:
            result = self.ctx.retriever.retrieve(query, top_k=6)
        except Exception as exc:  # noqa: BLE001 - grounding is optional
            self.emit("grounding.failed", str(exc), level="warning")
            return ""
        return result.context_text(max_chars=max_chars)
