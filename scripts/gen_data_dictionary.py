"""Generate the data dictionary from the live SQLite schema."""

import sqlite3
from pathlib import Path

from dedup.db import connect, init_schema


TABLE_GRAINS = {
    "source_systems": "one source system",
    "runs": "one pipeline execution",
    "raw_customer_records": "one delivered version of one source record",
    "rejects": "one rejected input row",
    "clean_customers": "one normalized valid version",
    "candidate_pairs": "one auto_merge or review pair in the current computation",
    "golden_customers": "one real-world customer",
    "golden_members": "one source record in one golden record",
    "golden_lineage": "one field of one golden record",
    "review_queue": "one uncertain pair in the current computation (regenerated each run)",
    "review_decisions": "one human decision (never deleted)",
}

COLUMN_DESCRIPTIONS = {
    "source_systems": {
        "source_system": "Canonical source system key.", "priority": "Configured survivorship priority.",
    },
    "runs": {
        "run_id": "Unique identity of one pipeline execution.", "started_at": "UTC time the run started.",
        "ended_at": "UTC time the run finished, or NULL while running.", "status": "Execution status.",
        "input_files": "JSON array of input file names.", "input_rows": "Number of input data rows.",
        "rejected_rows": "Number of rejected input rows.", "valid_rows": "Rows that passed input validation.",
        "new_version_rows": "Newly stored valid versions.",
        "duplicate_event_rows": "Valid deliveries already stored as versions.",
        "unique_source_records": "Distinct source records in stored history.",
        "golden_records": "Number of published golden customers.", "merged_away": "Source records merged into other records.",
        "records_in_merged_clusters": "Source records belonging to multi-member golden records.",
        "review_pending": "Number of pending review pairs.",
        "records_in_pending_review": "Distinct source records appearing in pending review pairs.",
        "metrics_json": "JSON object of run metrics.",
        "config_snapshot": "JSON snapshot of effective run configuration.", "error_message": "Failure detail, if any.",
    },
    "raw_customer_records": {
        "version_id": "Deterministic identity of this delivered version.",
        "source_record_id": "Stable identity of the logical source record.", "row_hash": "Fingerprint of original field values.",
        "source_system": "Originating source system.", "source_native_id": "Original identifier in the source system.",
        "full_name": "Original customer name.", "email": "Original email value.", "phone": "Original phone value.",
        "address": "Original address value.", "postcode": "Original postcode value.", "dob": "Original date of birth value.",
        "updated_at": "Original source update timestamp.", "source_file": "Input file basename.",
        "source_row_number": "One-based CSV row number including the header.",
        "first_seen_run_id": "Run that first stored this version.",
    },
    "rejects": {
        "reject_id": "SQLite-assigned surrogate key for a rejected row.", "source_file": "Input file basename.",
        "source_row_number": "One-based CSV row number including the header.", "reason_code": "Validation reason for rejection.",
        "raw_line": "Original rejected CSV line.", "raw_line_hash": "Fingerprint of the original rejected line.",
        "first_seen_run_id": "Run that first recorded this rejection.",
    },
    "clean_customers": {
        "version_id": "Version identity shared with the raw record.",
        "source_record_id": "Stable identity of the logical source record.", "email_norm": "Trimmed lowercase email.",
        "phone_norm": "Normalized valid ten-digit phone, otherwise NULL.", "name_norm": "Normalized full name.",
        "first_name_canon": "First name after the explicit nickname lookup.",
        "first_is_initial": "Whether the canonical first name is one character (0 or 1).",
        "last_name_norm": "Normalized last name.", "address_norm": "Normalized address.",
        "postcode_norm": "Normalized six-digit postcode, otherwise NULL.",
        "updated_at_utc": "Source update timestamp normalized to UTC.",
        "dob_norm": "ISO date of birth, otherwise NULL.", "soundex_last": "Hand-computed Soundex of the normalized last name.",
    },
    "candidate_pairs": {
        "pair_id": "Deterministic identity of the unordered source-record pair.",
        "source_record_id_a": "Smaller source record ID in the pair.",
        "source_record_id_b": "Larger source record ID in the pair.", "email_score": "Email feature score, when present.",
        "phone_score": "Phone feature score, when present.", "name_score": "Name feature score, when present.",
        "address_score": "Address feature score, when present.", "dob_score": "DOB feature score, when present.",
        "score": "Weighted pair score after missing-feature renormalization.",
        "coverage": "Fraction of configured weight represented by shared features.",
        "decision": "Classification decision retained for this pair.", "reason_code": "Reason for the classification.",
        "match_tier": "Exact or probable auto-merge tier, otherwise NULL.", "run_id": "Run that computed the pair.",
    },
    "golden_customers": {
        "golden_id": "Deterministic identity derived from sorted cluster members.",
        "full_name": "Surviving customer name.", "email": "Surviving email.", "phone": "Surviving phone.",
        "address": "Surviving address.", "postcode": "Surviving postcode.", "dob": "Surviving date of birth.",
        "member_count": "Number of source records in the cluster.", "match_tier": "Cluster summary tier.",
        "latest_updated_at_utc": "Latest member update timestamp.", "run_id": "Run that published this record.",
    },
    "golden_members": {
        "golden_id": "Golden record containing this source record.",
        "source_record_id": "Member source record identity.", "version_id": "Member version used in this computation.",
    },
    "golden_lineage": {
        "golden_id": "Golden record whose field is described.", "field_name": "Name of the survived field.",
        "value": "Surviving field value, or NULL when absent.", "version_id": "Version that supplied the value.",
        "source_record_id": "Source record that supplied the value.", "source_system": "Source system that supplied the value.",
        "rule_applied": "Survivorship rule that selected the value.", "run_id": "Run that produced this lineage.",
    },
    "review_queue": {
        "pair_id": "Candidate pair awaiting or carrying a review decision.", "score": "Pair score shown to reviewers.",
        "reason_code": "Reason the pair was sent to review.", "status": "Pending or recorded reviewer decision.",
        "run_id": "Run that generated this queue row.",
    },
    "review_decisions": {
        "pair_id": "Stable identity of the reviewed source-record pair.", "decision": "Human decision for the pair.",
        "reviewer": "Reviewer identifier, when supplied.", "decided_at": "UTC time the decision was recorded.",
        "note": "Optional reviewer note.",
    },
}

