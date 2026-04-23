"""SQLite database setup and connection management."""

import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".captainslog" / "log.db"

# Set to False at runtime if the SQLite build lacks FTS5.
FTS5_AVAILABLE: bool = True


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply any schema migrations that are not covered by CREATE IF NOT EXISTS."""
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(entries)")}
    if "recurrence" not in existing_cols:
        conn.execute("ALTER TABLE entries ADD COLUMN recurrence TEXT")
        conn.commit()


def _init_fts(conn: sqlite3.Connection) -> bool:
    """Create FTS5 virtual table and sync triggers. Returns True if FTS5 is available."""
    global FTS5_AVAILABLE  # noqa: PLW0603
    try:
        conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
                title, body,
                content='entries',
                content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS entries_fts_ai AFTER INSERT ON entries BEGIN
                INSERT INTO entries_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
            END;

            CREATE TRIGGER IF NOT EXISTS entries_fts_ad AFTER DELETE ON entries BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, title, body)
                    VALUES ('delete', old.id, old.title, old.body);
            END;

            CREATE TRIGGER IF NOT EXISTS entries_fts_au AFTER UPDATE ON entries BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, title, body)
                    VALUES ('delete', old.id, old.title, old.body);
                INSERT INTO entries_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
            END;
        """)
        # Rebuild to index any rows that existed before FTS was set up.
        conn.execute("INSERT INTO entries_fts(entries_fts) VALUES ('rebuild')")
        conn.commit()
        FTS5_AVAILABLE = True
    except sqlite3.OperationalError:
        FTS5_AVAILABLE = False
    return FTS5_AVAILABLE


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                body        TEXT,
                status      TEXT NOT NULL DEFAULT 'todo',
                priority    TEXT NOT NULL DEFAULT 'normal',
                category    TEXT NOT NULL DEFAULT 'inbox',
                due_date    TEXT,
                recurrence  TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_entries_status   ON entries(status);
            CREATE INDEX IF NOT EXISTS idx_entries_category ON entries(category);
            CREATE INDEX IF NOT EXISTS idx_entries_due_date ON entries(due_date);
        """)
        _migrate(conn)
        _init_fts(conn)
