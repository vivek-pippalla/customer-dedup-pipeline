"""Ground-truth evaluation for pre-clustering match decisions."""

import csv
import logging
import sqlite3
from collections import defaultdict
from dataclasses import asdict
from itertools import combinations
from pathlib import Path
from typing import Mapping

from dedup.blocking import block_keys, build_blocks
from dedup.classify import ClassifiedPair, classify_all
from dedup.ids import pair_id
from dedup.pipeline import current_versions


LOGGER = logging.getLogger(__name__)


def pairwise_metrics(
    true_pairs: set[tuple[str, str]], predicted_pairs: set[tuple[str, str]],
) -> dict[str, float | int]:
    """Compute standard pairwise precision, recall and F1 from pair sets."""
    true_positive = len(true_pairs & predicted_pairs)
    precision = true_positive / len(predicted_pairs) if predicted_pairs else 0.0
    recall = true_positive / len(true_pairs) if true_pairs else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"true_positive": true_positive, "precision": precision, "recall": recall, "f1": f1}


def missed_pair_category(
    pair: tuple[str, str], candidate_pairs: set[tuple[str, str]], classified: Mapping[tuple[str, str], ClassifiedPair],
    records_by_id: Mapping[str, Mapping[str, object]], capped_keys: set[tuple[str, str]],
) -> tuple[str, str | None]:
    """Explain an unmerged truth pair as scored, uncapped-blocked or unblocked."""
    canonical_pair = tuple(sorted(pair))
    if canonical_pair in candidate_pairs:
        item = classified[canonical_pair]
        return "scored_non_match", item.result.reason_code
    shared = set(block_keys(records_by_id[canonical_pair[0]])) & set(block_keys(records_by_id[canonical_pair[1]]))
    if not shared:
        return "not_blocked", None
    if shared.issubset(capped_keys):
        return "lost_to_cap", None
    return "not_blocked", None


def _read_truth(path: str | Path) -> list[dict[str, str]]:
    """Read generator ground truth from CSV."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def _truth_pairs(rows: list[dict[str, str]], existing_ids: set[str]) -> set[tuple[str, str]]:
    """Build true entity pairs using only valid rows already ingested."""
    entities: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        source_id = (row.get("source_record_id") or "").strip()
        entity = (row.get("true_entity_id") or "").strip()
        if row.get("is_invalid", "").strip().lower() in {"1", "true", "yes"}:
            continue
        if source_id and entity and source_id in existing_ids:
            entities[entity].add(source_id)
    pairs: set[tuple[str, str]] = set()
    for members in entities.values():
        pairs.update(combinations(sorted(members), 2))
    return pairs


def _reject_agreement(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> dict[str, object]:
    """Compare invalid truth labels with persisted row-level rejects."""
    stored = {
        (str(row["source_file"]), int(row["source_row_number"])): str(row["reason_code"])
        for row in conn.execute("SELECT source_file, source_row_number, reason_code FROM rejects")
        if row["source_file"] is not None and row["source_row_number"] is not None
    }
    invalid_rows = [row for row in rows if row.get("is_invalid", "").strip().lower() in {"1", "true", "yes"}]
    matched = 0
    for row in invalid_rows:
        key = ((row.get("source_file") or ""), int(row.get("row_number") or 0))
        expected = (row.get("expected_reject_reason") or "").strip()
        if key in stored and (not expected or expected == stored[key]):
            matched += 1
    return {"invalid_truth_rows": len(invalid_rows), "matched_rejects": matched,
            "agreement": matched / len(invalid_rows) if invalid_rows else 1.0}


def _feature_summary(pair: ClassifiedPair) -> dict[str, object]:
    """Serialize score fields for false-positive inspection."""
    return {**asdict(pair.features), "reason_code": pair.result.reason_code}


def evaluate_database(
    conn: sqlite3.Connection, truth_path: str | Path, config: Mapping[str, object],
) -> dict[str, object]:
    """Evaluate auto-merge pairs, review cases, blocking recall and rejects."""
    truth_rows = _read_truth(truth_path)
    records = current_versions(conn)
    record_ids = {str(record["source_record_id"]) for record in records}
    records_by_id = {str(record["source_record_id"]): record for record in records}
    truth = _truth_pairs(truth_rows, record_ids)
    block_config = config.get("blocking", {})
    block_cap = int(block_config.get("block_cap", 200)) if isinstance(block_config, Mapping) else 200
    candidate_pairs, blocking_stats = build_blocks(records, block_cap)
    classified = classify_all(records, candidate_pairs, config)
    by_pair = {tuple(sorted((item.source_record_id_a, item.source_record_id_b))): item for item in classified}
    auto_pairs = {pair for pair, item in by_pair.items() if item.result.decision == "auto_merge"}
    review_pairs = {pair for pair, item in by_pair.items() if item.result.decision == "review"}
    candidate_set = set(candidate_pairs)
    metrics = pairwise_metrics(truth, auto_pairs)
    true_auto = truth & auto_pairs
    true_review = truth & review_pairs
    missed = truth - auto_pairs - review_pairs

    key_members: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in records:
        identifier = str(record["source_record_id"])
        for key in block_keys(record):
            key_members[key].add(identifier)
    capped_keys = {key for key, members in key_members.items() if len(members) > block_cap}
    misses = {"not_blocked": [], "lost_to_cap": [], "scored_non_match": []}
    for pair in sorted(missed):
        category, reason = missed_pair_category(pair, candidate_set, by_pair, records_by_id, capped_keys)
        misses[category].append({"pair": pair, "reason_code": reason} if reason else pair)

    false_auto = sorted(auto_pairs - truth)
    precision = float(metrics["precision"])
    recall = float(metrics["recall"])
    f1 = float(metrics["f1"])
    blocking_recall = len(truth & candidate_set) / len(truth) if truth else 0.0
    return {
        "label": "auto_merge pairs only (pre-clustering)",
        "valid_source_records": len(record_ids),
        "true_duplicate_pairs": len(truth),
        "auto_merge_pairs": len(auto_pairs),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "blocking_recall": blocking_recall,
        "true_pairs_found": {"auto_merge": len(true_auto), "review": len(true_review), "missed_entirely": len(missed)},
        "review_queue_size": len(review_pairs),
        "miss_breakdown": {key: len(value) for key, value in misses.items()},
        "scored_non_match_details": misses["scored_non_match"],
        "false_auto_merges": [
            {"source_record_id_a": pair[0], "source_record_id_b": pair[1], **_feature_summary(by_pair[pair])}
            for pair in false_auto[:20]
        ],
        "false_auto_merge_count": len(false_auto),
        "ground_truth_invalid_agreement": _reject_agreement(conn, truth_rows),
        "blocking_stats": asdict(blocking_stats),
    }
