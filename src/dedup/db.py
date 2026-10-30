"""Database connection and schema helpers."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dedup.config import load_config


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a configured SQLite connection, creating its parent directory."""
    database = str(path)
    if database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if database != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    return connection


def init_schema(conn: sqlite3.Connection) -> None:
    """Apply the packaged schema and seed configured source systems."""
    schema_path = Path(__file__).with_name("schema.sql")
    schema_sql = schema_path.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    config = load_config()
    priorities = config["source_priority"]
    if not isinstance(priorities, dict):
        raise ValueError("configuration source_priority must be a table")
    conn.executemany(
        "INSERT INTO source_systems (source_system, priority) VALUES (?, ?) "
        "ON CONFLICT (source_system) DO UPDATE SET priority = excluded.priority",
        sorted(priorities.items()),
    )
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block in an immediate transaction, rolling it back on failure."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
