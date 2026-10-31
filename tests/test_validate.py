"""Validation rules, priority, and row-order invariance."""

from dedup.ingest import RawRow
from dedup.validate import validate_rows

AS_OF = "2025-01-01T00:00:00Z"


def make_row(**changes):
    fields = dict(source_system="CRM", source_native_id="x", full_name="Jane Doe", email="jane@example.test",
                  phone="", address="", postcode="", dob="", updated_at=AS_OF)
    fields.update(changes)
    line = ",".join(fields.values())
    return RawRow("input.csv", 1, line, fields)


def test_first_reason_codes_and_priority():
    rows = [make_row(source_system="", email="bad"), make_row(source_system="BOGUS"),
            make_row(email="bad"), make_row(updated_at="nope"),
            make_row(updated_at="2025-01-03T00:00:00Z")]
    valid, rejects = validate_rows(rows, AS_OF, ["CRM"], 24)
    assert not valid
    assert [row.reason_code for row in rejects] == ["missing_required", "invalid_source_system",
                                                       "invalid_email", "invalid_timestamp", "future_timestamp"]


def test_future_inside_tolerance_is_accepted():
    valid, rejects = validate_rows([make_row(updated_at="2025-01-02T00:00:00Z")], AS_OF, ["CRM"], 24)
    assert len(valid) == 1 and not rejects


def test_duplicate_key_winner_does_not_depend_on_input_order():
    candidates = [make_row(full_name=name, source_native_id="same") for name in ("Zulu Doe", "Alice Doe", "Maya Doe")]
    outcomes = []
    for ordered in (candidates, list(reversed(candidates))):
        valid, rejects = validate_rows(ordered, AS_OF, ["CRM"], 24)
        outcomes.append((valid[0].row_hash, {row.row_hash for row in rejects}))
        assert len(valid) == 1
        assert all(row.reason_code == "duplicate_key" for row in rejects)
    assert outcomes[0] == outcomes[1]

