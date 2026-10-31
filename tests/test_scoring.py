"""Scoring, renormalization, and evidence flags."""

from dedup.normalize import normalize_name, canonical_first_name, last_name, first_is_initial
from dedup.scoring import score_pair

WEIGHTS = {"email": 0.30, "phone": 0.25, "name": 0.25, "address": 0.10, "dob": 0.10}


def record(name="Jon Smith", **values):
    normalized = normalize_name(name)
    result = {"email_norm": None, "phone_norm": None, "name_norm": normalized,
              "first_name_canon": canonical_first_name(normalized),
              "first_is_initial": first_is_initial(normalized), "last_name_norm": last_name(normalized),
              "address_norm": None, "dob_norm": None}
    result.update(values)
    return result


def test_email_only_match_score_is_renormalized_and_coverage_is_not():
    pair = score_pair({"email_norm": "a@test.com"}, {"email_norm": "a@test.com"}, WEIGHTS)
    assert pair.email == 1.0
    assert pair.score == 1.0
    assert pair.coverage == 0.30


def test_strong_identifier_positive_and_negative():
    assert score_pair(record(email_norm="a@test.com"), record(email_norm="a@test.com"), WEIGHTS).strong_id
    assert score_pair(record(phone_norm="123"), record(phone_norm="123"), WEIGHTS).strong_id
    same_name_dob = score_pair(record("Jane Doe", dob_norm="2000-01-01"), record("Jane Doe", dob_norm="2000-01-01"), WEIGHTS)
    assert same_name_dob.strong_id
    assert not score_pair(record(email_norm="a@test.com"), record(email_norm="b@test.com"), WEIGHTS).strong_id


def test_dob_conflict_positive_and_negative():
    assert score_pair(record(dob_norm="2000-01-01"), record(dob_norm="2001-01-01"), WEIGHTS).dob_conflict
    assert not score_pair(record(dob_norm="2000-01-01"), record(dob_norm="2000-01-01"), WEIGHTS).dob_conflict
    assert not score_pair(record(), record(dob_norm="2000-01-01"), WEIGHTS).dob_conflict


def test_shared_conflict_requires_non_initial_different_first_names():
    a = record("Jane Doe", email_norm="a@test.com")
    b = record("Mary Doe", email_norm="a@test.com")
    assert score_pair(a, b, WEIGHTS).shared_conflict
    assert not score_pair(a, record("J Doe", email_norm="a@test.com"), WEIGHTS).shared_conflict
    assert not score_pair(a, record("Jane Doe", email_norm="b@test.com"), WEIGHTS).shared_conflict


def test_names_compatible_nickname_last_name_and_missing_cases():
    # Config nickname map canonicalizes Jon, Johnny and Jonathan to John.
    for candidate in ("John Smith", "Johnny Smith", "Jonathan Smith"):
        assert score_pair(record("Jon Smith", email_norm="same"), record(candidate, email_norm="same"), WEIGHTS).names_compatible
    assert not score_pair(record("J Smith"), record("John Smith"), WEIGHTS).names_compatible
    assert not score_pair(record("Jane"), record("Jane"), WEIGHTS).names_compatible
    assert not score_pair(record("Jane Smith"), record("Mary Smith"), WEIGHTS).names_compatible

