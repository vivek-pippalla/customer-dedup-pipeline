"""Read customer CSV batches and append valid raw versions."""

import csv
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from dedup.ids import ROW_HASH_FIELDS, normalize_source_system, row_hash, source_record_id, version_id


LOGGER = logging.getLogger(__name__)
CSV_COLUMNS = (
    "source_system", "source_native_id", "full_name", "email", "phone",
    "address", "postcode", "dob", "updated_at",
)


@dataclass
class RawRow:
    """One parsed CSV data row and its original source text."""

    source_file: str
    source_row_number: int
    raw_line: str
    fields: dict[str, str]
    reason_code: str | None = None
    source_record_id: str | None = None
    row_hash: str | None = None
    version_id: str | None = None


@dataclass
class BatchRead:
    """Parsed batch rows, structural rejects, warnings, and file status."""

    file_error: str | None = None
    warnings: list[str] = field(default_factory=list)
    rows: list[RawRow] = field(default_factory=list)
    structural_rejects: list[RawRow] = field(default_factory=list)
    is_empty: bool = False


class _TrackedLines:
    """Track original physical lines consumed for one logical CSV record."""

    def __init__(self, source: TextIO) -> None:
        self._source = iter(source)
        self._lines: list[str] = []

    def __iter__(self) -> "_TrackedLines":
        return self

    def __next__(self) -> str:
        line = next(self._source)
        self._lines.append(line)
        return line

    def begin_record(self) -> None:
        """Start collecting raw text for the next logical CSV record."""
        self._lines.clear()

    @property
    def raw_line(self) -> str:
        """Return original physical line text, including its line endings."""
        return "".join(self._lines)


def _fields_for_row(header: list[str], values: list[str]) -> dict[str, str]:
    """Keep known CSV fields and ignore any extra input columns."""
    return {
        name: values[index]
        for index, name in enumerate(header)
        if name in CSV_COLUMNS and index < len(values)
    }


def read_batch(path: str | Path) -> BatchRead:
    """Read a UTF-8 CSV batch without applying row validation rules."""
    source_path = Path(path)
    result = BatchRead()
    try:
        with source_path.open("r", encoding="utf-8-sig", newline="") as source:
            tracked = _TrackedLines(source)
            reader = csv.reader(tracked, strict=True)
            tracked.begin_record()
            try:
                header = next(reader)
            except StopIteration:
                result.is_empty = True
                return result
            except csv.Error as error:
                result.file_error = f"could not read CSV header: {error}"
                return result

            missing = [column for column in CSV_COLUMNS if column not in header]
            if missing:
                result.file_error = "schema_mismatch: missing required columns: " + ", ".join(missing)
                return result
            extras = sorted(set(header) - set(CSV_COLUMNS))
            if extras:
                warning = "ignored extra columns: " + ", ".join(extras)
                result.warnings.append(warning)
                LOGGER.warning("%s in %s", warning, source_path.name)

            row_number = 0
            while True:
                tracked.begin_record()
                try:
                    values = next(reader)
                except StopIteration:
                    break
                except csv.Error as error:
                    row_number += 1
                    reject = RawRow(
                        source_file=source_path.name,
                        source_row_number=row_number,
                        raw_line=tracked.raw_line,
                        fields={},
                        reason_code="malformed_row",
                    )
                    result.structural_rejects.append(reject)
                    LOGGER.warning("malformed CSV row %s in %s: %s", row_number, source_path.name, error)
                    continue

                row_number += 1
                raw_line = tracked.raw_line
                fields = _fields_for_row(header, values)
                raw_row = RawRow(source_path.name, row_number, raw_line, fields)
                if len(values) != len(header):
                    raw_row.reason_code = "malformed_row"
                    result.structural_rejects.append(raw_row)
                else:
                    result.rows.append(raw_row)
            result.is_empty = row_number == 0
    except (OSError, UnicodeError, csv.Error) as error:
        result.file_error = f"could not read {source_path.name}: {error}"
    return result


def compute_keys(row: RawRow) -> RawRow:
    """Attach deterministic source, content, and version IDs when possible."""
    row.source_record_id = None
    row.row_hash = None
    row.version_id = None
    source_system = row.fields.get("source_system", "")
    source_native_id = row.fields.get("source_native_id", "")
    if not source_system.strip() or not source_native_id.strip():
        return row
    values = [row.fields.get(column, "") for column in ROW_HASH_FIELDS]
    row.source_record_id = source_record_id(source_system, source_native_id)
    row.row_hash = row_hash(*values)
    row.version_id = version_id(row.source_record_id, row.row_hash)
    return row


def insert_versions(
    conn: sqlite3.Connection,
    rows: list[RawRow],
    run_id: str,
) -> tuple[int, int]:
    """Insert computed raw versions within the caller's active transaction."""
    if not conn.in_transaction:
        raise RuntimeError("insert_versions must run inside a caller-provided transaction")
    inserted_count = 0
    duplicate_event_count = 0
    statement = (
        "INSERT INTO raw_customer_records "
        "(version_id, source_record_id, row_hash, source_system, source_system_key, source_native_id, full_name, "
        "email, phone, address, postcode, dob, updated_at, source_file, source_row_number, first_seen_run_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (version_id) DO NOTHING"
    )
    for row in rows:
        if row.version_id is None or row.source_record_id is None or row.row_hash is None:
            compute_keys(row)
        if row.version_id is None or row.source_record_id is None or row.row_hash is None:
            raise ValueError(f"cannot compute source keys for row {row.source_row_number}")
        cursor = conn.execute(
            statement,
            (
                row.version_id,
                row.source_record_id,
                row.row_hash,
                row.fields.get("source_system"),
                normalize_source_system(row.fields["source_system"]),
                row.fields.get("source_native_id"),
                row.fields.get("full_name"),
                row.fields.get("email"),
                row.fields.get("phone"),
                row.fields.get("address"),
                row.fields.get("postcode"),
                row.fields.get("dob"),
                row.fields.get("updated_at"),
                row.source_file,
                row.source_row_number,
                run_id,
            ),
        )
        if cursor.rowcount == 1:
            inserted_count += 1
        else:
            duplicate_event_count += 1
    return inserted_count, duplicate_event_count
