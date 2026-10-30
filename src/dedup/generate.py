"""Generate deterministic synthetic customer CSV batches and ground truth."""

import json
import logging
import random
from pathlib import Path

from dedup.generator_output import assign_batches, batch_paths, inject_invalid_rows, truth_row, write_csv
from dedup.generator_records import CSV_COLUMNS, TRUTH_COLUMNS, make_records


LOGGER = logging.getLogger(__name__)
DEFAULT_DUP_RATE = 0.35
DEFAULT_FAMILY_RATE = 0.10
DEFAULT_INVALID_RATE = 0.14
DEFAULT_LATE_RATE = 0.10


def generate_data(
    rows: int,
    seed: int,
    dup_rate: float,
    family_rate: float,
    invalid_rate: float,
    late_rate: float,
    batches: int,
    out: str | Path,
    truth_out: str | Path,
) -> list[Path]:
    """Generate CSV batches, aligned ground truth, and a deterministic manifest."""
    if rows < 0:
        raise ValueError("rows must be zero or greater")
    if batches < 1:
        raise ValueError("batches must be at least 1")
    for name, rate in (("dup_rate", dup_rate), ("family_rate", family_rate),
                       ("invalid_rate", invalid_rate), ("late_rate", late_rate)):
        if not 0 <= rate <= 1:
            raise ValueError(f"{name} must be between 0 and 1")
    out_path = Path(out)
    truth_path = Path(truth_out)
    manifest_path = out_path.with_name(f"{out_path.stem}_manifest.json")
    output_paths = batch_paths(out_path, batches)
    protected_paths = {path.resolve() for path in output_paths}
    protected_paths.add(manifest_path.resolve())
    if truth_path.resolve() in protected_paths:
        raise ValueError("output, truth, and manifest paths must be different")

    rng = random.Random(seed)
    records = make_records(rows, rng, dup_rate, family_rate, late_rate)
    assign_batches(records, batches)
    inject_invalid_rows(records, rng, invalid_rate)

    truth_rows: list[list[object]] = []
    for batch_index, path in enumerate(output_paths):
        batch_records = [record for record in records if record.batch_index == batch_index]
        write_csv(path, CSV_COLUMNS, [record.fields for record in batch_records])
        truth_rows.extend(
            truth_row(record, path.name, row_number)
            for row_number, record in enumerate(batch_records, start=1)
        )
    write_csv(truth_path, TRUTH_COLUMNS, truth_rows)

    manifest = {
        "rows": rows,
        "seed": seed,
        "dup_rate": dup_rate,
        "family_rate": family_rate,
        "invalid_rate": invalid_rate,
        "late_rate": late_rate,
        "batches": batches,
        "out": str(out),
        "truth_out": str(truth_out),
        "generated_files": [path.name for path in output_paths],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    LOGGER.info("generated %s rows across %s file(s) with seed %s", rows, batches, seed)
    return output_paths
