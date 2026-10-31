"""Run a small dev-only grid over matching thresholds and weight profiles."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
import tempfile
from typing import Mapping

from dedup.config import load_config
from dedup.db import connect, init_schema
from dedup.evaluate import evaluate_database
from dedup.pipeline import run_pipeline


AUTO_VALUES = (0.85, 0.95)
REVIEW_VALUES = (0.55, 0.75)
LAST_NAME_VALUES = (0.85, 0.95)
WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "current": {"email": 0.30, "phone": 0.25, "name": 0.25, "address": 0.10, "dob": 0.10},
    "name_forward": {"email": 0.25, "phone": 0.25, "name": 0.30, "address": 0.10, "dob": 0.10},
    "identifier_forward": {"email": 0.35, "phone": 0.30, "name": 0.20, "address": 0.05, "dob": 0.10},
    "address_forward": {"email": 0.25, "phone": 0.20, "name": 0.25, "address": 0.20, "dob": 0.10},
}


def _assert_weight_profiles() -> None:
    """Fail early if any grid weight profile is not normalized."""
    for name, weights in WEIGHT_PROFILES.items():
        if abs(sum(weights.values()) - 1.0) > 1e-9:
            raise ValueError(f"weight profile {name} does not sum to 1.0")


def _tune_one(
    base_config: Mapping[str, object], input_path: Path, truth_path: Path,
    auto: float, review: float, last_name_min_jw: float, profile_name: str,
    weights: Mapping[str, float], as_of: str,
) -> dict[str, object]:
    """Run one isolated full pipeline and evaluate the resulting database."""
    config = deepcopy(dict(base_config))
    thresholds = dict(config["thresholds"])
    thresholds.update({"auto": auto, "review": review, "last_name_min_jw": last_name_min_jw})
    config["thresholds"] = thresholds
    config["weights"] = dict(weights)
    with tempfile.TemporaryDirectory(prefix="dedup-tune-") as temporary:
        conn = connect(Path(temporary) / "tune.db")
        try:
            init_schema(conn, config)
            run_pipeline(conn, [input_path], config, as_of=as_of)
            result = evaluate_database(conn, truth_path, config)
        finally:
            conn.close()
    auto_metrics = result["auto_merge_pairs_only_pre_clustering"]
    return {
        "auto": auto,
        "review": review,
        "last_name_min_jw": last_name_min_jw,
        "weights": profile_name,
        "precision": result["precision"],
        "recall": result["recall"],
        "f1": result["f1"],
        "auto_precision": auto_metrics["precision"],
        "review_queue_size": result["review_queue_size"],
        "false_auto_merges": result["false_auto_merge_count"],
    }


def _print_results(results: list[dict[str, object]]) -> None:
    """Print the complete tuning grid and a recommended eligible point."""
    columns = ("auto", "review", "last_name_min_jw", "weights", "precision", "recall", "f1",
               "auto_precision", "review_queue_size", "false_auto_merges")
    widths = {column: max(len(column), *(len(f"{row[column]:.4f}") if column in {"precision", "recall", "f1", "auto_precision"}
                                     else len(str(row[column])) for row in results)) for column in columns}
    print(" | ".join(column.ljust(widths[column]) for column in columns))
    print("-+-".join("-" * widths[column] for column in columns))
    for row in results:
        cells = []
        for column in columns:
            value = f"{row[column]:.4f}" if column in {"precision", "recall", "f1", "auto_precision"} else str(row[column])
            cells.append(value.ljust(widths[column]))
        print(" | ".join(cells))
    eligible = [row for row in results if float(row["auto_precision"]) >= 0.99]
    if eligible:
        recommended = max(eligible, key=lambda row: (float(row["recall"]), float(row["f1"]),
                                                       float(row["auto_precision"]),
                                                       -int(row["review_queue_size"])))
        print("\nRecommendation (not applied): maximize cluster recall among rows with auto-merge precision >= 0.99;")
        print("ties break by cluster F1, auto-merge precision, then smaller review queue.")
    else:
        recommended = max(results, key=lambda row: (float(row["auto_precision"]), float(row["recall"]),
                                                     float(row["f1"])))
        print("\nNo row reached the 0.99 auto-merge precision target. Recommendation (not applied):")
        print("highest auto-merge precision, then recall and cluster F1.")
    print("Recommended operating point:", recommended)


def main() -> int:
    """Execute the tuning grid using only the supplied dev dataset."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="seed-1 development CSV")
    parser.add_argument("--truth", required=True, type=Path, help="matching development ground-truth CSV")
    parser.add_argument("--config", required=True, type=Path, help="base TOML configuration")
    parser.add_argument("--profiles", nargs="+", choices=tuple(WEIGHT_PROFILES), default=tuple(WEIGHT_PROFILES),
                        help="weight profiles to evaluate (default: all four profiles)")
    args = parser.parse_args()
    if not args.input.is_file() or not args.truth.is_file():
        parser.error("both --input and --truth must be existing files")
    _assert_weight_profiles()
    base_config = load_config(args.config)
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    selected_profiles = [(name, WEIGHT_PROFILES[name]) for name in args.profiles]
    results = [
        _tune_one(base_config, args.input, args.truth, auto, review, last_name_min_jw,
                 profile_name, weights, as_of)
        for auto, review, last_name_min_jw, (profile_name, weights) in product(
            AUTO_VALUES, REVIEW_VALUES, LAST_NAME_VALUES, selected_profiles
        )
    ]
    _print_results(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
