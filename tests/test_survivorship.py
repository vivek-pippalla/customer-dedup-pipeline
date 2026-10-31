"""Golden field selection, deterministic fallback and lineage."""

from dedup.db import connect, init_schema
from dedup.config import load_config
from dedup.ingest import CSV_COLUMNS
from dedup.pipeline import current_versions
from dedup.runlog import start_run
from dedup.db import transaction
from dedup.ingest import RawRow, compute_keys, insert_versions
from dedup.survivorship import build_golden

PRIORITY = {"CRM": 1, "WEB": 2, "IMPORT": 3}


def rec(identifier, **overrides):
    row = {"source_record_id": identifier, "version_id": f"v-{identifier}", "source_system": "CRM",
           "full_name": "John Smith", "name_norm": "john smith", "first_name_canon": "john",
           "first_is_initial": 0, "last_name_norm": "smith", "email": "john@example.test",
           "phone": "9876543210", "address": "1 Main Road, Ahmedabad", "postcode": "380001",
           "dob": "2000-01-01", "dob_norm": "2000-01-01", "updated_at_utc": "2025-01-01T00:00:00Z"}
    row.update(overrides)
    return row


def golden(*records, tiers=None):
    return build_golden([row["source_record_id"] for row in records],
                        {row["source_record_id"]: row for row in records}, PRIORITY, tiers)


def rules_by_field(result):
    return {item.field_name: item for item in result.lineage}


def test_name_prefers_non_nickname_then_tokens_then_length():
    result = golden(rec("a", full_name="Jon Smith", name_norm="jon smith", first_name_canon="john"),
                    rec("b", full_name="John Smith", name_norm="john smith", first_name_canon="john"))
    assert result.full_name == "John Smith"
    assert rules_by_field(result)["full_name"].rule_applied == "non_nickname_first_name"

    result = golden(rec("a", full_name="John A Smith", name_norm="john a smith"),
                    rec("b", full_name="John Smith", name_norm="john smith"))
    assert result.full_name == "John A Smith"
    assert rules_by_field(result)["full_name"].rule_applied == "most_tokens"

    result = golden(rec("a", full_name="Annie Li", name_norm="annie li"),
                    rec("b", full_name="Ann Li", name_norm="ann li"))
    assert result.full_name == "Annie Li"
    assert rules_by_field(result)["full_name"].rule_applied == "longest_name"


def test_email_uses_priority_then_recency_then_smallest_id():
    result = golden(rec("a", email="a@example.test", source_system="WEB", updated_at_utc="2025-02-01T00:00:00Z"),
                    rec("b", email="b@example.test", source_system="CRM", updated_at_utc="2024-01-01T00:00:00Z"))
    assert result.email == "b@example.test"
    assert rules_by_field(result)["email"].rule_applied == "source_priority"
    result = golden(rec("a", email="a@example.test", updated_at_utc="2024-01-01T00:00:00Z"),
                    rec("b", email="b@example.test", updated_at_utc="2025-01-01T00:00:00Z"))
    assert result.email == "b@example.test"
    assert rules_by_field(result)["email"].rule_applied == "latest_updated_at"
    result = golden(rec("b", email="b@example.test"), rec("a", email="a@example.test"))
    assert result.email == "a@example.test"
    assert rules_by_field(result)["email"].rule_applied == "tie_break_smallest_id"


def test_phone_recency_beats_priority_and_priority_breaks_recency_tie():
    result = golden(rec("a", phone="1111111111", source_system="CRM", updated_at_utc="2024-01-01T00:00:00Z"),
                    rec("b", phone="2222222222", source_system="WEB", updated_at_utc="2025-01-01T00:00:00Z"))
    assert result.phone == "2222222222"
    assert rules_by_field(result)["phone"].rule_applied == "latest_updated_at"
    result = golden(rec("a", phone="1111111111", source_system="WEB"), rec("b", phone="2222222222", source_system="CRM"))
    assert result.phone == "2222222222"
    assert rules_by_field(result)["phone"].rule_applied == "source_priority"


