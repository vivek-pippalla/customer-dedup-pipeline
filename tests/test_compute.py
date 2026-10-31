"""Stage 2 computes output in memory and leaves database tables unchanged."""

import csv

from dedup.config import load_config
from dedup.db import connect, init_schema
from dedup.ingest import CSV_COLUMNS
from dedup.pipeline import compute_all, stage1_ingest
from dedup.runlog import start_run


def test_compute_all_returns_singleton_outputs_without_database_writes(tmp_path):
    path = tmp_path / "one.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(CSV_COLUMNS)
        writer.writerow(["CRM", "one", "Jane Doe", "jane@example.test", "9876543210", "1 Main Road", "123456", "2000-01-01", "2025-01-01T00:00:00Z"])
    conn = connect(":memory:")
    try:
        config = load_config()
        init_schema(conn, config)
        run_id = start_run(conn, "run_compute_test", started_at="2025-01-01T00:00:00Z")
        result = stage1_ingest(conn, [path], config, {"run_id": run_id, "as_of": "2025-01-01T00:00:00Z"})
        assert result["status"] == "success"
        before = conn.execute("SELECT COUNT(*) FROM raw_customer_records").fetchone()[0]
        computed = compute_all(conn, config)
        assert len(computed.golden_records) == 1
        assert len(computed.members) == 1
        assert len(computed.lineage_rows) == 6
        assert computed.golden_records[0].match_tier == "single"
        assert conn.execute("SELECT COUNT(*) FROM raw_customer_records").fetchone()[0] == before
        assert conn.execute("SELECT COUNT(*) FROM golden_customers").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM candidate_pairs").fetchone()[0] == 0
    finally:
        conn.close()
