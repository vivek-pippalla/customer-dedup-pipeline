"""Atomic replacement of current golden and review outputs."""

import sqlite3
from collections.abc import Callable, Mapping

from dedup.db import transaction
from dedup.pipeline import ComputeResult


class ReconciliationError(AssertionError):
    """A named reconciliation identity failed inside the publish transaction."""


def _assert_equal(name: str, left_label: str, left: int, right_label: str, right: int) -> dict[str, int | str]:
    """Assert one numeric identity and return its recorded operands."""
    result = {"identity": name, left_label: left, right_label: right}
    if left != right:
        raise ReconciliationError(f"{name} failed: {left_label}={left}, {right_label}={right}")
    return result


def _reconcile(
    conn: sqlite3.Connection, result: ComputeResult, input_counts: Mapping[str, int] | None,
    rejects_by_reason: Mapping[str, int] | None,
) -> dict[str, object]:
    """Check batch, database, aggregate, lineage, and foreign-key identities."""
    identities: dict[str, object] = {}
    if input_counts is not None:
        valid = int(input_counts["new_version_rows"]) + int(input_counts["duplicate_event_rows"])
        batch_parts = int(input_counts["rejected_rows"]) + valid
        identities["batch"] = _assert_equal("batch identity", "input_rows", int(input_counts["input_rows"]),
                                             "rejected_rows_plus_valid_rows", batch_parts)
        expected_rejects = sum((rejects_by_reason or {}).values())
        identities["rejects_by_reason"] = _assert_equal("reject reason identity", "rejected_rows",
                                                          int(input_counts["rejected_rows"]),
                                                          "sum_rejects_by_reason", expected_rejects)

    unique_records = int(conn.execute("SELECT COUNT(DISTINCT source_record_id) FROM raw_customer_records").fetchone()[0])
    golden_count = int(conn.execute("SELECT COUNT(*) FROM golden_customers").fetchone()[0])
    merged_away = unique_records - golden_count
    identities["database"] = _assert_equal("database identity", "unique_source_records", unique_records,
                                             "golden_records_plus_merged_away", golden_count + merged_away)
    member_sum = int(conn.execute("SELECT COALESCE(SUM(member_count), 0) FROM golden_customers").fetchone()[0])
    identities["golden_member_sum"] = _assert_equal("golden member sum identity", "sum_member_count", member_sum,
                                                      "unique_source_records", unique_records)
    member_rows = int(conn.execute("SELECT COUNT(*) FROM golden_members").fetchone()[0])
    identities["golden_members"] = _assert_equal("golden_members identity", "golden_members_count", member_rows,
                                                   "unique_source_records", unique_records)
    merged_records = int(conn.execute("SELECT COALESCE(SUM(member_count),0) FROM golden_customers WHERE member_count >= 2").fetchone()[0])
    merged_groups = int(conn.execute("SELECT COUNT(*) FROM golden_customers WHERE member_count >= 2").fetchone()[0])
    identities["merged_clusters"] = _assert_equal("merged cluster aggregate identity", "records_in_merged_clusters_minus_merged_away",
                                                    merged_records - merged_away, "multi_member_golden_records", merged_groups)
    orphan_lineage = int(conn.execute(
        "SELECT COUNT(*) FROM golden_lineage l LEFT JOIN golden_members m "
        "ON m.golden_id=l.golden_id AND m.source_record_id=l.source_record_id "
        "WHERE l.source_record_id IS NOT NULL AND m.source_record_id IS NULL"
    ).fetchone()[0])
    identities["lineage_membership"] = _assert_equal("lineage membership identity", "orphan_lineage_rows", orphan_lineage,
                                                       "expected_orphan_lineage_rows", 0)
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    identities["foreign_keys"] = _assert_equal("foreign key identity", "foreign_key_violations", len(fk_errors),
                                                "expected_foreign_key_violations", 0)
    if result.counts.get("unique_source_records") != unique_records:
        raise ReconciliationError(
            "compute/database identity failed: computed_unique_source_records="
            f"{result.counts.get('unique_source_records')}, database_unique_source_records={unique_records}"
        )
    computed_checks = {
        "golden_records": golden_count,
        "merged_away": merged_away,
        "records_in_merged_clusters": merged_records,
        "review_pending": int(conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0]),
        "records_in_pending_review": int(conn.execute(
            "SELECT COUNT(DISTINCT source_record_id) FROM ("
            " SELECT p.source_record_id_a AS source_record_id FROM review_queue q JOIN candidate_pairs p USING(pair_id)"
            " UNION SELECT p.source_record_id_b FROM review_queue q JOIN candidate_pairs p USING(pair_id))"
        ).fetchone()[0]),
    }
    for name, actual in computed_checks.items():
        expected = int(result.counts.get(name, -1))
        _assert_equal(f"computed {name} identity", f"computed_{name}", expected, f"database_{name}", actual)
    return identities


