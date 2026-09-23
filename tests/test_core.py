"""Paths, config and SQLite behaviour."""

from __future__ import annotations

import threading

from minics.core.config import SECRET_MASK, ConfigManager
from minics.core.db import Database
from minics.core.paths import get_paths


def test_paths_layout(home):
    paths = get_paths(str(home)).ensure()
    assert paths.config_file.name == "config.json"
    assert paths.database.name == "minics.sqlite3"
    assert paths.vectordb.is_dir()
    assert paths.graphdb.is_dir()
    assert paths.markdown_dir.is_dir()
    assert paths.originals_dir.is_dir()


def test_config_roundtrip_and_masking(home):
    manager = ConfigManager(get_paths(str(home)))
    manager.update(
        {
            "llm": {"base_url": "http://localhost:1234/v1", "api_key": "sk-test", "model": "m"},
            "embedding": {"model": "e", "dimension": 8},
        }
    )
    public = manager.load().public_dict()
    assert public["llm"]["api_key"] == SECRET_MASK
    assert public["llm"]["api_key_set"] is True
    # A blank embedding URL falls back to the LLM endpoint, so nothing is missing.
    assert public["embedding"]["effective_base_url"] == "http://localhost:1234/v1"
    assert public["missing_requirements"] == []
    assert public["ready"] is True

    # Saving with the mask keeps the original key.
    manager.update({"llm": {"api_key": SECRET_MASK, "model": "m2"}})
    assert manager.load().llm.api_key == "sk-test"
    assert manager.load().llm.model == "m2"


def test_config_requires_an_endpoint(home):
    manager = ConfigManager(get_paths(str(home)))
    manager.update({"embedding": {"model": "e", "dimension": 8}})
    missing = manager.load().missing_requirements()
    assert "LLM base URL" in missing
    assert "Embedding base URL" in missing


def test_embedding_endpoint_can_differ(home):
    manager = ConfigManager(get_paths(str(home)))
    manager.update(
        {
            "llm": {"base_url": "http://192.168.1.135:8000/v1", "model": "llama"},
            "embedding": {
                "base_url": "http://192.168.1.130:11434/v1",
                "model": "nomic-embed-text",
                "dimension": 768,
            },
        }
    )
    config = manager.load()
    assert config.llm.base_url == "http://192.168.1.135:8000/v1"
    assert config.embedding_base_url == "http://192.168.1.130:11434/v1"
    assert config.is_ready() is True


def test_database_concurrent_writes(home):
    paths = get_paths(str(home)).ensure()
    db = Database(paths.database)
    db.initialize()
    assert db.schema_version >= 1

    def write(index: int) -> None:
        db.set_state(f"key{index}", str(index))

    threads = [threading.Thread(target=write, args=(index,)) for index in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert db.scalar("SELECT COUNT(*) FROM app_state") == 40
    assert db.scalar("PRAGMA journal_mode") == "wal"
    db.close()
