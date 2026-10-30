"""Command-line interface for the deduplication pipeline."""

import argparse
from collections.abc import Sequence
import logging

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
    config = load_config()
    log_level = args.command_log_level or args.global_log_level or config["logging"]["level"]
    configure_logging(str(log_level))
    if args.command == "init-db":
        connection = connect(args.db)
        try:
            init_schema(connection)
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
    print("not implemented yet")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