def publish(
    conn: sqlite3.Connection, result: ComputeResult, run_id: str,
    fault_hook: Callable[[str], None] | None = None,
    input_counts: Mapping[str, int] | None = None,
    rejects_by_reason: Mapping[str, int] | None = None,
) -> dict[str, object]:
    """Replace computed outputs atomically, preserving all human review decisions."""
    with transaction(conn):
        conn.execute("DELETE FROM review_queue")
        conn.execute("DELETE FROM golden_lineage")
        conn.execute("DELETE FROM golden_members")
        conn.execute("DELETE FROM candidate_pairs")
        conn.execute("DELETE FROM golden_customers")
        if fault_hook:
            fault_hook("after_deletes")

        for golden in result.golden_records:
            conn.execute(
                "INSERT INTO golden_customers (golden_id, full_name, email, phone, address, postcode, dob, member_count, match_tier, latest_updated_at_utc, run_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (golden_id) DO NOTHING",
                (golden.golden_id, golden.full_name, golden.email, golden.phone, golden.address, golden.postcode,
                 golden.dob, golden.member_count, golden.match_tier, golden.latest_updated_at_utc, run_id),
            )
        for candidate in result.candidate_pairs:
            features = candidate.features
            conn.execute(
                "INSERT INTO candidate_pairs (pair_id, source_record_id_a, source_record_id_b, email_score, phone_score, name_score, address_score, dob_score, score, coverage, decision, reason_code, match_tier, run_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (pair_id) DO NOTHING",
                (candidate.pair_id, candidate.source_record_id_a, candidate.source_record_id_b,
                 features.email, features.phone, features.name, features.address, features.dob,
                 features.score, features.coverage, candidate.result.decision, candidate.result.reason_code,
                 candidate.result.match_tier, run_id),
            )
        if fault_hook:
            fault_hook("mid_inserts")
        conn.executemany(
            "INSERT INTO golden_members (golden_id, source_record_id, version_id) VALUES (?, ?, ?) "
            "ON CONFLICT (golden_id, source_record_id) DO NOTHING",
            [(row["golden_id"], row["source_record_id"], row["version_id"]) for row in result.members],
        )
        conn.executemany(
            "INSERT INTO golden_lineage (golden_id, field_name, value, version_id, source_record_id, source_system, rule_applied, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (golden_id, field_name) DO NOTHING",
            [(row["golden_id"], row["field_name"], row["value"], row["version_id"], row["source_record_id"],
              row["source_system"], row["rule_applied"], run_id) for row in result.lineage_rows],
        )
        for review in result.review_pairs:
            conn.execute(
                "INSERT INTO review_queue (pair_id, score, reason_code, status, run_id) "
                "SELECT ?, ?, ?, COALESCE(d.decision, 'pending'), ? FROM (SELECT 1) "
                "LEFT JOIN review_decisions d ON d.pair_id = ? "
                "ON CONFLICT (pair_id) DO NOTHING",
                (review.pair_id, review.features.score, review.result.reason_code, run_id, review.pair_id),
            )
        return _reconcile(conn, result, input_counts, rejects_by_reason)
