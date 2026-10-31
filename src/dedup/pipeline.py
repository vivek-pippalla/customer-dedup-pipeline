"""Stage orchestration for customer ingestion and validation."""

import hashlib
import logging
import sqlite3
import json
import time
from collections import Counter
from dataclasses import dataclass, field
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
from dedup.runlog import COUNT_COLUMNS, _utc_now_iso, finish_run, mark_abandoned_runs, start_run


LOGGER = logging.getLogger(__name__)


class PipelineRunError(RuntimeError):
    """A failed pipeline execution that has already been recorded in runs."""

    def __init__(self, run_id: str, message: str):
        super().__init__(message)
        self.run_id = run_id
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
    stage_timings: Mapping[str, float] = field(default_factory=dict)


def compute_all(conn: sqlite3.Connection, config: Mapping[str, object]) -> ComputeResult:
    """Compute current versions, candidates, decisions, clusters and golden rows in memory."""
    stage_timings: dict[str, float] = {}
    records = current_versions(conn)
    blocking_config = config.get("blocking", {})
    cap = int(blocking_config.get("block_cap", 200)) if isinstance(blocking_config, Mapping) else 200
    phase_start = time.perf_counter()
    pairs, stats = build_blocks(records, cap)
    stage_timings["blocking_seconds"] = time.perf_counter() - phase_start
    phase_start = time.perf_counter()
    classified = classify_all(records, pairs, config)
    scoring_classification_seconds = time.perf_counter() - phase_start
    auto_pairs = sorted({tuple(sorted((pair.source_record_id_a, pair.source_record_id_b)))
                         for pair in classified if pair.result.decision == "auto_merge"})
    by_id = {str(record["source_record_id"]): record for record in records}
    phase_start = time.perf_counter()
    initial_clusters = build_clusters(list(by_id), auto_pairs)
    clusters, demoted = check_clusters(initial_clusters, by_id)
    stage_timings["clustering_seconds"] = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    demoted_scored = classify_all(records, demoted, config) if demoted else []
    stage_timings["scoring_classification_seconds"] = scoring_classification_seconds + time.perf_counter() - phase_start
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

    phase_start = time.perf_counter()
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
    stage_timings["survivorship_lineage_seconds"] = time.perf_counter() - phase_start
    return ComputeResult(tuple(golden_records), tuple(members), tuple(lineage_rows), candidate_pairs,
                         review_pairs, tuple(clusters), tuple(auto_pairs), tuple(all_classified), stats, counts,
                         stage_timings)


def run_pipeline(
    conn: sqlite3.Connection, paths: Sequence[str | Path], config: Mapping[str, object],
    as_of: str | None = None, run_id: str | None = None, started_at: str | None = None,
    fault_hook=None,
) -> dict[str, object]:
    """Run ingest, in-memory compute, atomic publish, reconciliation and run logging."""
    from dataclasses import asdict

    from dedup.publish import publish

    total_start = time.perf_counter()
    started = started_at or _utc_now_iso()
    reference_time = as_of or started
    input_files = [str(path) for path in paths]
    snapshot = dict(config)
    snapshot["as_of"] = reference_time
    mark_abandoned_runs(conn)
    identifier = start_run(conn, run_id=run_id, started_at=started, input_files=input_files,
                           config_snapshot=snapshot)
    stage_counts: dict[str, int] = {}
    metrics: dict[str, object] = {}
    stage_timings: dict[str, float] = {}
    error_message: str | None = None
    try:
        LOGGER.info("stage 1 ingest started run_id=%s files=%s", identifier, len(input_files))
        phase_start = time.perf_counter()
        staged = stage1_ingest(conn, paths, config, {"run_id": identifier, "started_at": started, "as_of": reference_time})
        stage_timings["stage1_ingest_validate_normalize_seconds"] = time.perf_counter() - phase_start
        stage_counts = {key: int(staged.get(key, 0)) for key in (
            "input_rows", "rejected_rows", "valid_rows", "new_version_rows", "duplicate_event_rows")}
        metrics.update(staged.get("metrics", {}))
        for warning in metrics.get("warnings", []):
            LOGGER.warning("run_id=%s %s", identifier, warning)
        LOGGER.info("stage 1 ingest finished run_id=%s counts=%s", identifier, stage_counts)
        if staged["status"] == "failed":
            stage_timings["total_seconds"] = time.perf_counter() - total_start
            metrics["stage_timings"] = stage_timings
            raise PipelineRunError(identifier, str(staged["error"]))
        if staged["status"] == "success_empty":
            stage_timings["total_seconds"] = time.perf_counter() - total_start
            metrics["stage_timings"] = stage_timings
            finish_run(conn, identifier, "success_empty", stage_counts, metrics, None)
            return {"run_id": identifier, "status": "success_empty", "counts": stage_counts, "metrics": metrics}

        LOGGER.info("stage 2 compute started run_id=%s", identifier)
        compute_start = time.perf_counter()
        computed = compute_all(conn, config)
        compute_timings = dict(computed.stage_timings)
        stage_timings.update(compute_timings)
        stage_timings["compute_setup_seconds"] = max(
            0.0, time.perf_counter() - compute_start - sum(compute_timings.values())
        )
        decision_counts = Counter(pair.result.decision for pair in computed.classified_pairs)
        metrics.update({
            "blocking_stats": asdict(computed.blocking_stats),
            "decision_counts": dict(sorted(decision_counts.items())),
        })
        LOGGER.info("stage 2 compute finished run_id=%s counts=%s", identifier, dict(computed.counts))

        complete_counts = dict(stage_counts)
        complete_counts.update(computed.counts)
        for column in COUNT_COLUMNS:
            complete_counts.setdefault(column, 0)
        LOGGER.info("stage 3 publish started run_id=%s candidates=%s", identifier, len(computed.candidate_pairs))
        publish_start = time.perf_counter()
        reconciliation = publish(
            conn, computed, identifier, fault_hook=fault_hook,
            input_counts=stage_counts,
            rejects_by_reason=metrics.get("rejects_by_reason", {}),
        )
        stage_timings["publish_seconds"] = time.perf_counter() - publish_start
        metrics["reconciliation"] = reconciliation
        LOGGER.info("stage 3 publish finished run_id=%s counts=%s", identifier, computed.counts)
        stage_timings["total_seconds"] = time.perf_counter() - total_start
        metrics["stage_timings"] = stage_timings
        finish_run(conn, identifier, "success", complete_counts, metrics, None)
        return {"run_id": identifier, "status": "success", "counts": complete_counts, "metrics": metrics,
                "compute_result": computed}
    except Exception as error:
        if conn.in_transaction:
            conn.rollback()
        error_message = str(error)
        metrics["error"] = error_message
        stage_timings["total_seconds"] = time.perf_counter() - total_start
        metrics["stage_timings"] = stage_timings
        LOGGER.exception("pipeline run failed run_id=%s", identifier)
        try:
            failed_counts = {column: stage_counts.get(column, 0) for column in COUNT_COLUMNS}
            finish_run(conn, identifier, "failed", failed_counts, metrics, error_message)
        except Exception:
            LOGGER.exception("could not persist failed run run_id=%s", identifier)
        if isinstance(error, PipelineRunError):
            raise
        raise PipelineRunError(identifier, error_message) from error


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
