"""Ordered schema migrations.

Each :class:`~minics.core.db.Migration` is applied exactly once, in ascending
``version`` order, inside the writer thread.  Add a new migration whenever the
database shape changes — never edit a released migration.

Migration 1 introduces the runtime key/value store used for small bits of state
that do not belong in the user-facing config (window position, last opened
dataset, ...).
"""

from __future__ import annotations

from minics.core.db import Migration

MIGRATIONS: list[Migration] = [
    Migration(
        version=1,
        name="core_kv_store",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS schema_log (
                version     INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """,
        ),
    ),
    Migration(
        version=2,
        name="datasets_entries_collections_documents",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id   TEXT NOT NULL UNIQUE,
                name        TEXT NOT NULL,
                slug        TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                tags        TEXT NOT NULL DEFAULT '[]',
                source      TEXT NOT NULL DEFAULT 'manual',
                metadata    TEXT NOT NULL DEFAULT '{}',
                settings    TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id   TEXT NOT NULL UNIQUE,
                dataset_id  INTEGER REFERENCES datasets(id) ON DELETE CASCADE,
                status      TEXT NOT NULL DEFAULT 'draft',
                messages    TEXT NOT NULL DEFAULT '[]',
                tags        TEXT NOT NULL DEFAULT '[]',
                notes       TEXT NOT NULL DEFAULT '',
                quality     REAL,
                evaluation  TEXT,
                source      TEXT NOT NULL DEFAULT 'manual',
                metadata    TEXT NOT NULL DEFAULT '{}',
                position    INTEGER NOT NULL DEFAULT 0,
                version     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS entry_versions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id    INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                version     INTEGER NOT NULL,
                snapshot    TEXT NOT NULL,
                reason      TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL,
                UNIQUE (entry_id, version)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS collections (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id   TEXT NOT NULL UNIQUE,
                name        TEXT NOT NULL,
                slug        TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                dataset_id  INTEGER REFERENCES datasets(id) ON DELETE SET NULL,
                tags        TEXT NOT NULL DEFAULT '[]',
                metadata    TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS collection_entries (
                collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                entry_id      INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                position      INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (collection_id, entry_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS documents (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id      TEXT NOT NULL UNIQUE,
                title          TEXT NOT NULL,
                source         TEXT NOT NULL DEFAULT '',
                kind           TEXT NOT NULL DEFAULT '',
                original_path  TEXT NOT NULL DEFAULT '',
                markdown_path  TEXT NOT NULL DEFAULT '',
                size_bytes     INTEGER NOT NULL DEFAULT 0,
                sha256         TEXT NOT NULL DEFAULT '',
                status         TEXT NOT NULL DEFAULT 'pending',
                error          TEXT NOT NULL DEFAULT '',
                chunk_count    INTEGER NOT NULL DEFAULT 0,
                tags           TEXT NOT NULL DEFAULT '[]',
                metadata       TEXT NOT NULL DEFAULT '{}',
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS document_chunks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id   TEXT NOT NULL UNIQUE,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                idx         INTEGER NOT NULL DEFAULT 0,
                text        TEXT NOT NULL DEFAULT '',
                tokens      INTEGER NOT NULL DEFAULT 0,
                heading     TEXT NOT NULL DEFAULT '',
                vector_id   TEXT NOT NULL DEFAULT '',
                metadata    TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                UNIQUE (document_id, idx)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id     TEXT NOT NULL UNIQUE,
                title         TEXT NOT NULL DEFAULT 'New conversation',
                system_prompt TEXT NOT NULL DEFAULT '',
                use_rag       INTEGER NOT NULL DEFAULT 1,
                use_graph     INTEGER NOT NULL DEFAULT 1,
                use_grounding INTEGER NOT NULL DEFAULT 1,
                dataset_id    INTEGER REFERENCES datasets(id) ON DELETE SET NULL,
                metadata      TEXT NOT NULL DEFAULT '{}',
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id       TEXT NOT NULL UNIQUE,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                idx             INTEGER NOT NULL DEFAULT 0,
                role            TEXT NOT NULL,
                content         TEXT NOT NULL DEFAULT '',
                citations       TEXT NOT NULL DEFAULT '[]',
                model           TEXT,
                usage           TEXT NOT NULL DEFAULT '{}',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_entries_dataset ON entries(dataset_id)",
            "CREATE INDEX IF NOT EXISTS idx_entries_status ON entries(status)",
            "CREATE INDEX IF NOT EXISTS idx_entry_versions_entry ON entry_versions(entry_id)",
            "CREATE INDEX IF NOT EXISTS idx_coll_entries_entry ON collection_entries(entry_id)",
            "CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)",
            "CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc ON document_chunks(document_id)",
            "CREATE INDEX IF NOT EXISTS idx_conversation_messages_conv "
            "ON conversation_messages(conversation_id)",
        ),
    ),
]

