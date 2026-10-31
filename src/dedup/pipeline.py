"""Stage orchestration for customer ingestion and validation."""

import hashlib
import logging
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from dedup.db import transaction
from dedup.ingest import BatchRead, RawRow, compute_keys, insert_versions, read_batch
from dedup.normalize import normalize_row
from dedup.validate import validate_rows


LOGGER = logging.getLogger(__name__)
CLEAN_INSERT = (
    "INSERT INTO clean_customers (version_id, source_record_id, email_norm, phone_norm, name_norm, "
    "first_name_canon, first_is_initial, last_name_norm, address_norm, postcode_norm, updated_at_utc, dob_norm, soundex_last) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (version_id) DO NOTHING"
)


def _config_value(config: Mapping[str, object], section: str, key: str, default: object) -> object:
    table = config.get(section, {})
    return table.get(key, default) if isinstance(table, Mapping) else default


def stage1_ingest(
    conn: sqlite3.Connection, paths: Iterable[str | Path], config: Mapping[str, object], run: Mapping[str, object],
) -> dict[str, object]:
    """Read, validate, normalize and atomically append a Stage 1 batch."""
    run_id = str(run["run_id"])
    started = str(run.get("as_of") or run.get("started_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    tolerance = float(_config_value(config, "validation", "future_tolerance_hours", 24))
    systems = [row[0] for row in conn.execute("SELECT source_system FROM source_systems ORDER BY source_system")]
    batches: list[tuple[BatchRead, list[RawRow], list[RawRow]]] = []
    input_rows = 0
    warnings: list[str] = []
    all_rejects: list[RawRow] = []
    all_valid: list[RawRow] = []
    for path in paths:
        batch = read_batch(path)
        if batch.file_error:
            return {"status": "failed", "error": batch.file_error, "input_rows": 0,
                    "rejected_rows": 0, "valid_rows": 0, "new_version_rows": 0,
                    "duplicate_event_rows": 0, "metrics": {"phone_invalid": 0, "rejects_by_reason": {}, "warnings": warnings}}
        warnings.extend(batch.warnings)
        input_rows += len(batch.rows) + len(batch.structural_rejects)
        valid, rejects = validate_rows(batch.rows, started, systems, tolerance)
        rejects.extend(batch.structural_rejects)
        for reject in batch.structural_rejects:
            if reject.reason_code is None:
                reject.reason_code = "malformed_row"
        all_valid.extend(valid)
        all_rejects.extend(rejects)
        batches.append((batch, valid, rejects))

    if all(path_batch.is_empty for path_batch, _, _ in batches):
        return {"status": "success_empty", "error": None, "input_rows": 0, "rejected_rows": 0,
                "valid_rows": 0, "new_version_rows": 0, "duplicate_event_rows": 0,
                "metrics": {"phone_invalid": 0, "rejects_by_reason": {}, "warnings": warnings}}

    reasons = Counter(row.reason_code for row in all_rejects)
    phone_invalid = sum(int(normalize_row(row).phone_invalid) for row in all_valid)
    new_versions = duplicate_events = 0
    try:
        with transaction(conn):
            inserted_ids: set[str] = set()
            for row in all_valid:
                compute_keys(row)
            new_versions, duplicate_events = insert_versions(conn, all_valid, run_id)
            # Determine newly inserted versions from their first-seen run within this transaction.
            inserted_ids = {row[0] for row in conn.execute(
                "SELECT version_id FROM raw_customer_records WHERE first_seen_run_id = ?", (run_id,)
            )}
            for row in sorted(all_valid, key=lambda item: (item.version_id or "")):
                if row.version_id not in inserted_ids:
                    continue
                normalized = normalize_row(row)
                conn.execute(CLEAN_INSERT, (
                    row.version_id, row.source_record_id, normalized.email_norm, normalized.phone_norm,
                    normalized.name_norm, normalized.first_name_canon, int(normalized.first_is_initial),
                    normalized.last_name_norm, normalized.address_norm, normalized.postcode_norm,
                    normalized.updated_at_utc, normalized.dob_norm, normalized.soundex_last,
                ))
            for reject in all_rejects:
                raw_hash = hashlib.sha1(reject.raw_line.encode("utf-8")).hexdigest()[:16]
                conn.execute(
                    "INSERT INTO rejects (source_file, source_row_number, reason_code, raw_line, raw_line_hash, first_seen_run_id) "
                    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (source_file, source_row_number, raw_line_hash) DO NOTHING",
                    (reject.source_file, reject.source_row_number, reject.reason_code, reject.raw_line, raw_hash, run_id),
                )
    except Exception:
        LOGGER.exception("stage 1 transaction failed for run %s", run_id)
        raise
    valid_rows = new_versions + duplicate_events
    assert input_rows == len(all_rejects) + valid_rows, "batch identity: input_rows != rejected_rows + valid_rows"
    metrics = {"phone_invalid": phone_invalid, "rejects_by_reason": dict(sorted(reasons.items())), "warnings": warnings}
    return {"status": "success", "error": None, "input_rows": input_rows,
            "rejected_rows": len(all_rejects), "valid_rows": valid_rows,
            "new_version_rows": new_versions, "duplicate_event_rows": duplicate_events,
            "metrics": metrics}
