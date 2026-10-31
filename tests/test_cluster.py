"""Union-find clustering and transitive-conflict behavior."""

from dedup.cluster import build_clusters, check_clusters


def test_chain_forms_one_cluster_and_root_is_smallest_identifier():
    assert build_clusters(["c", "b", "a", "d"], [("b", "c"), ("b", "a")]) == [("a", "b", "c"), ("d",)]


def test_conflicting_three_member_chain_splits_and_demotes_all_pairs():
    records = {
        "a": {"dob_norm": "2000-01-01", "first_name_canon": "jane", "first_is_initial": False},
        "b": {"dob_norm": "2000-01-01", "first_name_canon": "jane", "first_is_initial": False},
        "c": {"dob_norm": "2001-01-01", "first_name_canon": "jane", "first_is_initial": False},
    }
    clusters = build_clusters(["a", "b", "c"], [("a", "b"), ("b", "c")])
    final, demoted = check_clusters(clusters, records)
    assert final == [("a",), ("b",), ("c",)]
    assert demoted == [("a", "b"), ("a", "c"), ("b", "c")]


def test_all_pairs_check_detects_shared_first_name_conflict_and_is_order_independent():
    records = {
        "a": {"first_name_canon": "jane", "first_is_initial": False},
        "b": {"first_name_canon": "jane", "first_is_initial": False},
        "c": {"first_name_canon": "mary", "first_is_initial": False},
    }
    baseline = check_clusters([("a", "b", "c")], records)
    shuffled = check_clusters([("c", "a", "b")], records)
    assert baseline == shuffled
    assert len(baseline[0]) == 3
    assert len(baseline[1]) == 3


def test_initial_only_first_name_does_not_trigger_shared_style_conflict():
    records = {identifier: {"first_name_canon": "j", "first_is_initial": True} for identifier in "abc"}
    assert check_clusters([("a", "b", "c")], records) == ([ ("a", "b", "c") ], [])

