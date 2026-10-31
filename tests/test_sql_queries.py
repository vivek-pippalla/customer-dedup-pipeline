"""Smoke-test every documented sample SQL query against a real small pipeline DB."""

import csv
import re
import sqlite3
from pathlib import Path

from dedup.config import load_config
from dedup.db import connect, init_schema
from dedup.pipeline import run_pipeline


ROOT = Path(__file__).resolve().parents[1]


def _queries() -> dict[str, str]:
    content = (ROOT / "sql" / "sample_queries.sql").read_text(encoding="utf-8")
    pieces = re.split(r"(?m)^-- QUERY: ([a-z0-9_]+)\s*$", content)
    return {pieces[index]: pieces[index + 1].strip()
            for index in range(1, len(pieces), 2)}


def _write_fixture(path: Path) -> Path:
    columns = ("source_system", "source_native_id", "full_name", "email", "phone",
               "address", "postcode", "dob", "updated_at")
    rows = [
        ["CRM", "person-001", "Maya Patel", "maya@example.com", "9876543210", "1 Main Road", "560001", "1980-01-01", "2024-01-01T00:00:00Z"],
        ["WEB", "person-002", "Maya Patel", "maya@example.com", "9876543210", "1 Main Road", "560001", "1980-01-01", "2024-01-01T00:00:00Z"],
        ["IMPORT", "person-003", "Maya Patel", "maya@example.com", "9876543210", "1 Main Road", "560001", "1980-01-01", "2024-01-01T00:00:00Z"],
        ["CRM", "family-004", "Ravi Shah", "family@example.com", "9876543211", "2 Oak Road", "560002", "1985-02-02", "2024-01-01T00:00:00Z"],
        ["WEB", "family-005", "Nina Shah", "family@example.com", "9876543212", "3 Oak Road", "560002", "1986-03-03", "2024-01-01T00:00:00Z"],
        ["IMPORT", "single-006", "Ira Das", "ira@example.com", "9876543213", "4 Pine Road", "560003", "1990-04-04", "2024-01-01T00:00:00Z"],
        ["CRM", "invalid-007", "Bad Email", "not-an-email", "9876543214", "5 Pine Road", "560004", "1991-05-05", "2024-01-01T00:00:00Z"],
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)
    return path


def test_all_documented_sql_queries_run_and_return_expected_results(tmp_path):
    queries = _queries()
    assert set(queries) == {
        "reconciliation_identities", "foreign_key_orphans", "rejects_by_reason",
        "largest_clusters_with_members", "three_source_rows_one_golden_lineage",
        "review_queue_with_both_records", "merged_away_by_source_system",
        "version_and_duplicate_event_counts_by_run",
    }

    database = tmp_path / "queries.sqlite"
    source = _write_fixture(tmp_path / "customers.csv")
    conn = connect(database)
    try:
        config = load_config()
        init_schema(conn, config)
        result = run_pipeline(conn, [source], config, as_of="2025-01-01T00:00:00Z")
        assert result["status"] == "success"

        identities = conn.execute(queries["reconciliation_identities"]).fetchall()
        assert len(identities) == 6
        assert all(row["passed"] == 1 for row in identities)

        orphan_checks = conn.execute(queries["foreign_key_orphans"]).fetchall()
        assert len(orphan_checks) == 14
        assert all(row["orphan_count"] == 0 for row in orphan_checks)

        rejects = conn.execute(queries["rejects_by_reason"]).fetchall()
        assert [(row["reason_code"], row["reject_count"]) for row in rejects] == [("invalid_email", 1)]

        largest = conn.execute(queries["largest_clusters_with_members"]).fetchall()
        assert len(largest) == 3
        assert {row["member_count"] for row in largest} == {3}

        lineage = conn.execute(queries["three_source_rows_one_golden_lineage"]).fetchall()
        assert len(lineage) == 6
        assert len({row["field_name"] for row in lineage}) == 6
        assert {row["member_count"] for row in lineage} == {3}

        review = conn.execute(queries["review_queue_with_both_records"]).fetchall()
        assert len(review) == 1
        assert review[0]["reason_code"] == "dob_conflict"
        assert review[0]["name_a"] and review[0]["name_b"]
        assert review[0]["email_a"] == review[0]["email_b"] == "family@example.com"

        merged = conn.execute(queries["merged_away_by_source_system"]).fetchall()
        assert sum(row["merged_away_count"] for row in merged) == 2

        by_run = conn.execute(queries["version_and_duplicate_event_counts_by_run"]).fetchall()
        assert len(by_run) == 1
        assert by_run[0]["input_rows"] == 7
        assert by_run[0]["new_version_rows"] == 6
        assert by_run[0]["duplicate_event_rows"] == 0
        assert by_run[0]["rejected_rows"] == 1
    finally:
        conn.close()
