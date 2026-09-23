"""Document conversion, RAG indexing, graph topology and RRF fusion."""

from __future__ import annotations

from minics.documents.convert import clean_markdown, convert_file, detect_kind
from minics.rag.fusion import fuse_hit_lists, reciprocal_rank_fusion


def test_detect_kind_and_clean_markdown(tmp_path):
    assert detect_kind("a.pdf") == "pdf"
    assert detect_kind("b.docx") == "docx"
    assert detect_kind("c.tex") == "latex"
    assert detect_kind("d.md") == "markdown"
    cleaned = clean_markdown("Title\n\n\n\nPage 3\n\nbody   \ntext")
    assert "Page 3" not in cleaned
    assert "body" in cleaned


def test_convert_text_and_latex(tmp_path):
    text = tmp_path / "note.txt"
    text.write_text("INTRODUCTION\n\nSome  content here.\n", encoding="utf-8")
    converted = convert_file(text)
    assert converted.kind == "text"
    assert "## Introduction" in converted.markdown

    tex = tmp_path / "paper.tex"
    tex.write_text(
        "\\section{Intro}We use \\textbf{transformers} and " + "$x^2$" + ".",
        encoding="utf-8",
    )
    converted = convert_file(tex)
    assert converted.kind == "latex"
    assert "## Intro" in converted.markdown
    assert "**transformers**" in converted.markdown


def test_rrf_fusion_prefers_agreement():
    scores = reciprocal_rank_fusion({"vector": ["a", "b"], "graph": ["b", "c"]}, k=60)
    assert scores["b"] > scores["a"] and scores["b"] > scores["c"]

    fused = fuse_hit_lists(
        {"vector": [{"chunk_id": "a"}, {"chunk_id": "b"}], "graph": [{"chunk_id": "b"}]},
        key="chunk_id",
    )
    assert fused[0]["chunk_id"] == "b"
    assert set(fused[0]["sources"]) == {"vector", "graph"}


def test_vector_and_graph_indexing(ctx, fake_embed):
    document = ctx.documents.add_text(
        "# Retrieval\n\nReciprocal Rank Fusion combines ranked lists.\n\n"
        "## Graph\n\nThe graph stores entities and co-occurrence edges.",
        title="RAG Notes",
    )
    result = ctx.indexer.index_document(document.id)
    assert result["chunks"] >= 1
    assert ctx.vectorstore.count() == result["chunks"]
    assert ctx.documents.get(document.id).chunk_count == result["chunks"]

    graph_result = ctx.graph_indexer.index_document(document.id)
    assert graph_result["entities"] > 0
    stats = ctx.graph.stats()
    assert stats["documents"] == 1 and stats["chunks"] == result["chunks"]
    assert ctx.graph.find_entities(["Rank Fusion"])

    # Re-indexing is idempotent.
    ctx.indexer.index_document(document.id)
    assert ctx.vectorstore.count() == result["chunks"]

    ctx.indexer.remove_document(document.id)
    assert ctx.vectorstore.count() == 0


def test_hybrid_retrieval_and_grounding(ctx, fake_embed):
    first = ctx.documents.add_text(
        "# Fusion\n\nReciprocal Rank Fusion merges ranked lists from retrievers.",
        title="Fusion Notes",
    )
    second = ctx.documents.add_text(
        "# Graphs\n\nGraphs store entities and edges between them.", title="Graph Notes"
    )
    for document in (first, second):
        ctx.indexer.index_document(document.id)
        ctx.graph_indexer.index_document(document.id)

    result = ctx.retriever.retrieve("reciprocal rank fusion retrievers")
    assert result.used_rag and result.used_graph
    assert result.chunks
    assert result.chunks[0].fused_score > 0
    assert result.citations()
    assert "Fusion" in result.context_text()

    vector_only = ctx.retriever.retrieve("entities edges", use_graph=False)
    assert all("graph" not in chunk.sources for chunk in vector_only.chunks)
    assert ctx.retriever.retrieve("x", use_rag=False, use_graph=False).chunks == []

    filtered = ctx.retriever.retrieve("entities", document_ids=[second.id])
    assert all(chunk.document_id == second.id for chunk in filtered.chunks)