TABLE_ORIGINS = {
    "source_systems": "source", "runs": "derived", "raw_customer_records": "source",
    "rejects": "source", "clean_customers": "derived", "candidate_pairs": "derived",
    "golden_customers": "derived", "golden_members": "derived", "golden_lineage": "derived",
    "review_queue": "derived", "review_decisions": "source",
}

ASSUMPTIONS = (
    ("A1", "The entity is customers and all data is synthetic", "Metrics do not transfer to real data"),
    ("A2", "Email and phone are strong but not unique per person (families, role mailboxes)", "Handled by `shared_identifier_conflict` and the block cap"),
    ("A3", "`(source_system, source_native_id)` identifies one logical record; a re-delivery with changed content is an update", "If a source reuses native IDs, unrelated people merge"),
    ("A4", "`updated_at` is the business time of a version; naive timestamps are UTC", "Wrong current version if sources use local time"),
    ("A5", "Phones are Indian 10-digit numbers (+91 and leading 0 handled); an invalid phone becomes NULL and the row is kept", "International numbers lose the phone feature"),
    ("A6", "Source priority is CRM > WEB > IMPORT (config)", "Different winners when values tie on other rules"),
    ("A7", "A wrong merge costs more than a missed duplicate", "Thresholds favour precision; the review queue grows"),
    ("A8", "File basenames are unique per ingested file", "Reject idempotency key could collide"),
    ("A9", "DOB, when present on both records, is reliable enough to block auto-merge; but entry errors exist, so a mismatch with a strong identifier goes to review", "Some true duplicates wait for a human"),
    ("A10", "Full recompute is affordable up to the benchmarked size (100k rows)", "Needs an incremental design beyond that"),
    ("A11", "One writer at a time (SQLite)", "No concurrent runs"),
    ("A12", 'Ground truth is the generator\'s entity ids, the only notion of "true duplicate" available', "Metrics reflect the generator's noise model"),
)


