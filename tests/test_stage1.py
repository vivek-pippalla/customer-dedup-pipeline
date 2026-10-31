"""Stage 1 transaction, accounting and rerun behavior."""

import csv
from pathlib import Path

from dedup.config import load_config
from dedup.db import connect, init_schema
from dedup.runlog import start_run
from dedup.pipeline import stage1_ingest
from dedup.ingest import CSV_COLUMNS


def write_file(path: Path, rows=(), columns=CSV_COLUMNS):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)
    return path


def test_stage1_counts_rerun_rejects_and_phone_metric(tmp_path):
    good = ["CRM", "x", "Jane Doe", "jane@example.test", "123456789", "", "", "", "2025-01-01T00:00:00Z"]
    bad = ["CRM", "y", "John Doe", "bad-email", "", "", "", "", "2025-01-01T00:00:00Z"]
    path = write_file(tmp_path / "batch.csv", [good, bad])
    conn = connect(":memory:")
    try:
        init_schema(conn)
        config = load_config()
        first_run = start_run(conn, "run_stage_one", started_at="2025-01-01T00:00:00Z")
        first = stage1_ingest(conn, [path], config, {"run_id": first_run, "as_of": "2025-01-01T00:00:00Z"})
        second_run = start_run(conn, "run_stage_two", started_at="2025-01-01T00:00:00Z")
        second = stage1_ingest(conn, [path], config, {"run_id": second_run, "as_of": "2025-01-01T00:00:00Z"})
        assert (first["input_rows"], first["rejected_rows"], first["new_version_rows"], first["duplicate_event_rows"]) == (2, 1, 1, 0)
        assert first["metrics"]["phone_invalid"] == 1
        assert second["new_version_rows"] == 0 and second["rejected_rows"] == 1
        assert conn.execute("SELECT COUNT(*) FROM rejects").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM clean_customers").fetchone()[0] == 1
    finally:
        conn.close()


def test_schema_error_and_empty_batch_leave_tables_unchanged(tmp_path):
    conn = connect(":memory:")
    try:
        init_schema(conn)
        config = load_config()
        run_id = start_run(conn, "run_file_error", started_at="2025-01-01T00:00:00Z")
        path = write_file(tmp_path / "missing.csv", [], columns=CSV_COLUMNS[:-1])
        failed = stage1_ingest(conn, [path], config, {"run_id": run_id, "as_of": "2025-01-01T00:00:00Z"})
        assert failed["status"] == "failed" and "updated_at" in failed["error"]
        assert conn.execute("SELECT COUNT(*) FROM raw_customer_records").fetchone()[0] == 0
        empty = tmp_path / "empty.csv"
        empty.write_text(",".join(CSV_COLUMNS) + "\n", encoding="utf-8")
        empty_run = start_run(conn, "run_empty", started_at="2025-01-01T00:00:00Z")
        result = stage1_ingest(conn, [empty], config, {"run_id": empty_run, "as_of": "2025-01-01T00:00:00Z"})
        assert result["status"] == "success_empty"
    finally:
        conn.close()

