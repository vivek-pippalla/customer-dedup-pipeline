"""Coverage for pure normalization rules and edge cases."""

from dedup.normalize import (
    canonical_first_name, first_is_initial, normalize_address, normalize_name,
    normalize_dob, normalize_email, normalize_phone, normalize_postcode, normalize_timestamp, soundex,
)


def test_phone_prefixes_and_invalid_length():
    assert normalize_phone("+91 98765-43210") == "9876543210"
    assert normalize_phone("09876543210") == "9876543210"
    assert normalize_phone("123456789") is None


def test_names_accents_titles_comma_initial_and_one_character():
    assert normalize_name("Dr. Zoë, Ms. Anne-Marie") == "anne marie zoe"
    assert normalize_name("J Smith") == "j smith"
    assert normalize_name("Q") == "q"
    # One-character names remain valid normalized names and are flagged as initials.
    assert first_is_initial("q")
    assert first_is_initial("j smith")


def test_nickname_lookup_is_single_step_and_unmapped_is_preserved():
    mapping = {"jon": "john", "johnny": "john", "john": "johnathan"}
    assert canonical_first_name("jon smith", mapping) == "john"
    assert canonical_first_name("johnny smith", mapping) == "john"
    assert canonical_first_name("jonathan smith", mapping) == "jonathan"
    assert canonical_first_name("unknown smith", mapping) == "unknown"


def test_address_postcode_timestamp_and_soundex():
    assert normalize_address("12 St. Rd., Apt #3") == "12 street road apartment 3"
    assert normalize_postcode("380-001") == "380001"
    assert normalize_postcode("12345") is None
    assert normalize_timestamp("2025-01-02T03:04:05+05:30") == "2025-01-01T21:34:05Z"
    assert normalize_timestamp("2025-01-02T03:04:05") == "2025-01-02T03:04:05Z"
    assert soundex("Robert") == "R163"


def test_email_and_dob_cleanup_preserve_valid_values_and_null_invalid_values():
    assert normalize_email("  Jane+tag.Name@Example.test ") == "jane+tag.name@example.test"
    assert normalize_email("not-an-email") is None
    assert normalize_dob("2000-02-29") == "2000-02-29"
    assert normalize_dob("2001-02-29") is None

