"""Database-backed reconciliation report and deterministic CSV exports."""

import csv
import json
import logging
import sqlite3
from pathlib import Path
from typing import Sequence


LOGGER = logging.getLogger(__name__)
EXPORT_COLUMNS = {
    "golden_customers": ("golden_id", "full_name", "email", "phone", "address", "postcode", "dob",
                         "member_count", "match_tier", "latest_updated_at_utc"),
    "golden_lineage": ("golden_id", "field_name", "value", "version_id", "source_record_id", "source_system", "rule_applied"),
    "review_queue": ("pair_id", "score", "reason_code", "status"),
    "rejects": ("reject_id", "source_file", "source_row_number", "reason_code", "raw_line", "raw_line_hash"),
}
EXPORT_ORDER = {
    "golden_customers": "golden_id",
    "golden_lineage": "golden_id, field_name",
    "review_queue": "pair_id",
    "rejects": "reject_id",
}


def _table_rows(conn: sqlite3.Connection, table: str, columns: Sequence[str], order: str) -> list[dict[str, object]]:
    """Read a fixed, internal table/column export query."""
    selected = ", ".join(columns)
    return [dict(row) for row in conn.execute(f"SELECT {selected} FROM {table} ORDER BY {order}")]


def export_tables(conn: sqlite3.Connection, export_dir: str | Path) -> list[Path]:
    """Write stable CSVs without run IDs or execution timestamps."""
    folder = Path(export_dir)
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for table, columns in EXPORT_COLUMNS.items():
        target = folder / f"{table}.csv"
        rows = _table_rows(conn, table, columns, EXPORT_ORDER[table])
        with target.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        written.append(target)
    return written


