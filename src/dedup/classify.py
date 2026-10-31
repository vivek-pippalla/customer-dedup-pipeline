"""Evidence-gated pair classification."""

from dataclasses import dataclass
from typing import Mapping, Sequence

from dedup.scoring import PairFeatures, score_pair


DECISION_TABLE = (
    (1, "dob_conflict and strong_id", "review", "dob_conflict"),
    (2, "dob_conflict and not strong_id", "non_match", "dob_conflict"),
    (3, "shared_conflict", "review", "shared_identifier_conflict"),
    (4, "not strong_id and score >= review", "review", "name_only"),
    (5, "not strong_id", "non_match", "low_score"),
    (6, "strong_id and names_compatible and score >= auto and coverage >= min_coverage", "auto_merge", "auto_merge"),
    (7, "strong_id and (not names_compatible or coverage < min_coverage)", "review", "shared_identifier_only"),
    (8, "strong_id and gates pass and score < auto", "review", "score_below_auto"),
)


@dataclass(frozen=True)
class Decision:
    """Final decision label and its reason and match tier."""
    decision: str
    reason_code: str
    match_tier: str | None


@dataclass(frozen=True)
class ClassifiedPair:
    """A candidate pair with features and its evidence-gate decision."""
    pair_id: str
    source_record_id_a: str
    source_record_id_b: str
    features: PairFeatures
    result: Decision


def classify_pair(features: PairFeatures, thresholds: Mapping[str, float]) -> Decision:
    """Apply the documented decision table in order; first matching row wins."""
    auto = float(thresholds["auto"])
    review = float(thresholds["review"])
    min_coverage = float(thresholds["min_coverage"])
    outcome: tuple[str, str] | None = None
    if features.dob_conflict and features.strong_id:
        outcome = ("review", "dob_conflict")
    elif features.dob_conflict and not features.strong_id:
        outcome = ("non_match", "dob_conflict")
    elif features.shared_conflict:
        outcome = ("review", "shared_identifier_conflict")
    elif not features.strong_id and features.score >= review:
        outcome = ("review", "name_only")
    elif not features.strong_id:
        outcome = ("non_match", "low_score")
    elif features.names_compatible and features.score >= auto and features.coverage >= min_coverage:
        outcome = ("auto_merge", "auto_merge")
    elif not features.names_compatible or features.coverage < min_coverage:
        outcome = ("review", "shared_identifier_only")
    else:
        outcome = ("review", "score_below_auto")
    match_tier = None
    if outcome[0] == "auto_merge":
        match_tier = "exact" if (features.email_equal and features.name_equal and features.phone_exact_for_tier) else "probable"
    return Decision(outcome[0], outcome[1], match_tier)


def classify_all(
    records: Sequence[Mapping[str, object]], pairs: Sequence[tuple[str, str]], config: Mapping[str, object],
) -> list[ClassifiedPair]:
    """Score and classify candidate pairs in deterministic pair-id order."""
    from dedup.ids import pair_id

    by_id = {str(record["source_record_id"]): record for record in records}
    weights = config.get("weights", {})
    thresholds = config.get("thresholds", {})
    if not isinstance(weights, Mapping) or not isinstance(thresholds, Mapping):
        raise ValueError("config must include weights and thresholds tables")
    threshold_values = {key: float(thresholds[key]) for key in ("auto", "review", "min_coverage")}
    last_name_min_jw = float(thresholds.get("last_name_min_jw", 0.90))
    canonical_pairs = sorted({tuple(sorted((str(a), str(b)))) for a, b in pairs})
    output: list[ClassifiedPair] = []
    for record_a, record_b in canonical_pairs:
        if record_a not in by_id or record_b not in by_id:
            continue
        features = score_pair(by_id[record_a], by_id[record_b], weights, last_name_min_jw)
        output.append(ClassifiedPair(
            pair_id(record_a, record_b), record_a, record_b, features,
            classify_pair(features, threshold_values),
        ))
    return sorted(output, key=lambda item: item.pair_id)
