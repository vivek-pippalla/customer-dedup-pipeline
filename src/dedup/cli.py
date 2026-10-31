"""Command-line interface for the deduplication pipeline."""

import argparse
from collections.abc import Sequence
import logging
from datetime import datetime, timezone

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
from dedup.runlog import finish_run, mark_abandoned_runs, start_run
from dedup.pipeline import stage1_ingest


LOGGER = logging.getLogger(__name__)

def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for all pipeline commands."""
    parser = argparse.ArgumentParser(prog="dedup")
    parser.add_argument("--log-level", dest="global_log_level")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init-db", "run", "generate", "evaluate", "report"):
        command_parser = commands.add_parser(name)
        command_parser.add_argument("--log-level", dest="command_log_level")
        if name == "init-db":
            command_parser.add_argument("--db", required=True, help="SQLite database path")
        elif name == "run":
            command_parser.add_argument("--input", nargs="+", required=True, metavar="FILE")
            command_parser.add_argument("--db", required=True)
            command_parser.add_argument("--config", required=True)
            command_parser.add_argument("--as-of")
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
        run_id = None
        try:
            init_schema(connection)
            mark_abandoned_runs(connection)
            snapshot = dict(config)
            snapshot["as_of"] = as_of or started_at
            run_id = start_run(connection, started_at=started_at, input_files=args.input, config_snapshot=snapshot)
            result = stage1_ingest(connection, args.input, config, {"run_id": run_id, "started_at": started_at, "as_of": as_of or started_at})
            counts = {key: int(result.get(key, 0)) for key in (
                "input_rows", "rejected_rows", "valid_rows", "new_version_rows", "duplicate_event_rows")}
            finish_run(connection, run_id, str(result["status"]), counts, result["metrics"], result["error"])
            if result["status"] == "failed":
                print(f"Run {run_id} failed: {result['error']}")
                return 1
            metrics = result["metrics"]
            print(f"Run {run_id}: {result['status']}")
            print("Input rows | Rejected by reason | New versions | Duplicate events")
            print(f"{counts['input_rows']} | {metrics['rejects_by_reason']} | {counts['new_version_rows']} | {counts['duplicate_event_rows']}")
            return 0
        except Exception as error:
            LOGGER.exception("run failed")
            if run_id is not None:
                try:
                    finish_run(connection, run_id, "failed", {}, {}, str(error))
                except Exception:
                    LOGGER.exception("could not finish failed run %s", run_id)
            print(f"Run failed: {error}")
            return 1
        finally:
            connection.close()
    print("not implemented yet")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