def test_address_completeness_then_recency_and_postcode_follows_address_winner():
    result = golden(rec("a", address="1 Main Road", postcode="111111", updated_at_utc="2025-01-01T00:00:00Z"),
                    rec("b", address="1 Main Road, Apt 2, Ahmedabad", postcode="222222", updated_at_utc="2024-01-01T00:00:00Z"))
    rules = rules_by_field(result)
    assert result.address == "1 Main Road, Apt 2, Ahmedabad"
    assert rules["address"].rule_applied == "most_complete_address"
    assert result.postcode == "222222"
    assert rules["postcode"].rule_applied == "follows_address_winner"
    result = golden(rec("a", address="one, city", updated_at_utc="2024-01-01T00:00:00Z"),
                    rec("b", address="two, city", updated_at_utc="2025-01-01T00:00:00Z"))
    assert result.address == "two, city"
    assert rules_by_field(result)["address"].rule_applied == "latest_updated_at"


def test_postcode_fallback_and_dob_majority_then_priority_fallback():
    result = golden(rec("a", address="A, B, C", postcode="", source_system="CRM"),
                    rec("b", address="B", postcode="111111", source_system="WEB"),
                    rec("c", address="C", postcode="222222", source_system="IMPORT"))
    assert result.postcode == "111111"
    assert rules_by_field(result)["postcode"].rule_applied == "source_priority"
    result = golden(rec("a", dob="2000-01-01", dob_norm="2000-01-01", source_system="WEB"),
                    rec("b", dob="2000-01-01", dob_norm="2000-01-01", source_system="IMPORT"),
                    rec("c", dob="2001-01-01", dob_norm="2001-01-01", source_system="CRM"))
    assert result.dob == "2000-01-01"
    assert rules_by_field(result)["dob"].rule_applied == "majority_value"
    result = golden(rec("a", dob="2000-01-01", dob_norm="2000-01-01", source_system="WEB"),
                    rec("b", dob="2001-01-01", dob_norm="2001-01-01", source_system="CRM"))
    assert result.dob == "2001-01-01"
    assert rules_by_field(result)["dob"].rule_applied == "source_priority"


def test_no_value_golden_id_lineage_and_match_tiers():
    result = golden(rec("z", full_name="", name_norm="", email="bad", phone="bad", address="", postcode="bad", dob_norm=""))
    rules = rules_by_field(result)
    assert result.golden_id == "g_" + __import__("hashlib").sha1(b"z").hexdigest()[:16]
    assert result.match_tier == "single"
    for field in ("full_name", "email", "phone", "address", "postcode", "dob"):
        assert rules[field].value is None and rules[field].rule_applied == "no_value"
    merged = golden(rec("a"), rec("b"), tiers=["exact"])
    assert merged.match_tier == "exact"
    assert all(line.source_record_id in {"a", "b"} for line in merged.lineage if line.source_record_id)


def test_current_version_chooses_newest_timestamp_when_older_version_arrives_later():
    conn = connect(":memory:")
    try:
        init_schema(conn)
        first_run = start_run(conn, "run_newer", started_at="2025-01-01T00:00:00Z")
        newer = RawRow("batch.csv", 1, "newer", dict(zip(CSV_COLUMNS, ["CRM", "same", "Newest Name", "new@example.test", "9876543210", "1 Main Rd", "123456", "", "2025-01-01T00:00:00Z"])))
        compute_keys(newer)
        with transaction(conn):
            insert_versions(conn, [newer], first_run)
            conn.execute("INSERT INTO clean_customers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (newer.version_id, newer.source_record_id, "new@example.test", "9876543210", "newest name", "newest", 0,
                          "name", "1 main road", "123456", "2025-01-01T00:00:00Z", None, "N500"))
        later_run = start_run(conn, "run_late", started_at="2025-02-01T00:00:00Z")
        older = RawRow("late.csv", 1, "older", dict(zip(CSV_COLUMNS, ["CRM", "same", "Older Name", "old@example.test", "9876543210", "1 Main Rd", "123456", "", "2024-01-01T00:00:00Z"])))
        compute_keys(older)
        with transaction(conn):
            insert_versions(conn, [older], later_run)
            conn.execute("INSERT INTO clean_customers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (older.version_id, older.source_record_id, "old@example.test", "9876543210", "older name", "older", 0,
                          "name", "1 main road", "123456", "2024-01-01T00:00:00Z", None, "N500"))
        current = current_versions(conn)
        assert len(current) == 1
        assert current[0]["full_name"] == "Newest Name"
        assert build_golden([current[0]["source_record_id"]], {current[0]["source_record_id"]: current[0]}, PRIORITY).full_name == "Newest Name"
    finally:
        conn.close()
