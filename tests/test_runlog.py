"""Tests for persistent pipeline run logging."""

from pathlib import Path

from dedup.db import connect, init_schema
from dedup.runlog import finish_run, mark_abandoned_runs, start_run


def test_start_and_finish_run_commit_state() -> None:
    """Run status and metrics are committed and serialized deterministically."""
    conn = connect(":memory:")
    try:
        init_schema(conn)
        run_id = start_run(conn, "run_finish", started_at="2025-01-01T00:00:00Z", input_files=["b.csv", "a.csv"])
        finish_run(conn, run_id, "success", {"input_rows": 4, "new_version_rows": 3}, {"z": 1, "a": 2}, None)
        row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        assert row["status"] == "success"
        assert row["input_rows"] == 4
        assert row["new_version_rows"] == 3
        assert row["input_files"] == '["a.csv","b.csv"]'
        assert row["metrics_json"] == '{"a":2,"z":1}'
        assert row["ended_at"].endswith("Z")
    finally:
        conn.close()


def test_abandoned_runs_are_failed_with_required_error() -> None:
    """Leftover running rows are marked failed and explain why."""
    conn = connect(":memory:")
    try:
        init_schema(conn)
        start_run(conn, "run_abandoned", started_at="2025-01-01T00:00:00Z")
        assert mark_abandoned_runs(conn) == 1
        row = conn.execute("SELECT status, error_message, ended_at FROM runs WHERE run_id='run_abandoned'").fetchone()
        assert row["status"] == "failed"
        assert row["error_message"] == "abandoned: process stopped before finishing"
        assert row["ended_at"].endswith("Z")
    finally:
        conn.close()


def test_start_run_marks_previous_running_run_abandoned() -> None:
    """Starting a new execution recovers any unfinished execution first."""
    conn = connect(":memory:")
    try:
        init_schema(conn)
        start_run(conn, "run_previous", started_at="2025-01-01T00:00:00Z")
        start_run(conn, "run_current", started_at="2025-01-01T00:01:00Z")
        rows = conn.execute("SELECT run_id, status FROM runs ORDER BY run_id").fetchall()
        assert [(row["run_id"], row["status"]) for row in rows] == [
            ("run_current", "running"), ("run_previous", "failed")
        ]
    finally:
        conn.close()


def test_data_dictionary_generation_and_missing_description(tmp_path: Path) -> None:
    """The schema dictionary renders fully and rejects a missing description."""
    import pytest

    from scripts.gen_data_dictionary import COLUMN_DESCRIPTIONS, generate_dictionary, render_dictionary

    conn = connect(":memory:")
    try:
        init_schema(conn)
        shortened = {table: dict(columns) for table, columns in COLUMN_DESCRIPTIONS.items()}
        del shortened["runs"]["status"]
        with pytest.raises(ValueError, match="runs.status"):
            render_dictionary(conn, shortened)
    finally:
        conn.close()

    destination = generate_dictionary(tmp_path / "DATA_DICTIONARY.md")
    markdown = destination.read_text(encoding="utf-8")
    assert "## `runs`" in markdown
    assert "A12" in markdown

