"""Transactional publishing, rollback, reconciliation and persistent decisions."""

import csv
from dataclasses import replace
from hashlib import sha256

import pytest

from dedup.config import load_config
from dedup.db import connect, init_schema
from dedup.ingest import CSV_COLUMNS
from dedup.pipeline import PipelineRunError, run_pipeline


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
    return path


def _rows():
    return [
        ["CRM", "a", "Jane Doe", "jane@example.test", "9876543210", "1 Main Road, Town", "123456", "2000-01-01", "2025-01-01T00:00:00Z"],
        ["WEB", "b", "Jane Doe", "jane@example.test", "9876543210", "1 Main Road, Town", "123456", "2000-01-01", "2025-01-02T00:00:00Z"],
        ["IMPORT", "c", "Mary Roe", "jane@example.test", "9123456780", "9 Other Road, Town", "123456", "1999-01-01", "2025-01-03T00:00:00Z"],
    ]


def _snapshot(conn, table, order, omit=()):
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})") if row[1] not in omit]
    rows = conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order}").fetchall()
    payload = repr((columns, [tuple(row) for row in rows])).encode("utf-8")
    return len(rows), sha256(payload).hexdigest()


def _publish_snapshots(conn, stable=False):
    omit = ("run_id",) if stable else ()
    return {
        "golden_customers": _snapshot(conn, "golden_customers", "golden_id", omit),
        "golden_members": _snapshot(conn, "golden_members", "golden_id, source_record_id"),
        "golden_lineage": _snapshot(conn, "golden_lineage", "golden_id, field_name", omit),
        "candidate_pairs": _snapshot(conn, "candidate_pairs", "pair_id", omit),
        "review_queue": _snapshot(conn, "review_queue", "pair_id", omit),
    }


def test_fault_mid_publish_rolls_back_and_failed_run_is_logged(tmp_path):
    source = _write_csv(tmp_path / "customers.csv", _rows())
    conn = connect(":memory:")
    try:
        config = load_config()
        init_schema(conn, config)
        first = run_pipeline(conn, [source], config, as_of="2025-02-01T00:00:00Z", run_id="run_good")
        before = _publish_snapshots(conn)
        before_stable = _publish_snapshots(conn, stable=True)

        def fail_midway(stage):
            if stage == "mid_inserts":
                raise RuntimeError("injected publish fault")

        with pytest.raises(PipelineRunError, match="injected publish fault"):
            run_pipeline(conn, [source], config, as_of="2025-02-02T00:00:00Z", run_id="run_fault", fault_hook=fail_midway)
        assert _publish_snapshots(conn) == before
        assert conn.execute("SELECT status FROM runs WHERE run_id='run_fault'").fetchone()[0] == "failed"
        retry = run_pipeline(conn, [source], config, as_of="2025-02-03T00:00:00Z", run_id="run_retry")
        assert retry["status"] == "success"
        assert _publish_snapshots(conn, stable=True) == before_stable
        assert conn.execute("SELECT COUNT(*) FROM golden_members").fetchone()[0] == conn.execute(
            "SELECT COUNT(DISTINCT source_record_id) FROM raw_customer_records").fetchone()[0]
    finally:
        conn.close()


def test_failed_identity_check_rolls_back_publish_and_marks_run_failed(tmp_path, monkeypatch):
    source = _write_csv(tmp_path / "customers.csv", _rows())
    conn = connect(":memory:")
    try:
        config = load_config()
        init_schema(conn, config)
        run_pipeline(conn, [source], config, as_of="2025-02-01T00:00:00Z", run_id="run_initial")
        computed = run_pipeline(conn, [source], config, as_of="2025-02-02T00:00:00Z", run_id="run_compute")
        before = _publish_snapshots(conn)
        import dedup.pipeline as pipeline_module

        real_compute = pipeline_module.compute_all

        def inconsistent_compute(connection, loaded_config):
            result = real_compute(connection, loaded_config)
            wrong_counts = dict(result.counts, unique_source_records=result.counts["unique_source_records"] + 1)
            return replace(result, counts=wrong_counts)

        monkeypatch.setattr(pipeline_module, "compute_all", inconsistent_compute)
        with pytest.raises(PipelineRunError, match="computed_unique_source_records"):
            run_pipeline(conn, [source], config, as_of="2025-02-04T00:00:00Z", run_id="run_bad_identity")
        assert _publish_snapshots(conn) == before
        failed = conn.execute("SELECT status, error_message FROM runs WHERE run_id='run_bad_identity'").fetchone()
        assert failed["status"] == "failed" and "computed_unique_source_records" in failed["error_message"]
    finally:
        conn.close()


def test_orphan_checks_are_zero_after_publish(tmp_path):
    source = _write_csv(tmp_path / "customers.csv", _rows())
    conn = connect(":memory:")
    try:
        init_schema(conn)
        run_pipeline(conn, [source], load_config(), as_of="2025-02-01T00:00:00Z", run_id="run_orphans")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
