"""Evaluation metrics and block-cap miss attribution."""

from dedup.evaluate import missed_pair_category, pairwise_metrics


def test_pairwise_precision_recall_and_f1_on_hand_built_truth():
    truth = {("a", "b"), ("c", "d")}
    predicted = {("a", "b"), ("a", "c")}
    assert pairwise_metrics(truth, predicted) == {"true_positive": 1, "precision": 0.5, "recall": 0.5, "f1": 0.5}


def test_pair_sharing_only_capped_key_is_lost_to_cap():
    pair = ("a", "b")
    records = {"a": {"source_record_id": "a", "email_norm": "shared@test"},
               "b": {"source_record_id": "b", "email_norm": "shared@test"}}
    assert missed_pair_category(pair, set(), {}, records, {("email", "shared@test")}) == ("lost_to_cap", None)
    assert missed_pair_category(pair, set(), {}, records, set()) == ("not_blocked", None)
