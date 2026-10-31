"""Command-line interface for the deduplication pipeline."""

import argparse
from collections.abc import Sequence
import logging
from datetime import datetime, timezone
import json
import sqlite3

from dedup.config import load_config
from dedup.db import connect, init_schema
from dedup.generate import (
    DEFAULT_DUP_RATE,
    DEFAULT_FAMILY_RATE,
    DEFAULT_INVALID_RATE,
    DEFAULT_LATE_RATE,
    generate_data,
)
from dedup.runlog import configure_logging
from dedup.pipeline import PipelineRunError, run_pipeline
from dedup.evaluate import evaluate_database
from dedup.report import write_report


LOGGER = logging.getLogger(__name__)

def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for all pipeline commands."""
    parser = argparse.ArgumentParser(prog="dedup")
    parser.add_argument("--log-level", dest="global_log_level")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init-db", "run", "generate", "evaluate", "report", "review-decide"):
        command_parser = commands.add_parser(name)
        command_parser.add_argument("--log-level", dest="command_log_level")
        if name == "init-db":
            command_parser.add_argument("--db", required=True, help="SQLite database path")
        elif name == "run":
            command_parser.add_argument("--input", nargs="+", required=True, metavar="FILE")
            command_parser.add_argument("--db", required=True)
            command_parser.add_argument("--config", required=True)
            command_parser.add_argument("--as-of")
        elif name == "evaluate":
            command_parser.add_argument("--db", required=True)
            command_parser.add_argument("--truth", required=True)
        elif name == "report":
            command_parser.add_argument("--db", required=True)
            command_parser.add_argument("--out", required=True)
            command_parser.add_argument("--export-dir")
        elif name == "review-decide":
            command_parser.add_argument("--db", required=True)
            command_parser.add_argument("--pair-id", required=True)
            command_parser.add_argument("--decision", choices=("merge", "not_merge"), required=True)
            command_parser.add_argument("--reviewer", required=True)
            command_parser.add_argument("--note", required=True)
        elif name == "generate":
            command_parser.add_argument("--rows", type=int, required=True)
            command_parser.add_argument("--seed", type=int, default=1)
            command_parser.add_argument("--dup-rate", type=float, default=DEFAULT_DUP_RATE)
            command_parser.add_argument("--family-rate", type=float, default=DEFAULT_FAMILY_RATE)
            command_parser.add_argument("--invalid-rate", type=float, default=DEFAULT_INVALID_RATE)
            command_parser.add_argument("--late-rate", type=float, default=DEFAULT_LATE_RATE)
            command_parser.add_argument("--batches", type=int, default=1)
            command_parser.add_argument("--out", required=True)
            command_parser.add_argument("--truth-out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run database initialization or a not-yet-implemented command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config if args.command == "run" else None)
    except ValueError as error:
        parser.error(str(error))
    log_level = args.command_log_level or args.global_log_level or config["logging"]["level"]
    configure_logging(str(log_level))
    if args.command == "init-db":
        connection = connect(args.db)
        try:
            init_schema(connection, config)
        finally:
            connection.close()
        LOGGER.info("initialized database at %s", args.db)
        return 0
    if args.command == "generate":
        try:
            generate_data(
                rows=args.rows,
                seed=args.seed,
                dup_rate=args.dup_rate,
                family_rate=args.family_rate,
                invalid_rate=args.invalid_rate,
                late_rate=args.late_rate,
                batches=args.batches,
                out=args.out,
                truth_out=args.truth_out,
            )
        except ValueError as error:
            parser.error(str(error))
        return 0
    if args.command == "evaluate":
        connection = connect(args.db)
        try:
            result = evaluate_database(connection, args.truth, config)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        except (OSError, ValueError) as error:
            parser.error(str(error))
        finally:
            connection.close()
    if args.command == "report":
        connection = connect(args.db)
        try:
            target = write_report(connection, args.out, args.export_dir)
            print(f"Wrote {target}")
            if args.export_dir:
                print(f"Exported CSV tables to {args.export_dir}")
            return 0
        except (OSError, sqlite3.Error) as error:
            parser.error(str(error))
        finally:
            connection.close()
    if args.command == "review-decide":
        connection = connect(args.db)
        try:
            decided_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            connection.execute(
                "INSERT INTO review_decisions (pair_id, decision, reviewer, decided_at, note) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (pair_id) DO UPDATE SET decision=excluded.decision, reviewer=excluded.reviewer, "
                "decided_at=excluded.decided_at, note=excluded.note",
                (args.pair_id, args.decision, args.reviewer, decided_at, args.note),
            )
            connection.commit()
            print(f"Saved {args.decision} decision for {args.pair_id}")
            return 0
        except sqlite3.Error as error:
            parser.error(str(error))
        finally:
            connection.close()
    if args.command == "run":
        as_of = args.as_of
        if as_of:
            try:
                parsed_as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
                if parsed_as_of.tzinfo is None:
                    parsed_as_of = parsed_as_of.replace(tzinfo=timezone.utc)
                as_of = parsed_as_of.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                parser.error("--as-of must be an ISO-8601 timestamp")
        started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        connection = connect(args.db)
        try:
            init_schema(connection, config)
            result = run_pipeline(connection, args.input, config, as_of=as_of, started_at=started_at)
            counts = result["counts"]
            metrics = result["metrics"]
            print(f"Run {result['run_id']}: {result['status']}")
            summary_columns = ("input_rows", "rejected_rows", "valid_rows", "new_version_rows", "duplicate_event_rows",
                               "unique_source_records", "golden_records", "merged_away", "review_pending")
            print("Count | " + " | ".join(summary_columns) + " | rejects_by_reason")
            print("Run | " + " | ".join(str(counts.get(key, 0)) for key in summary_columns) +
                  f" | {metrics.get('rejects_by_reason', {})}")
            return 0
        except PipelineRunError as error:
            print(f"Run failed: {error}")
            return 1
        finally:
            connection.close()
    print("not implemented yet")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
