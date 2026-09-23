"""Dataset, entry and collection services."""

from __future__ import annotations

import pytest

from minics.domain.entities import Evaluation
from minics.services.base import NotFoundError


def test_dataset_crud(ctx):
    dataset = ctx.datasets.create("Support QA", description="d", tags=["support"])
    assert dataset.slug == "support-qa"

    duplicate = ctx.datasets.create("Support QA")
    assert duplicate.slug == "support-qa-2"

    listing = ctx.datasets.list(search="support")
    assert {d.public_id for d in listing} == {dataset.public_id, duplicate.public_id}

    updated = ctx.datasets.update(dataset.id, {"name": "Support QA v2"})
    assert updated.slug == "support-qa-v2"

    assert ctx.datasets.stats(dataset.id)["entries"] == 0
    assert ctx.datasets.delete(dataset.public_id) is True
    with pytest.raises(NotFoundError):
        ctx.datasets.get(dataset.public_id)


def test_entry_lifecycle_and_versioning(ctx):
    dataset = ctx.datasets.create("SFT")
    entry = ctx.entries.create(
        dataset.id, system="Be brief.", user="What is RRF?", assistant="A fusion method."
    )
    assert entry.position == 1
    assert ctx.entries.validate(entry.id)["valid"] is True
    assert ctx.datasets.stats(dataset.id)["entries"] == 1

    edited = ctx.entries.update(
        entry.id,
        {"messages": [*(m.model_dump() for m in entry.messages),
                      {"role": "assistant", "content": "It fuses ranked lists."}]},
    )
    assert edited.version == 2
    versions = ctx.entries.versions(entry.id)
    assert [v["version"] for v in versions] == [2, 1]

    ctx.entries.add_tags(entry.id, ["rrf", "rrf", "hybrid"])
    assert ctx.entries.get(entry.id).tags == ["rrf", "hybrid"]

    ctx.entries.set_evaluation(entry.id, Evaluation(score=0.9, summary="good"))
    reloaded = ctx.entries.get(entry.id)
    assert reloaded.quality == 0.9
    assert reloaded.evaluation.summary == "good"

    assert ctx.entries.count(dataset=dataset.id, status="draft") == 1
    assert ctx.entries.count(search="RRF") == 1
    assert ctx.entries.delete(entry.public_id) is True


def test_bulk_import_and_validation_problems(ctx):
    created = ctx.entries.bulk_create(
        [
            {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]},
            [{"role": "user", "content": "q2"}],
        ]
    )
    assert len(created) == 2
    assert ctx.entries.validate(created[0].id)["valid"] is True
    assert ctx.entries.validate(created[1].id)["valid"] is False


def test_collections_and_export(ctx):
    dataset = ctx.datasets.create("FAQ")
    first = ctx.entries.create(dataset.id, user="Capital of France?", assistant="Paris.")
    second = ctx.entries.create(dataset.id, user="2+2?", assistant="4.")
    ctx.entries.set_status(first.id, "approved")

    collection = ctx.collections.create("FAQ Set", dataset=dataset.id, entry_ids=[first.id])
    assert collection.entry_ids == [first.id]

    ctx.collections.add_entries(collection.id, [second.id])
    assert len(ctx.collections.entry_ids(collection.id)) == 2

    chatml = ctx.collections.export(collection.id, fmt="chatml")
    assert '"role": "user"' in chatml
    assert len(chatml.splitlines()) == 2

    approved_only = ctx.collections.export(collection.id, fmt="jsonl", only_approved=True)
    assert len(approved_only.splitlines()) == 1

    alpaca = ctx.collections.export(collection.id, fmt="alpaca")
    assert '"instruction": "Capital of France?"' in alpaca

    assert ctx.collections.collections_for_entry(first.id)[0].name == "FAQ Set"

    ctx.collections.remove_entries(collection.id, [second.id])
    assert ctx.collections.entry_ids(collection.id) == [first.id]
