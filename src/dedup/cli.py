"""Command-line interface for the deduplication pipeline."""

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(prog="dedup")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init-db", "run", "generate", "evaluate", "report"):
        commands.add_parser(name)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command stub and return its process status."""
    args = build_parser().parse_args(argv)
    print("not implemented yet")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