def _schema_tables(conn: sqlite3.Connection) -> list[str]:
    """Return user table names in a stable order."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [row[0] for row in rows]


def _columns(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    """Read columns for one live SQLite table."""
    return list(conn.execute(f'PRAGMA table_info("{table}")'))


def _foreign_keys(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    """Map foreign-key columns to their referenced table and column."""
    rows = conn.execute(f'PRAGMA foreign_key_list("{table}")')
    return {row["from"]: f"{row['table']}.{row['to']}" for row in rows}


def render_dictionary(
    conn: sqlite3.Connection,
    column_descriptions: dict[str, dict[str, str]] = COLUMN_DESCRIPTIONS,
) -> str:
    """Render schema metadata and fail if any live table or column lacks a description."""
    tables = _schema_tables(conn)
    missing_tables = sorted(set(tables) - set(TABLE_GRAINS))
    missing_grains = sorted(set(tables) - set(TABLE_GRAINS))
    missing_descriptions = sorted(set(tables) - set(column_descriptions))
    problems = [f"missing table description: {name}" for name in missing_tables]
    problems.extend(f"missing table grain: {name}" for name in missing_grains)
    problems.extend(f"missing column description: {name}" for name in missing_descriptions)
    for table in tables:
        documented = column_descriptions.get(table, {})
        problems.extend(
            f"missing column description: {table}.{row['name']}"
            for row in _columns(conn, table)
            if row["name"] not in documented or not documented[row["name"]]
        )
    if problems:
        raise ValueError("; ".join(problems))

    lines = ["# Data dictionary", "", "## Table grains", ""]
    lines.extend(f"- **{table}**: {TABLE_GRAINS[table]}" for table in tables)
    lines.extend(("", "## Assumptions", "", "| ID | Assumption | If it is wrong |", "|---|---|---|"))
    lines.extend(f"| {key} | {assumption} | {consequence} |" for key, assumption, consequence in ASSUMPTIONS)
    for table in tables:
        lines.extend(("", f"## `{table}`", "", f"**Grain:** {TABLE_GRAINS[table]}.", ""))
        lines.extend(("| Column | SQLite type | Nullable | Key | Source or derived | Description |", "|---|---|---|---|---|---|"))
        foreign_keys = _foreign_keys(conn, table)
        columns = _columns(conn, table)
        primary_keys = [row for row in columns if row["pk"]]
        for column in columns:
            name = column["name"]
            key_parts = []
            if column["pk"]:
                key_parts.append("PK" if len(primary_keys) == 1 else f"PK ({column['pk']})")
            if name in foreign_keys:
                key_parts.append(f"FK → `{foreign_keys[name]}`")
            key = ", ".join(key_parts) if key_parts else "—"
            nullable = "no" if column["notnull"] or column["pk"] else "yes"
            description = column_descriptions[table][name].replace("|", "\\|")
            lines.append(
                f"| `{name}` | {column['type'] or '—'} | {nullable} | {key} | "
                f"{TABLE_ORIGINS[table]} | {description} |"
            )
    return "\n".join(lines) + "\n"


def generate_dictionary(output_path: str | Path | None = None) -> Path:
    """Generate the data dictionary from a fresh in-memory initialized database."""
    destination = Path(output_path) if output_path is not None else Path(__file__).resolve().parents[1] / "docs" / "DATA_DICTIONARY.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(":memory:")
    try:
        init_schema(conn)
        markdown = render_dictionary(conn)
    finally:
        conn.close()
    destination.write_text(markdown, encoding="utf-8", newline="")
    return destination


def main() -> None:
    """Generate the checked schema reference."""
    try:
        generate_dictionary()
    except (OSError, sqlite3.Error, ValueError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