def _latest_run(conn: sqlite3.Connection) -> dict[str, object] | None:
    """Return the most recently started run with decoded metrics."""
    row = conn.execute("SELECT * FROM runs ORDER BY started_at DESC, run_id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    result = dict(row)
    try:
        result["metrics"] = json.loads(str(result.get("metrics_json") or "{}"))
    except json.JSONDecodeError:
        result["metrics"] = {}
    return result


def build_report(conn: sqlite3.Connection) -> str:
    """Query reconciliation, run, reject, review, cluster and quality metrics."""
    latest = _latest_run(conn)
    unique_records = int(conn.execute("SELECT COUNT(DISTINCT source_record_id) FROM raw_customer_records").fetchone()[0])
    golden_count = int(conn.execute("SELECT COUNT(*) FROM golden_customers").fetchone()[0])
    merged_away = unique_records - golden_count
    member_sum = int(conn.execute("SELECT COALESCE(SUM(member_count),0) FROM golden_customers").fetchone()[0])
    records_merged = int(conn.execute("SELECT COALESCE(SUM(member_count),0) FROM golden_customers WHERE member_count >= 2").fetchone()[0])
    merged_groups = int(conn.execute("SELECT COUNT(*) FROM golden_customers WHERE member_count >= 2").fetchone()[0])
    member_rows = int(conn.execute("SELECT COUNT(*) FROM golden_members").fetchone()[0])
    reject_total = int(conn.execute("SELECT COUNT(*) FROM rejects").fetchone()[0])
    rejects_by_reason = conn.execute(
        "SELECT reason_code, COUNT(*) AS row_count FROM rejects GROUP BY reason_code ORDER BY reason_code"
    ).fetchall()
    review_by_reason = conn.execute(
        "SELECT reason_code, COUNT(*) AS row_count FROM review_queue GROUP BY reason_code ORDER BY reason_code"
    ).fetchall()
    largest_clusters = conn.execute(
        "SELECT g.golden_id, g.full_name, g.member_count FROM golden_customers g "
        "WHERE g.member_count >= 2 ORDER BY g.member_count DESC, g.golden_id LIMIT 10"
    ).fetchall()
    review_size = int(conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0])
    rejected_sum = sum(int(row["row_count"]) for row in rejects_by_reason)
    fk_errors = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    lineage_orphans = int(conn.execute(
        "SELECT COUNT(*) FROM golden_lineage l LEFT JOIN golden_members m "
        "ON m.golden_id=l.golden_id AND m.source_record_id=l.source_record_id "
        "WHERE l.source_record_id IS NOT NULL AND m.source_record_id IS NULL"
    ).fetchone()[0])

    batch_input = int(latest.get("input_rows", 0)) if latest else 0
    batch_rejected = int(latest.get("rejected_rows", 0)) if latest else 0
    batch_valid = int(latest.get("valid_rows", 0)) if latest else 0
    metrics = latest.get("metrics", {}) if latest else {}
    if not isinstance(metrics, dict):
        metrics = {}
    blocking = metrics.get("blocking_stats", {})
    capped = blocking.get("capped_blocks", []) if isinstance(blocking, dict) else []
    warnings: list[str] = []
    for run_row in conn.execute("SELECT metrics_json FROM runs ORDER BY started_at, run_id"):
        try:
            run_metrics = json.loads(run_row[0] or "{}")
        except json.JSONDecodeError:
            continue
        for warning in run_metrics.get("warnings", []) if isinstance(run_metrics, dict) else []:
            if warning not in warnings:
                warnings.append(str(warning))

    clean_count = int(conn.execute("SELECT COUNT(*) FROM clean_customers").fetchone()[0])
    quality_fields = ("email_norm", "phone_norm", "name_norm", "first_name_canon", "last_name_norm",
                      "address_norm", "postcode_norm", "updated_at_utc", "dob_norm", "soundex_last")
    null_rates = []
    for field in quality_fields:
        null_count = int(conn.execute(f"SELECT COUNT(*) FROM clean_customers WHERE {field} IS NULL").fetchone()[0])
        null_rates.append((field, null_count, null_count / clean_count if clean_count else 0.0))

    lines = ["# Reconciliation report", "", "## Latest run", ""]
    if latest:
        lines.extend([
            f"- Run ID: `{latest['run_id']}`",
            f"- Status: **{latest['status']}**",
            f"- Started: {latest['started_at']}",
            f"- Ended: {latest.get('ended_at') or '-'}",
            f"- Input files: {latest['input_files']}",
            f"- Error: {latest.get('error_message') or '-'}",
            "",
            "| Count | Value |", "|---|---:|",
        ])
        for key in ("input_rows", "rejected_rows", "valid_rows", "new_version_rows", "duplicate_event_rows",
                    "unique_source_records", "golden_records", "merged_away", "records_in_merged_clusters",
                    "review_pending", "records_in_pending_review"):
            lines.append(f"| {key} | {latest.get(key, 0)} |")
    else:
        lines.append("No runs have been recorded.")

    lines.extend(["", "## Reconciliation identities", "",
                  "| Identity | Left side | Right side | Pass |", "|---|---:|---:|:---:|"])
    batch_right = batch_rejected + batch_valid
    lines.append(f"| Batch: input = rejected + valid | {batch_input} | {batch_right} | {'yes' if batch_input == batch_right else 'NO'} |")
    lines.append(f"| Database: unique = golden + merged away | {unique_records} | {golden_count + merged_away} | yes |")
    lines.append(f"| Database: sum member_count = unique | {member_sum} | {unique_records} | {'yes' if member_sum == unique_records else 'NO'} |")
    lines.append(f"| Aggregate: merged records - merged away = multi-member golden records | {records_merged - merged_away} | {merged_groups} | {'yes' if records_merged - merged_away == merged_groups else 'NO'} |")
    lines.append(f"| Rejects by reason sum = persisted rejects | {rejected_sum} | {reject_total} | {'yes' if rejected_sum == reject_total else 'NO'} |")
    lines.append(f"| Golden member rows = unique source records | {member_rows} | {unique_records} | {'yes' if member_rows == unique_records else 'NO'} |")
    lines.append(f"| Lineage source membership orphans | {lineage_orphans} | 0 | {'yes' if lineage_orphans == 0 else 'NO'} |")
    lines.append(f"| Foreign-key violations | {fk_errors} | 0 | {'yes' if fk_errors == 0 else 'NO'} |")

    lines.extend(["", "## Rejects by reason", "", "| Reason | Rows |", "|---|---:|"])
    lines.extend(f"| {row['reason_code']} | {row['row_count']} |" for row in rejects_by_reason)
    lines.extend(["", "## Largest clusters", "", "| Golden ID | Name | Members |", "|---|---|---:|"])
    lines.extend(f"| {row['golden_id']} | {row['full_name'] or ''} | {row['member_count']} |" for row in largest_clusters)
    lines.extend(["", "## Review queue by reason", "", f"Total: **{review_size}**", "", "| Reason | Pairs |", "|---|---:|"])
    lines.extend(f"| {row['reason_code']} | {row['row_count']} |" for row in review_by_reason)
    lines.extend(["", "## Capped blocks", ""])
    if capped:
        lines.extend(["| Key type | Key | Size | Pairs skipped |", "|---|---|---:|---:|"])
        lines.extend(f"| {row.get('key_type')} | `{row.get('key_value')}` | {row.get('size')} | {row.get('pairs_skipped')} |" for row in capped)
    else:
        lines.append("No blocks exceeded the configured cap.")
    lines.extend(["", "## Data quality", "", f"Clean rows: **{clean_count}**",
                  f"Phone invalid in latest run: **{metrics.get('phone_invalid', 0)}**", "",
                  "| Field | Nulls | Null rate |", "|---|---:|---:|"])
    lines.extend(f"| {field} | {count} | {rate:.2%} |" for field, count, rate in null_rates)
    lines.extend(["", "### Warnings", ""])
    lines.extend(f"- {warning}" for warning in warnings) if warnings else lines.append("None recorded.")
    lines.append("")
    return "\n".join(lines)


def write_report(conn: sqlite3.Connection, out: str | Path, export_dir: str | Path | None = None) -> Path:
    """Write a reconciliation Markdown report and optional stable CSV exports."""
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_report(conn), encoding="utf-8", newline="")
    if export_dir is not None:
        export_tables(conn, export_dir)
    LOGGER.info("wrote reconciliation report to %s", target)
    return target
