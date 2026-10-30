"""Tests for SQLite schema and transaction handling."""

import sqlite3
from pathlib import Path

import pytest

from dedup.db import connect, init_schema, transaction
from dedup.runlog import start_run


def test_schema_is_idempotent_and_seeds_sources() -> None:
    """Applying the schema twice preserves all tables and source priorities."""
    conn = connect(":memory:")
    try:
        init_schema(conn)
        init_schema(conn)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        assert len(tables) == 11
        assert [tuple(row) for row in conn.execute(
            "SELECT source_system, priority FROM source_systems ORDER BY priority"
        )] == [("CRM", 1), ("WEB", 2), ("IMPORT", 3)]
    finally:
        conn.close()


def test_connect_configures_wal_foreign_keys_and_parent_folder(tmp_path: Path) -> None:
    """File connections create parents and enable the required SQLite settings."""
    database = tmp_path / "nested" / "pipeline.db"
    conn = connect(database)
    try:
        assert database.exists()
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_memory_connection_skips_wal() -> None:
    """In-memory databases keep SQLite's memory journal mode."""
    conn = connect(":memory:")
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "memory"
    finally:
        conn.close()


def test_foreign_keys_and_status_checks_are_enforced() -> None:
    """Connections enforce source references and run status checks."""
    conn = connect(":memory:")
    try:
        init_schema(conn)
        run_id = start_run(conn, "run_fk_test", started_at="2025-01-01T00:00:00Z")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO raw_customer_records "
                "(version_id, source_record_id, row_hash, source_system, source_native_id, full_name, updated_at, first_seen_run_id) "
                "VALUES ('v1', 's1', 'h1', 'UNKNOWN', 'n1', 'Name', '2025-01-01T00:00:00Z', ?) "
                "ON CONFLICT (version_id) DO NOTHING",
                (run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO runs (run_id, started_at, status) VALUES ('bad', '2025-01-01T00:00:00Z', 'bogus') "
                "ON CONFLICT (run_id) DO NOTHING"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO review_decisions (pair_id, decision) VALUES ('p1', 'bogus') "
                         "ON CONFLICT (pair_id) DO NOTHING")
        conn.execute(
            "INSERT INTO candidate_pairs "
            "(pair_id, source_record_id_a, source_record_id_b, score, coverage, decision, reason_code, run_id) "
            "VALUES ('p1', 'a', 'b', 0.8, 0.7, 'review', 'name_only', ?) "
            "ON CONFLICT (pair_id) DO NOTHING",
            (run_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO candidate_pairs "
                "(pair_id, source_record_id_a, source_record_id_b, score, coverage, decision, reason_code, run_id) "
                "VALUES ('p2', 'a', 'c', 0.8, 0.7, 'bogus', 'name_only', ?) "
                "ON CONFLICT (pair_id) DO NOTHING",
                (run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO review_queue (pair_id, score, reason_code, status, run_id) "
                "VALUES ('p1', 0.8, 'name_only', 'bogus', ?) ON CONFLICT (pair_id) DO NOTHING",
                (run_id,),
            )
    finally:
        conn.close()


def test_transaction_rolls_back_on_exception() -> None:
    """An exception rolls back all writes in a transaction block."""
    conn = connect(":memory:")
    try:
        init_schema(conn)
        with pytest.raises(RuntimeError, match="rollback"):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO source_systems (source_system, priority) VALUES ('TEMP', 10) "
                    "ON CONFLICT (source_system) DO NOTHING"
                )
                raise RuntimeError("rollback")
        assert conn.execute("SELECT 1 FROM source_systems WHERE source_system='TEMP'").fetchone() is None
    finally:
        conn.close()


def test_run_log_survives_rolled_back_data_transaction() -> None:
    """The committed run record remains when later data work rolls back."""
    conn = connect(":memory:")
    try:
        init_schema(conn)
        run_id = start_run(conn, "run_survives", started_at="2025-01-01T00:00:00Z")
        with pytest.raises(RuntimeError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO rejects (source_file, source_row_number, reason_code, first_seen_run_id) "
                    "VALUES ('input.csv', 2, 'missing_required', ?) "
                    "ON CONFLICT (source_file, source_row_number, raw_line_hash) DO NOTHING",
                    (run_id,),
                )
                raise RuntimeError("data transaction failed")
        assert conn.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()["status"] == "running"
        assert conn.execute("SELECT COUNT(*) FROM rejects").fetchone()[0] == 0
    finally:
        conn.close()
