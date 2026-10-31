"""Decision-table rule and exact/probable tier tests."""

from dataclasses import replace

from dedup.classify import classify_pair
from dedup.normalize import normalize_name, canonical_first_name, last_name, first_is_initial
from dedup.scoring import PairFeatures, score_pair

THRESHOLDS = {"auto": 0.90, "review": 0.65, "min_coverage": 0.50}


def feature(**changes):
    values = dict(email=None, phone=None, name=None, address=None, dob=None, score=0.5, coverage=0.7,
                  strong_id=False, dob_conflict=False, shared_conflict=False, names_compatible=False)
    values.update(changes)
    return PairFeatures(**values)


def test_decision_table_rows_one_through_eight():
    cases = [
        (feature(strong_id=True, dob_conflict=True), "review", "dob_conflict"),
        (feature(dob_conflict=True), "non_match", "dob_conflict"),
        (feature(shared_conflict=True), "review", "shared_identifier_conflict"),
        (feature(score=0.65), "review", "name_only"),
        (feature(score=0.64), "non_match", "low_score"),
        (feature(strong_id=True, names_compatible=True, score=0.90, coverage=0.50,
                 email_equal=True, name_equal=True), "auto_merge", "auto_merge"),
        (feature(strong_id=True), "review", "shared_identifier_only"),
        (feature(strong_id=True, names_compatible=True, score=0.89), "review", "score_below_auto"),
    ]
    for features, decision, reason in cases:
        result = classify_pair(features, THRESHOLDS)
        assert (result.decision, result.reason_code) == (decision, reason)


def _record(name, **overrides):
    normalized = normalize_name(name)
    result = {"email_norm": None, "phone_norm": None, "name_norm": normalized,
              "first_name_canon": canonical_first_name(normalized),
              "first_is_initial": first_is_initial(normalized), "last_name_norm": last_name(normalized),
              "address_norm": None, "postcode_norm": None, "dob_norm": None}
    result.update(overrides)
    return result


def test_examples_family_conflict_nickname_phone_and_dob_conflict():
    a = _record("John Doe", email_norm="family@example.test")
    b = _record("Mary Doe", email_norm="family@example.test")
    result = classify_pair(score_pair(a, b, {"email": 0.3, "phone": 0.25, "name": 0.25, "address": 0.1, "dob": 0.1}), THRESHOLDS)
    assert (result.decision, result.reason_code) == ("review", "shared_identifier_conflict")

    phone_a = _record("Jon Smith", phone_norm="1234567890")
    phone_b = _record("Jonathan Smith", phone_norm="1234567890")
    phone_features = score_pair(phone_a, phone_b, {"email": 0.3, "phone": 0.25, "name": 0.25, "address": 0.1, "dob": 0.1})
    assert classify_pair(phone_features, THRESHOLDS).decision == "auto_merge"

    conflict = score_pair(_record("Jane Doe", email_norm="x@test", dob_norm="2000-01-01"),
                          _record("Jane Doe", email_norm="x@test", dob_norm="2001-01-01"),
                          {"email": 0.3, "phone": 0.25, "name": 0.25, "address": 0.1, "dob": 0.1})
    assert (classify_pair(conflict, THRESHOLDS).decision, classify_pair(conflict, THRESHOLDS).reason_code) == ("review", "dob_conflict")


def test_email_only_different_names_is_review_and_case_whitespace_is_exact():
    weights = {"email": 0.3, "phone": 0.25, "name": 0.25, "address": 0.1, "dob": 0.1}
    different = score_pair(_record("Jon Doe", email_norm="shared@test"),
                           _record("Johnny Roe", email_norm="shared@test"), weights)
    assert (classify_pair(different, THRESHOLDS).decision, classify_pair(different, THRESHOLDS).reason_code) == ("review", "shared_identifier_only")
    equal = score_pair(_record("Jane Doe", email_norm="jane@example.test"),
                       _record(" jane   doe ", email_norm=" jane@example.test "), weights)
    assert classify_pair(equal, THRESHOLDS).match_tier == "exact"


def test_similar_names_without_strong_identifier_do_not_auto_merge():
    features = feature(score=0.70)
    assert (classify_pair(features, THRESHOLDS).decision, classify_pair(features, THRESHOLDS).reason_code) == ("review", "name_only")
    assert classify_pair(replace(features, score=0.2), THRESHOLDS).reason_code == "low_score"

