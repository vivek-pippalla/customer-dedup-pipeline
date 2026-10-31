"""End-to-end backfill and ground-truth isolation scenarios."""

import csv
from pathlib import Path

from dedup.cli import build_parser
from dedup.config import load_config
from dedup.db import connect, init_schema
from dedup.ingest import CSV_COLUMNS
from dedup.pipeline import run_pipeline


def _write(path: Path, row):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        writer.writerow(row)
    return path


def test_record_in_second_file_with_older_timestamp_does_not_replace_golden_values(tmp_path):
    newer = _write(tmp_path / "newer.csv", ["CRM", "same-id", "Newer Name", "newer@example.test", "9876543210",
                                               "1 Main Road", "123456", "2000-01-01", "2025-01-10T00:00:00Z"])
    older = _write(tmp_path / "older.csv", ["CRM", "same-id", "Older Name", "older@example.test", "9876543210",
                                               "9 Old Road", "654321", "1999-01-01", "2025-01-09T00:00:00Z"])
    conn = connect(tmp_path / "late.db")
    try:
        config = load_config()
        init_schema(conn, config)
        result = run_pipeline(conn, [newer, older], config, as_of="2025-02-01T00:00:00Z", run_id="run_late_file")
        assert result["counts"]["new_version_rows"] == 2
        golden = conn.execute("SELECT full_name, email, address, latest_updated_at_utc FROM golden_customers").fetchone()
        assert tuple(golden) == ("Newer Name", "newer@example.test", "1 Main Road", "2025-01-10T00:00:00Z")
    finally:
        conn.close()


def test_run_has_no_truth_argument_and_only_evaluator_reads_truth_csv():
    parser = build_parser()
    run_parser = parser._subparsers._group_actions[0].choices["run"]
    assert "--truth" not in run_parser._option_string_actions
    source_dir = Path(__file__).resolve().parents[1] / "src" / "dedup"
    readers = [path.name for path in source_dir.glob("*.py") if "csv.DictReader" in path.read_text(encoding="utf-8")]
    assert readers == ["evaluate.py"]
