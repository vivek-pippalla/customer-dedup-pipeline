"""End-to-end orchestration, idempotency, review decisions and exports."""

import csv

from dedup.config import load_config
from dedup.db import connect, init_schema
from dedup.ingest import CSV_COLUMNS
from dedup.pipeline import run_pipeline
from dedup.report import export_tables
from dedup.runlog import start_run
from dedup.cli import build_parser


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
    return path


def rows():
    return [
        ["CRM", "a", "Jane Doe", "jane@example.test", "9876543210", "1 Main Road, Town", "123456", "2000-01-01", "2025-01-01T00:00:00Z"],
        ["WEB", "b", "Jane Doe", "jane@example.test", "9876543210", "1 Main Road, Town", "123456", "2000-01-01", "2025-01-02T00:00:00Z"],
        ["IMPORT", "c", "Mary Roe", "jane@example.test", "9123456780", "9 Other Road, Town", "123456", "1999-01-01", "2025-01-03T00:00:00Z"],
    ]


def output_rows(conn, table, order, omit_run=False):
    omit = {"run_id"} if omit_run else set()
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})") if row[1] not in omit]
    return [tuple(row) for row in conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order}")]


def test_rerun_is_idempotent_review_decisions_persist_and_empty_leaves_outputs(tmp_path):
    source = write_csv(tmp_path / "input.csv", rows())
    empty = tmp_path / "empty.csv"
    empty.write_text(",".join(CSV_COLUMNS) + "\n", encoding="utf-8")
    conn = connect(":memory:")
    try:
        config = load_config()
        init_schema(conn, config)
        first = run_pipeline(conn, [source], config, as_of="2025-02-01T00:00:00Z", run_id="run_e2e_one")
        raw_count = conn.execute("SELECT COUNT(*) FROM raw_customer_records").fetchone()[0]
        golden_before = output_rows(conn, "golden_customers", "golden_id", omit_run=True)
        review = conn.execute("SELECT pair_id FROM review_queue ORDER BY pair_id LIMIT 1").fetchone()
        assert review is not None
        conn.execute(
            "INSERT INTO review_decisions (pair_id, decision, reviewer, decided_at, note) VALUES (?, 'merge', 'tester', '2025-02-01T00:00:00Z', 'keep') "
            "ON CONFLICT (pair_id) DO UPDATE SET decision=excluded.decision"
            , (review[0],),
        )
        conn.commit()
        second = run_pipeline(conn, [source], config, as_of="2025-02-02T00:00:00Z", run_id="run_e2e_two")
        assert first["counts"]["new_version_rows"] == 3
        assert second["counts"]["new_version_rows"] == 0
        assert second["counts"]["duplicate_event_rows"] == 3
        assert conn.execute("SELECT COUNT(*) FROM raw_customer_records").fetchone()[0] == raw_count
        assert output_rows(conn, "golden_customers", "golden_id", omit_run=True) == golden_before
        assert conn.execute("SELECT status FROM review_queue WHERE pair_id=?", (review[0],)).fetchone()[0] == "merge"
        before_empty = {table: output_rows(conn, table, order) for table, order in (
            ("golden_customers", "golden_id"), ("golden_members", "golden_id, source_record_id"),
            ("golden_lineage", "golden_id, field_name"), ("candidate_pairs", "pair_id"), ("review_queue", "pair_id"))}
        result = run_pipeline(conn, [empty], config, as_of="2025-02-03T00:00:00Z", run_id="run_e2e_empty")
        assert result["status"] == "success_empty"
        after_empty = {table: output_rows(conn, table, order) for table, order in (
            ("golden_customers", "golden_id"), ("golden_members", "golden_id, source_record_id"),
            ("golden_lineage", "golden_id, field_name"), ("candidate_pairs", "pair_id"), ("review_queue", "pair_id"))}
        assert after_empty == before_empty
    finally:
        conn.close()


def test_shuffled_rows_and_reversed_files_produce_same_golden_tables(tmp_path):
    source_rows = rows()
    first_a = write_csv(tmp_path / "a1.csv", source_rows[:2])
    second_a = write_csv(tmp_path / "a2.csv", source_rows[2:])
    first_b = write_csv(tmp_path / "b1.csv", [source_rows[2], source_rows[0]])
    second_b = write_csv(tmp_path / "b2.csv", [source_rows[1]])
    outputs = []
    for db_order, files in (("one", [first_a, second_a]), ("two", [second_b, first_b])):
        conn = connect(":memory:")
        try:
            config = load_config()
            init_schema(conn, config)
            run_pipeline(conn, files, config, as_of="2025-02-01T00:00:00Z", run_id=f"run_order_{db_order}")
            outputs.append({table: output_rows(conn, table, order, omit_run=True) for table, order in (
                ("golden_customers", "golden_id"), ("golden_members", "golden_id, source_record_id"),
                ("golden_lineage", "golden_id, field_name"), ("candidate_pairs", "pair_id"),
                ("review_queue", "pair_id"))})
        finally:
            conn.close()
    assert outputs[0] == outputs[1]


def test_exports_are_byte_identical_and_run_has_no_truth_option(tmp_path):
    source = write_csv(tmp_path / "input.csv", rows())
    conn = connect(":memory:")
    try:
        config = load_config()
        init_schema(conn, config)
        run_pipeline(conn, [source], config, as_of="2025-02-01T00:00:00Z", run_id="run_export_one")
        export_tables(conn, tmp_path / "export_one")
        run_pipeline(conn, [source], config, as_of="2025-02-02T00:00:00Z", run_id="run_export_two")
        export_tables(conn, tmp_path / "export_two")
        for name in ("golden_customers.csv", "golden_lineage.csv", "review_queue.csv", "rejects.csv"):
            assert (tmp_path / "export_one" / name).read_bytes() == (tmp_path / "export_two" / name).read_bytes()
        parser = build_parser()
        run_parser = next(action for action in parser._subparsers._group_actions[0].choices.values() if action.prog == "dedup run")
        assert "--truth" not in run_parser._option_string_actions
    finally:
        conn.close()
