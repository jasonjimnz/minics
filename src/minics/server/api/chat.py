"""Chat endpoints (streaming and non-streaming)."""

from __future__ import annotations

from flask import Blueprint

from minics.server.deps import get_ctx, json_body, ok
from minics.server.sse import sse_response

bp = Blueprint("chat", __name__, url_prefix="/api/chat/conversations")


def _payload(ctx, conversation) -> dict:
    data = conversation.to_dict()
    data["messages"] = [m.to_dict() for m in ctx.chat.history(conversation.id)]
    return data


@bp.get("")
@bp.get("/")
def list_conversations():
    ctx = get_ctx()
    items = [
        {"conversation": item["conversation"].to_dict(), "message_count": item["message_count"]}
        for item in ctx.chat.list()
    ]
    return ok({"items": items, "total": len(items)})


@bp.post("")
@bp.post("/")
def create_conversation():
    ctx = get_ctx()
    body = json_body()
    conversation = ctx.chat.create(
        body.get("title", "New conversation"),
        system_prompt=body.get("system_prompt", ""),
        use_rag=body.get("use_rag"),
        use_graph=body.get("use_graph"),
        use_grounding=body.get("use_grounding"),
        dataset=body.get("dataset"),
    )
    return ok(_payload(ctx, conversation)), 201


@bp.get("/<ref>")
def get_conversation(ref: str):
    ctx = get_ctx()
    return ok(_payload(ctx, ctx.chat.get(ref)))


@bp.patch("/<ref>")
def update_conversation(ref: str):
    ctx = get_ctx()
    conversation = ctx.chat.update(ref, json_body())
    return ok(_payload(ctx, conversation))


@bp.delete("/<ref>")
def delete_conversation(ref: str):
    ctx = get_ctx()
    return ok({"deleted": ctx.chat.delete(ref)})


@bp.get("/<ref>/messages")
def list_messages(ref: str):
    ctx = get_ctx()
    return ok({"items": [m.to_dict() for m in ctx.chat.history(ref)]})


@bp.post("/<ref>/messages")
def send_message(ref: str):
    ctx = get_ctx()
    body = json_body()
    result = ctx.chat.send(
        ref,
        body.get("content", ""),
        use_rag=body.get("use_rag"),
        use_graph=body.get("use_graph"),
        use_grounding=body.get("use_grounding"),
        model=body.get("model"),
        temperature=body.get("temperature"),
    )
    return ok(result)


@bp.delete("/<ref>/messages")
def clear_messages(ref: str):
    ctx = get_ctx()
    conversation = ctx.chat.get(ref)
    ctx.db.update(
        "DELETE FROM conversation_messages WHERE conversation_id = ?", (int(conversation.id),)
    )
    return ok({"cleared": True})


@bp.post("/<ref>/stream")
def stream_message(ref: str):
    ctx = get_ctx()
    body = json_body()
    events = ctx.chat.stream(
        ref,
        body.get("content", ""),
        use_rag=body.get("use_rag"),
        use_graph=body.get("use_graph"),
        use_grounding=body.get("use_grounding"),
        model=body.get("model"),
        temperature=body.get("temperature"),
    )
    return sse_response(events)


@bp.post("/<ref>/retrieve")
def retrieve(ref: str):
    ctx = get_ctx()
    body = json_body()
    result = ctx.chat.retrieve(
        ref,
        body.get("query", ""),
        use_rag=body.get("use_rag"),
        use_graph=body.get("use_graph"),
        top_k=body.get("top_k"),
    )
    return ok(result.to_dict())


@bp.get("/<ref>/citations")
def citations(ref: str):
    ctx = get_ctx()
    messages = ctx.chat.history(ref)
    items = []
    for message in messages:
        for citation in message.citations:
            items.append(citation.model_dump())
    return ok({"items": items})


