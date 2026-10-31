"""Previously uncovered input, boundary, and transitive conflict cases."""

import csv
from pathlib import Path

from dedup.config import load_config
from dedup.db import connect, init_schema
from dedup.ingest import CSV_COLUMNS
from dedup.pipeline import PipelineRunError, run_pipeline
from dedup.ingest import RawRow
from dedup.validate import validate_rows


AS_OF = "2025-02-01T00:00:00Z"


def write_csv(path: Path, rows, columns=CSV_COLUMNS):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)
    return path


def snapshot_outputs(conn):
    tables = ("golden_customers", "golden_members", "golden_lineage", "candidate_pairs", "review_queue")
    return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
            for table in tables}


def test_malformed_csv_is_rejected_and_run_continues(tmp_path):
    path = tmp_path / "malformed.csv"
    good = "CRM,good,Jane Doe,jane@example.test,9876543210,1 Main Road,123456,2000-01-01,2025-01-01T00:00:00Z\n"
    path.write_text(",".join(CSV_COLUMNS) + "\nCRM,too,few\n" + good, encoding="utf-8", newline="")
    conn = connect(tmp_path / "malformed.db")
    try:
        config = load_config()
        init_schema(conn, config)
        result = run_pipeline(conn, [path], config, as_of=AS_OF, run_id="run_malformed")
        assert result["counts"]["input_rows"] == 2
        assert result["counts"]["rejected_rows"] == 1
        assert conn.execute("SELECT reason_code FROM rejects").fetchone()[0] == "malformed_row"
        assert conn.execute("SELECT COUNT(*) FROM raw_customer_records").fetchone()[0] == 1
        assert conn.execute("SELECT status FROM runs WHERE run_id='run_malformed'").fetchone()[0] == "success"
    finally:
        conn.close()


def test_schema_mismatch_marks_run_failed_and_extra_columns_warn(tmp_path):
    conn = connect(tmp_path / "schema.db")
    try:
        config = load_config()
        init_schema(conn, config)
        missing = write_csv(tmp_path / "missing.csv", [], CSV_COLUMNS[:-1])
        try:
            run_pipeline(conn, [missing], config, as_of=AS_OF, run_id="run_missing_schema")
        except PipelineRunError as error:
            assert "updated_at" in str(error)
        else:
            raise AssertionError("schema mismatch did not fail the run")
        status = conn.execute("SELECT status, error_message FROM runs WHERE run_id='run_missing_schema'").fetchone()
        assert status["status"] == "failed" and "updated_at" in status["error_message"]
        assert conn.execute("SELECT COUNT(*) FROM raw_customer_records").fetchone()[0] == 0

        extra_columns = (*CSV_COLUMNS, "unused_note")
        values = ["CRM", "one", "Jane Doe", "jane@example.test", "9876543210", "", "", "", "2025-01-01T00:00:00Z", "ignore me"]
        extra = write_csv(tmp_path / "extra.csv", [values], extra_columns)
        result = run_pipeline(conn, [extra], config, as_of=AS_OF, run_id="run_extra_column")
        assert result["status"] == "success"
        assert result["metrics"]["warnings"] == ["ignored extra columns: unused_note"]
        assert conn.execute("SELECT COUNT(*) FROM raw_customer_records").fetchone()[0] == 1
    finally:
        conn.close()


def test_zero_byte_batch_succeeds_without_changing_published_outputs(tmp_path):
    source = write_csv(tmp_path / "one.csv", [["CRM", "one", "Jane Doe", "jane@example.test", "9876543210", "", "", "", "2025-01-01T00:00:00Z"]])
    zero_byte = tmp_path / "zero.csv"
    zero_byte.write_bytes(b"")
    conn = connect(tmp_path / "empty.db")
    try:
        config = load_config()
        init_schema(conn, config)
        run_pipeline(conn, [source], config, as_of=AS_OF, run_id="run_before_zero")
        before = snapshot_outputs(conn)
        result = run_pipeline(conn, [zero_byte], config, as_of=AS_OF, run_id="run_zero_byte")
        assert result["status"] == "success_empty"
        assert snapshot_outputs(conn) == before
    finally:
        conn.close()


def test_timestamp_one_second_beyond_tolerance_is_rejected(tmp_path):
    fields = dict(zip(CSV_COLUMNS, ["CRM", "one", "Jane Doe", "", "", "", "", "", "2025-02-02T00:00:01Z"]))
    row = RawRow("boundary.csv", 1, "boundary row", fields)
    valid, rejects = validate_rows([row], AS_OF, ["CRM"], 24)
    assert valid == []
    assert len(rejects) == 1 and rejects[0].reason_code == "future_timestamp"


def test_one_character_name_long_address_and_empty_optional_values_are_kept(tmp_path):
    long_address = "A" * 300
    path = write_csv(tmp_path / "boundary.csv", [["CRM", "one", "Q", "", "", long_address, "", "", "2025-01-01T00:00:00Z"]])
    conn = connect(tmp_path / "boundary.db")
    try:
        config = load_config()
        init_schema(conn, config)
        result = run_pipeline(conn, [path], config, as_of=AS_OF, run_id="run_boundaries")
        golden = conn.execute("SELECT full_name, address FROM golden_customers").fetchone()
        assert result["counts"]["rejected_rows"] == 0
        assert tuple(golden) == ("Q", long_address)
    finally:
        conn.close()


def test_transitive_chain_with_conflicting_endpoints_is_demoted_to_review(tmp_path):
    records = [
        ["CRM", "a", "Jane Smith", "shared@example.test", "", "1 Main Road, Town", "123456", "2000-01-01", "2025-01-01T00:00:00Z"],
        ["WEB", "b", "Jane Smith", "shared@example.test", "9876543210", "1 Main Road, Town", "123456", "", "2025-01-02T00:00:00Z"],
        ["IMPORT", "c", "Jane Smith", "", "9876543210", "1 Main Road, Town", "123456", "2001-01-01", "2025-01-03T00:00:00Z"],
    ]
    path = write_csv(tmp_path / "transitive.csv", records)
    conn = connect(tmp_path / "transitive.db")
    try:
        config = load_config()
        init_schema(conn, config)
        result = run_pipeline(conn, [path], config, as_of=AS_OF, run_id="run_transitive")
        assert all(golden.member_count == 1 for golden in result["compute_result"].golden_records)
        reasons = [pair.result.reason_code for pair in result["compute_result"].review_pairs]
        assert reasons.count("transitive_conflict") == 3
        assert conn.execute("SELECT COUNT(*) FROM review_queue WHERE reason_code='transitive_conflict'").fetchone()[0] == 3
    finally:
        conn.close()
