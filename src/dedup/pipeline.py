"""Stage orchestration for customer ingestion and validation."""

import hashlib
import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from dedup.db import transaction
from dedup.classify import ClassifiedPair, classify_all as classify_candidates
from dedup.ingest import BatchRead, RawRow, compute_keys, insert_versions, read_batch
from dedup.normalize import normalize_row
from dedup.validate import validate_rows
from dedup.blocking import BlockingStats, build_blocks
from dedup.cluster import build_clusters, check_clusters
from dedup.classify import Decision
from dedup.survivorship import GoldenRecord, build_golden


LOGGER = logging.getLogger(__name__)
CLEAN_INSERT = (
    "INSERT INTO clean_customers (version_id, source_record_id, email_norm, phone_norm, name_norm, "
    "first_name_canon, first_is_initial, last_name_norm, address_norm, postcode_norm, updated_at_utc, dob_norm, soundex_last) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (version_id) DO NOTHING"
)


def current_versions(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Select one deterministic current clean version per source record."""
    rows = conn.execute(
        "WITH ranked AS ("
        " SELECT c.*, r.row_hash, r.source_system, r.full_name, r.email, r.phone, r.address, r.postcode, r.dob, "
        " ROW_NUMBER() OVER ("
        "  PARTITION BY c.source_record_id ORDER BY c.updated_at_utc DESC, r.row_hash ASC"
        " ) AS version_rank FROM clean_customers c"
        " JOIN raw_customer_records r ON r.version_id = c.version_id"
        ") SELECT * FROM ranked WHERE version_rank = 1 ORDER BY source_record_id"
    ).fetchall()
    return [dict(row) for row in rows]


def classify_all(
    records: Sequence[Mapping[str, object]], pairs: Sequence[tuple[str, str]], config: Mapping[str, object],
) -> list[ClassifiedPair]:
    """Pipeline entry point for deterministic candidate scoring and classification."""
    return classify_candidates(records, pairs, config)


@dataclass(frozen=True)
class ComputeResult:
    """Complete in-memory matching, clustering, and survivorship output."""
    golden_records: tuple[GoldenRecord, ...]
    members: tuple[dict[str, str], ...]
    lineage_rows: tuple[dict[str, object], ...]
    candidate_pairs: tuple[ClassifiedPair, ...]
    review_pairs: tuple[ClassifiedPair, ...]
    clusters: tuple[tuple[str, ...], ...]
    auto_merge_pairs: tuple[tuple[str, str], ...]
    classified_pairs: tuple[ClassifiedPair, ...]
    blocking_stats: BlockingStats
    counts: Mapping[str, int]


def compute_all(conn: sqlite3.Connection, config: Mapping[str, object]) -> ComputeResult:
    """Compute current versions, candidates, decisions, clusters and golden rows in memory."""
    records = current_versions(conn)
    blocking_config = config.get("blocking", {})
    cap = int(blocking_config.get("block_cap", 200)) if isinstance(blocking_config, Mapping) else 200
    pairs, stats = build_blocks(records, cap)
    classified = classify_all(records, pairs, config)
    auto_pairs = sorted({tuple(sorted((pair.source_record_id_a, pair.source_record_id_b)))
                         for pair in classified if pair.result.decision == "auto_merge"})
    by_id = {str(record["source_record_id"]): record for record in records}
    initial_clusters = build_clusters(list(by_id), auto_pairs)
    clusters, demoted = check_clusters(initial_clusters, by_id)

    demoted_scored = classify_all(records, demoted, config) if demoted else []
    merged: dict[tuple[str, str], ClassifiedPair] = {
        tuple(sorted((pair.source_record_id_a, pair.source_record_id_b))): pair for pair in classified
    }
    for pair in demoted_scored:
        key = tuple(sorted((pair.source_record_id_a, pair.source_record_id_b)))
        merged[key] = ClassifiedPair(pair.pair_id, pair.source_record_id_a, pair.source_record_id_b,
                                     pair.features, Decision("review", "transitive_conflict", None))
    all_classified = [merged[key] for key in sorted(merged)]
    candidate_pairs = tuple(pair for pair in all_classified if pair.result.decision in {"auto_merge", "review"})
    review_pairs = tuple(pair for pair in candidate_pairs if pair.result.decision == "review")

    golden_records: list[GoldenRecord] = []
    members: list[dict[str, str]] = []
    lineage_rows: list[dict[str, object]] = []
    edge_tier_by_pair = {
        tuple(sorted((pair.source_record_id_a, pair.source_record_id_b))): pair.result.match_tier
        for pair in classified if pair.result.decision == "auto_merge"
    }
    priority = config.get("source_priority", {})
    if not isinstance(priority, Mapping):
        raise ValueError("config source_priority must be a table")
    for cluster in clusters:
        member_set = set(cluster)
        edge_tiers = [tier or "probable" for pair, tier in edge_tier_by_pair.items()
                      if pair[0] in member_set and pair[1] in member_set]
        golden = build_golden(cluster, by_id, priority, edge_tiers)
        golden_records.append(golden)
        for member in golden.members:
            members.append({"golden_id": golden.golden_id, "source_record_id": member.source_record_id,
                            "version_id": member.version_id})
        for line in golden.lineage:
            lineage_rows.append({"golden_id": golden.golden_id, "field_name": line.field_name,
                                 "value": line.value, "version_id": line.version_id,
                                 "source_record_id": line.source_record_id, "source_system": line.source_system,
                                 "rule_applied": line.rule_applied})
    golden_records.sort(key=lambda record: record.golden_id)
    members.sort(key=lambda row: (row["golden_id"], row["source_record_id"]))
    lineage_rows.sort(key=lambda row: (str(row["golden_id"]), str(row["field_name"])))
    counts = {
        "unique_source_records": len(by_id),
        "golden_records": len(golden_records),
        "merged_away": len(by_id) - len(golden_records),
        "records_in_merged_clusters": sum(len(cluster) for cluster in clusters if len(cluster) >= 2),
        "review_pending": len(review_pairs),
        "records_in_pending_review": len({identifier for pair in review_pairs
                                          for identifier in (pair.source_record_id_a, pair.source_record_id_b)}),
    }
    return ComputeResult(tuple(golden_records), tuple(members), tuple(lineage_rows), candidate_pairs,
                         review_pairs, tuple(clusters), tuple(auto_pairs), tuple(all_classified), stats, counts)


def _config_value(config: Mapping[str, object], section: str, key: str, default: object) -> object:
    table = config.get(section, {})
    return table.get(key, default) if isinstance(table, Mapping) else default


def stage1_ingest(
    conn: sqlite3.Connection, paths: Iterable[str | Path], config: Mapping[str, object], run: Mapping[str, object],
) -> dict[str, object]:
    """Read, validate, normalize and atomically append a Stage 1 batch."""
    run_id = str(run["run_id"])
    started = str(run.get("as_of") or run.get("started_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    tolerance = float(_config_value(config, "validation", "future_tolerance_hours", 24))
    systems = [row[0] for row in conn.execute("SELECT source_system FROM source_systems ORDER BY source_system")]
    batches: list[tuple[BatchRead, list[RawRow], list[RawRow]]] = []
    input_rows = 0
    warnings: list[str] = []
    all_rejects: list[RawRow] = []
    all_valid: list[RawRow] = []
    for path in paths:
        batch = read_batch(path)
        if batch.file_error:
            return {"status": "failed", "error": batch.file_error, "input_rows": 0,
                    "rejected_rows": 0, "valid_rows": 0, "new_version_rows": 0,
                    "duplicate_event_rows": 0, "metrics": {"phone_invalid": 0, "rejects_by_reason": {}, "warnings": warnings}}
        warnings.extend(batch.warnings)
        input_rows += len(batch.rows) + len(batch.structural_rejects)
        valid, rejects = validate_rows(batch.rows, started, systems, tolerance)
        rejects.extend(batch.structural_rejects)
        for reject in batch.structural_rejects:
            if reject.reason_code is None:
                reject.reason_code = "malformed_row"
        all_valid.extend(valid)
        all_rejects.extend(rejects)
        batches.append((batch, valid, rejects))

    if all(path_batch.is_empty for path_batch, _, _ in batches):
        return {"status": "success_empty", "error": None, "input_rows": 0, "rejected_rows": 0,
                "valid_rows": 0, "new_version_rows": 0, "duplicate_event_rows": 0,
                "metrics": {"phone_invalid": 0, "rejects_by_reason": {}, "warnings": warnings}}

    reasons = Counter(row.reason_code for row in all_rejects)
    phone_invalid = sum(int(normalize_row(row).phone_invalid) for row in all_valid)
    new_versions = duplicate_events = 0
    try:
        with transaction(conn):
            inserted_ids: set[str] = set()
            for row in all_valid:
                compute_keys(row)
            new_versions, duplicate_events = insert_versions(conn, all_valid, run_id)
            # Determine newly inserted versions from their first-seen run within this transaction.
            inserted_ids = {row[0] for row in conn.execute(
                "SELECT version_id FROM raw_customer_records WHERE first_seen_run_id = ?", (run_id,)
            )}
            for row in sorted(all_valid, key=lambda item: (item.version_id or "")):
                if row.version_id not in inserted_ids:
                    continue
                normalized = normalize_row(row)
                conn.execute(CLEAN_INSERT, (
                    row.version_id, row.source_record_id, normalized.email_norm, normalized.phone_norm,
                    normalized.name_norm, normalized.first_name_canon, int(normalized.first_is_initial),
                    normalized.last_name_norm, normalized.address_norm, normalized.postcode_norm,
                    normalized.updated_at_utc, normalized.dob_norm, normalized.soundex_last,
                ))
            for reject in all_rejects:
                raw_hash = hashlib.sha1(reject.raw_line.encode("utf-8")).hexdigest()[:16]
                conn.execute(
                    "INSERT INTO rejects (source_file, source_row_number, reason_code, raw_line, raw_line_hash, first_seen_run_id) "
                    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (source_file, source_row_number, raw_line_hash) DO NOTHING",
                    (reject.source_file, reject.source_row_number, reject.reason_code, reject.raw_line, raw_hash, run_id),
                )
    except Exception:
        LOGGER.exception("stage 1 transaction failed for run %s", run_id)
        raise
    valid_rows = new_versions + duplicate_events
    assert input_rows == len(all_rejects) + valid_rows, "batch identity: input_rows != rejected_rows + valid_rows"
    metrics = {"phone_invalid": phone_invalid, "rejects_by_reason": dict(sorted(reasons.items())), "warnings": warnings}
    return {"status": "success", "error": None, "input_rows": input_rows,
            "rejected_rows": len(all_rejects), "valid_rows": valid_rows,
            "new_version_rows": new_versions, "duplicate_event_rows": duplicate_events,
            "metrics": metrics}
