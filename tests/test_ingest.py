"""Tests for CSV reading, key calculation, and raw-version insertion."""

import sqlite3
from pathlib import Path

from dedup.db import connect, init_schema, transaction
from dedup.ids import ROW_HASH_FIELDS, normalize_source_system, row_hash, source_record_id, version_id
from dedup.ingest import CSV_COLUMNS, compute_keys, insert_versions, read_batch
from dedup.runlog import start_run


def _write_csv(path: Path, text: str) -> Path:
    """Write hand-authored CSV text without newline translation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        output.write(text)
    return path


def _header(columns: tuple[str, ...] = CSV_COLUMNS) -> str:
    """Return a CSV header line."""
    return ",".join(columns) + "\n"


def _raw_record(name: str = "Ada Lovelace", email: str = "ada@example.test") -> str:
    """Build one complete synthetic raw record."""
    return f"CRM,C-1,{name},{email},9876543210,1 Main Road,123456,1815-12-10,2025-01-02T03:04:05Z\n"


def test_read_batch_happy_path_and_source_row_numbers(tmp_path: Path) -> None:
    """A valid CSV returns exact source fields and one-based data row numbers."""
    path = _write_csv(tmp_path / "customers.csv", _header() + _raw_record() + _raw_record("Grace Hopper"))
    batch = read_batch(path)
    assert batch.file_error is None
    assert batch.is_empty is False
    assert batch.warnings == []
    assert batch.structural_rejects == []
    assert [row.source_file for row in batch.rows] == ["customers.csv", "customers.csv"]
    assert [row.source_row_number for row in batch.rows] == [1, 2]
    assert batch.rows[0].fields["full_name"] == "Ada Lovelace"


def test_header_only_and_zero_byte_files_are_empty(tmp_path: Path) -> None:
    """A header-only file and a zero-byte file are represented as empty batches."""
    header_only = read_batch(_write_csv(tmp_path / "header.csv", _header()))
    zero_byte = read_batch(_write_csv(tmp_path / "empty.csv", ""))
    for batch in (header_only, zero_byte):
        assert batch.file_error is None
        assert batch.is_empty is True
        assert batch.rows == []
        assert batch.structural_rejects == []


def test_missing_required_header_returns_named_file_error(tmp_path: Path) -> None:
    """A renamed required header is reported as a file-level schema error."""
    columns = tuple("customer_name" if name == "full_name" else name for name in CSV_COLUMNS)
    batch = read_batch(_write_csv(tmp_path / "missing.csv", _header(columns)))
    assert batch.file_error is not None
    assert "full_name" in batch.file_error
    assert batch.rows == []


def test_extra_header_column_warns_but_is_ignored(tmp_path: Path) -> None:
    """Extra input columns produce a warning and do not hide valid rows."""
    columns = (*CSV_COLUMNS, "unused_note")
    values = _raw_record().rstrip("\n") + ",ignored\n"
    batch = read_batch(_write_csv(tmp_path / "extra.csv", _header(columns) + values))
    assert batch.file_error is None
    assert len(batch.warnings) == 1
    assert "unused_note" in batch.warnings[0]
    assert len(batch.rows) == 1
    assert "unused_note" not in batch.rows[0].fields


def test_wrong_column_count_is_structural_reject_and_read_continues(tmp_path: Path) -> None:
    """A wrong-width row is separated as malformed while later rows still load."""
    malformed = "CRM,C-2,Too Few Fields\n"
    path = _write_csv(tmp_path / "malformed.csv", _header() + malformed + _raw_record())
    batch = read_batch(path)
    assert len(batch.rows) == 1
    assert batch.rows[0].source_row_number == 2
    assert len(batch.structural_rejects) == 1
    reject = batch.structural_rejects[0]
    assert reject.reason_code == "malformed_row"
    assert reject.source_row_number == 1
    assert reject.raw_line == malformed
    assert reject.fields["source_native_id"] == "C-2"


def test_quoted_commas_and_embedded_newlines_are_parsed_and_preserved(tmp_path: Path) -> None:
    """CSV quoting preserves commas, embedded newlines, and raw logical text."""
    fields = 'CRM,C-1,"Doe, Jane",jane@example.test,9876543210,"Line one\nLine two",123456,,2025-01-02T03:04:05Z\n'
    batch = read_batch(_write_csv(tmp_path / "quoted.csv", _header() + fields))
    assert len(batch.rows) == 1
    row = batch.rows[0]
    assert row.source_row_number == 1
    assert row.fields["full_name"] == "Doe, Jane"
    assert row.fields["address"] == "Line one\nLine two"
    assert row.raw_line == fields


def test_non_ascii_names_survive_utf8_read(tmp_path: Path) -> None:
    """Non-ASCII text is decoded and retained without alteration."""
    batch = read_batch(_write_csv(tmp_path / "unicode.csv", _header() + _raw_record("Zoë Nguyễn")))
    assert batch.rows[0].fields["full_name"] == "Zoë Nguyễn"


def test_csv_parse_error_becomes_structural_reject(tmp_path: Path) -> None:
    """An unparseable CSV record is returned as malformed instead of raising."""
    bad = 'CRM,C-1,"unclosed quote\n'
    batch = read_batch(_write_csv(tmp_path / "bad_quote.csv", _header() + bad))
    assert batch.file_error is None
    assert len(batch.structural_rejects) == 1
    assert batch.structural_rejects[0].reason_code == "malformed_row"
    assert batch.structural_rejects[0].raw_line == bad


def test_compute_keys_uses_raw_content_and_canonical_source_key(tmp_path: Path) -> None:
    """Key calculation normalizes source identity but hashes original field values."""
    raw = _raw_record("  ADA LOVELACE  ", "ADA@EXAMPLE.TEST")
    row = read_batch(_write_csv(tmp_path / "keys.csv", _header() + raw)).rows[0]
    compute_keys(row)
    expected_source = source_record_id("CRM", "C-1")
    expected_hash = row_hash(*(row.fields[column] for column in ROW_HASH_FIELDS))
    assert row.source_record_id == expected_source
    assert row.row_hash == expected_hash
    assert row.version_id == version_id(expected_source, expected_hash)
    assert row.fields["full_name"] == "  ADA LOVELACE  "


def test_insert_versions_is_idempotent_and_counts_conflicts(tmp_path: Path) -> None:
    """The first insert stores each version and redelivery counts as duplicate events."""
    path = _write_csv(tmp_path / "insert.csv", _header() + _raw_record() + _raw_record("Grace Hopper"))
    rows = [compute_keys(row) for row in read_batch(path).rows]
    conn = connect(":memory:")
    try:
        init_schema(conn)
        run_id = start_run(conn, "run_ingest", started_at="2025-01-01T00:00:00Z")
        with transaction(conn):
            assert insert_versions(conn, rows, run_id) == (2, 0)
        with transaction(conn):
            assert insert_versions(conn, rows, run_id) == (0, 2)
        assert conn.execute("SELECT COUNT(*) FROM raw_customer_records").fetchone()[0] == 2
    finally:
        conn.close()


def test_same_source_record_with_changed_content_inserts_new_version(tmp_path: Path) -> None:
    """Changed original content keeps the source ID and creates a new version ID."""
    path = _write_csv(tmp_path / "updates.csv", _header() + _raw_record() + _raw_record(email="ada.new@example.test"))
    rows = [compute_keys(row) for row in read_batch(path).rows]
    assert rows[0].source_record_id == rows[1].source_record_id
    assert rows[0].version_id != rows[1].version_id
    conn = connect(":memory:")
    try:
        init_schema(conn)
        run_id = start_run(conn, "run_updates", started_at="2025-01-01T00:00:00Z")
        with transaction(conn):
            assert insert_versions(conn, rows, run_id) == (2, 0)
    finally:
        conn.close()


def test_insert_preserves_original_values_and_links_canonical_source(tmp_path: Path) -> None:
    """Raw values remain exact while the separate source key satisfies its FK."""
    raw = " crm , C-1 ,  ADA LOVELACE  ,ADA@EXAMPLE.TEST,9876543210,  1 Main Road ,123456,,2025-01-02T03:04:05Z\n"
    row = compute_keys(read_batch(_write_csv(tmp_path / "preserve.csv", _header() + raw)).rows[0])
    conn = connect(":memory:")
    try:
        init_schema(conn)
        run_id = start_run(conn, "run_preserve", started_at="2025-01-01T00:00:00Z")
        with transaction(conn):
            assert insert_versions(conn, [row], run_id) == (1, 0)
        stored = conn.execute(
            "SELECT source_system, source_system_key, source_native_id, full_name, email, address "
            "FROM raw_customer_records WHERE version_id=?",
            (row.version_id,),
        ).fetchone()
        assert tuple(stored) == (
            " crm ", "CRM", " C-1 ", "  ADA LOVELACE  ", "ADA@EXAMPLE.TEST", "  1 Main Road "
        )
        assert normalize_source_system(stored["source_system"]) == stored["source_system_key"]
    finally:
        conn.close()


def test_insert_versions_requires_caller_transaction(tmp_path: Path) -> None:
    """Raw insertion refuses to run outside an explicit transaction."""
    row = compute_keys(read_batch(_write_csv(tmp_path / "one.csv", _header() + _raw_record())).rows[0])
    conn = connect(":memory:")
    try:
        init_schema(conn)
        run_id = start_run(conn, "run_tx_required", started_at="2025-01-01T00:00:00Z")
        try:
            insert_versions(conn, [row], run_id)
        except RuntimeError as error:
            assert "caller-provided transaction" in str(error)
        else:
            raise AssertionError("insert_versions accepted a call without an active transaction")
    finally:
        conn.close()
