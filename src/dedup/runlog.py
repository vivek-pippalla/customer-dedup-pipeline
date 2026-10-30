"""Persist pipeline run status and configure standard logging."""

import json
import logging
import sqlite3
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from dedup.config import load_config
from dedup.ids import new_run_id


LOGGER = logging.getLogger(__name__)
COUNT_COLUMNS = (
    "input_rows", "rejected_rows", "valid_rows", "new_version_rows", "duplicate_event_rows",
    "unique_source_records", "golden_records", "merged_away", "records_in_merged_clusters",
    "review_pending", "records_in_pending_review",
)
RUN_STATUSES = ("running", "success", "success_empty", "failed")


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 Z timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_text(value: object) -> str:
    """Serialize JSON deterministically for storage."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def start_run(
    conn: sqlite3.Connection,
    run_id: str | None = None,
    started_at: str | None = None,
    input_files: Sequence[str] = (),
    config_snapshot: Mapping[str, object] | None = None,
) -> str:
    """Mark interrupted runs, insert a new running row, and commit it."""
    mark_abandoned_runs(conn)
    identifier = run_id or new_run_id()
    config = dict(config_snapshot) if config_snapshot is not None else load_config()
    cursor = conn.execute(
        "INSERT INTO runs (run_id, started_at, status, input_files, config_snapshot) "
        "VALUES (?, ?, 'running', ?, ?) ON CONFLICT (run_id) DO NOTHING",
        (identifier, started_at or _utc_now_iso(), _json_text(sorted(input_files)), _json_text(config)),
    )
    conn.commit()
    if cursor.rowcount != 1:
        raise sqlite3.IntegrityError(f"run_id already exists: {identifier}")
    return identifier


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    counts: Mapping[str, int],
    metrics: Mapping[str, object],
    error: str | None,
) -> None:
    """Update a run's final status, metrics, and counts, then commit."""
    if status not in RUN_STATUSES:
        raise ValueError(f"invalid run status: {status}")
    unknown_counts = set(counts) - set(COUNT_COLUMNS)
    if unknown_counts:
        raise ValueError(f"unknown run count fields: {', '.join(sorted(unknown_counts))}")
    assignments = [f"{column} = ?" for column in COUNT_COLUMNS]
    assignments.extend(("ended_at = ?", "status = ?", "metrics_json = ?", "error_message = ?"))
    values = [counts.get(column, 0) for column in COUNT_COLUMNS]
    values.extend((_utc_now_iso(), status, _json_text(dict(metrics)), error, run_id))
    cursor = conn.execute(
        f"UPDATE runs SET {', '.join(assignments)} WHERE run_id = ?",
        values,
    )
    if cursor.rowcount != 1:
        raise ValueError(f"unknown run_id: {run_id}")
    conn.commit()


def mark_abandoned_runs(conn: sqlite3.Connection) -> int:
    """Mark unfinished runs failed and commit the recovery update."""
    cursor = conn.execute(
        "UPDATE runs SET status = 'failed', ended_at = ?, "
        "error_message = 'abandoned: process stopped before finishing' "
        "WHERE status = 'running'",
        (_utc_now_iso(),),
    )
    conn.commit()
    return cursor.rowcount


def configure_logging(level: str | None = None) -> None:
    """Configure one console handler with ISO-8601 UTC timestamps."""
    configured_level = (level or str(load_config()["logging"]["level"])).upper()
    numeric_level = logging.getLevelName(configured_level)
    if not isinstance(numeric_level, int):
        raise ValueError(f"unknown logging level: {configured_level}")
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            root_logger.removeHandler(handler)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)
    LOGGER.debug("logging configured at %s", configured_level)
