"""Tests for deterministic identifiers."""

from datetime import datetime, timedelta, timezone

from dedup.ids import (
    golden_id,
    new_run_id,
    pair_id,
    row_hash,
    source_record_id,
    version_id,
)


def test_ids_have_fixed_golden_values() -> None:
    """Each data ID follows its fixed SHA-1 input and truncation format."""
    source_id = source_record_id(" crm ", " C-1 ")
    content_hash = row_hash(
        "CRM", "C-1", "Ada Lovelace", "ada@example.test", "+1", "1 Main Rd",
        "123456", "1815-12-10", "2025-01-02T03:04:05Z",
    )
    assert source_id == "5579740249b26fb7"
    assert content_hash == "d29b3655a4534fc9"
    assert version_id(source_id, content_hash) == "e3c529f895174958"
    assert golden_id(["b" * 16, "a" * 16]) == "g_1ee720238312371f"
    assert pair_id("a" * 16, "b" * 16) == "1ee720238312371f"
    assert new_run_id(
        clock=lambda: datetime(2025, 1, 2, 8, 34, 5, tzinfo=timezone(timedelta(hours=5, minutes=30))),
        suffix="aBcD",
    ) == "run_20250102T030405Z_abcd"


def test_pair_id_is_symmetric_and_source_id_uses_normalized_system() -> None:
    """Pair order and source-system case or whitespace do not affect the ID."""
    assert pair_id("record-b", "record-a") == pair_id("record-a", "record-b")
    assert source_record_id("crm", "customer-4") == source_record_id(" CRM ", "customer-4")


def test_new_content_changes_version_not_source_identity() -> None:
    """A changed original field creates a new version of the same source record."""
    first_id = source_record_id("WEB", "W-10")
    changed_hash = row_hash(
        "WEB", "W-10", "Sam Example", "sam@example.test", None, None,
        None, None, "2025-02-01T00:00:00Z",
    )
    newer_hash = row_hash(
        "WEB", "W-10", "Sam Example", "sam.new@example.test", None, None,
        None, None, "2025-02-01T00:00:00Z",
    )
    assert first_id == source_record_id("WEB", "W-10")
    assert changed_hash != newer_hash
    assert version_id(first_id, changed_hash) != version_id(first_id, newer_hash)
