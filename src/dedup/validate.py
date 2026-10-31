"""Row-level validation and deterministic duplicate-key rejection."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from dedup.ingest import RawRow, compute_keys
from dedup.normalize import normalize_email, normalize_timestamp


REQUIRED_FIELDS = ("source_system", "source_native_id", "full_name", "updated_at")


def _as_utc(value: str) -> datetime | None:
    normalized = normalize_timestamp(value)
    if normalized is None:
        return None
    return datetime.strptime(normalized, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def validate_rows(
    rows: Iterable[RawRow], run_started_at: str, source_systems: Iterable[str], tolerance_hours: float,
) -> tuple[list[RawRow], list[RawRow]]:
    """Return valid rows and rejects, assigning each row its first failure."""
    started = _as_utc(run_started_at)
    if started is None:
        raise ValueError("run_started_at must be a parseable ISO timestamp")
    systems = {system.strip().upper() for system in source_systems}
    valid: list[RawRow] = []
    rejects: list[RawRow] = []
    for row in rows:
        reason = None
        if any(not (row.fields.get(field) or "").strip() for field in REQUIRED_FIELDS):
            reason = "missing_required"
        elif (row.fields.get("source_system") or "").strip().upper() not in systems:
            reason = "invalid_source_system"
        elif (row.fields.get("email") or "").strip() and normalize_email(row.fields.get("email")) is None:
            reason = "invalid_email"
        else:
            updated = _as_utc(row.fields.get("updated_at", ""))
            if updated is None:
                reason = "invalid_timestamp"
            elif updated > started + timedelta(hours=tolerance_hours):
                reason = "future_timestamp"
        if reason:
            row.reason_code = reason
            rejects.append(row)
        else:
            compute_keys(row)
            valid.append(row)

    # Select duplicate-key winners only among rows that have passed prior rules.
    grouped: dict[tuple[str, str], list[RawRow]] = defaultdict(list)
    for row in valid:
        timestamp = normalize_timestamp(row.fields.get("updated_at"))
        grouped[(row.source_record_id or "", timestamp or "")].append(row)
    duplicate_victims: set[int] = set()
    for group in grouped.values():
        hashes = {row.row_hash for row in group}
        if len(hashes) > 1:
            winner_hash = min(value for value in hashes if value is not None)
            duplicate_victims.update(id(row) for row in group if row.row_hash != winner_hash)
    kept: list[RawRow] = []
    for row in valid:
        if id(row) in duplicate_victims:
            row.reason_code = "duplicate_key"
            rejects.append(row)
        else:
            kept.append(row)
    rejects.sort(key=lambda row: (row.source_file, row.source_row_number))
    kept.sort(key=lambda row: (row.source_file, row.source_row_number))
    return kept, rejects
