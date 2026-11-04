"""OpenAI-compatible proxy server.

The proxy exposes ``/v1/chat/completions`` (plus ``/v1/models`` and
``/health``) backed by the MiniCS configuration: every incoming request is
first answered by the hybrid retriever, the retrieved context is injected
into the prompt as grounding, and the enhanced prompt is sent to the
configured LLM.  Responses carry a ``minics`` metadata block with the MiniCS
version, the model used and which documents/chunks were used.
"""
