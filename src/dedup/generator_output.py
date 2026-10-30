"""Apply labelled generation cases and write deterministic CSV outputs."""

import csv
import json
import math
import random
from pathlib import Path
from typing import Sequence

from dedup.generator_records import CSV_COLUMNS, TRUTH_COLUMNS, GeneratedRecord
from dedup.ids import row_hash, source_record_id


INVALID_ISSUES = (
    "invalid_email", "missing_required", "invalid_source_system", "malformed_row",
    "invalid_timestamp", "future_timestamp", "duplicate_key",
)


def assign_batches(records: list[GeneratedRecord], batches: int) -> None:
    """Distribute rows in order and place late versions in a later file."""
    row_count = len(records)
    base_size, remainder = divmod(row_count, batches)
    cursor = 0
    for batch_index in range(batches):
        size = base_size + (batch_index < remainder)
        for record in records[cursor:cursor + size]:
            record.batch_index = batch_index
        cursor += size
    if batches > 1:
        for newer in records:
            if not newer.late_new:
                continue
            older = next((record for record in records if record.late_old and record.entity_id == newer.entity_id
                          and record.fields[1] == newer.fields[1]), None)
            if older is not None:
                newer.batch_index = 0
                older.batch_index = min(1, batches - 1)


def _make_duplicate_pair(
    records: list[GeneratedRecord], invalid_indices: set[int], target_index: int,
) -> tuple[int, int] | None:
    """Make a same-key, same-time conflict with one eligible valid partner."""
    target = records[target_index]
    entity_sizes: dict[str, int] = {}
    for record in records:
        entity_sizes[record.entity_id] = entity_sizes.get(record.entity_id, 0) + 1
    candidates = [
        index for index, record in enumerate(records)
        if index != target_index and index not in invalid_indices
        and record.batch_index == target.batch_index
        and (record.entity_id == target.entity_id or entity_sizes[record.entity_id] < 4)
        and not record.late_old and not record.late_new
    ]
    if not candidates:
        return None
    partner_index = min(candidates)
    partner = records[partner_index]
    target.fields[0:2] = partner.fields[0:2]
    target.fields[8] = partner.fields[8]
    target.entity_id = partner.entity_id
    target.fields[2] = f"{partner.fields[2]} Duplicate"
    target_hash = row_hash(*target.fields)
    partner_hash = row_hash(*partner.fields)
    victim = records[target_index if target_hash > partner_hash else partner_index]
    victim.invalid_reason = "duplicate_key"
    victim.issue = "duplicate_key"
    return target_index, partner_index


def inject_invalid_rows(records: list[GeneratedRecord], rng: random.Random, invalid_rate: float) -> None:
    """Inject labelled validation failures while preserving the row count."""
    if not records or invalid_rate <= 0:
        return
    invalid_count = min(len(records), max(1, math.floor(len(records) * invalid_rate + 0.5)))
    eligible_targets = [index for index, record in enumerate(records) if not record.late_old and not record.late_new]
    if len(eligible_targets) < invalid_count:
        eligible_targets = list(range(len(records)))
    targets = sorted(rng.sample(eligible_targets, invalid_count))
    issues = [INVALID_ISSUES[index % len(INVALID_ISSUES)] for index in range(invalid_count)]
    rng.shuffle(issues)
    target_set = set(targets)
    for target_index, issue in zip(targets, issues):
        record = records[target_index]
        if issue == "duplicate_key":
            duplicate_pair = _make_duplicate_pair(records, target_set, target_index)
            if duplicate_pair is not None:
                target_set.update(duplicate_pair)
                continue
            issue = "invalid_timestamp"
        if issue == "invalid_email":
            record.fields[3] = "not-an-email"
        elif issue == "missing_required":
            record.fields[2] = ""
        elif issue == "invalid_source_system":
            record.fields[0] = "UNKNOWN"
        elif issue == "malformed_row":
            record.fields = record.fields[:-1]
        elif issue == "invalid_timestamp":
            record.fields[8] = "not-a-timestamp"
        elif issue == "future_timestamp":
            record.fields[8] = "2099-01-01T00:00:00Z"
        record.invalid_reason = issue
        record.issue = issue


def batch_paths(out_path: Path, batches: int) -> list[Path]:
    """Build output paths for one file or a numbered batch set."""
    if batches == 1:
        return [out_path]
    suffix = out_path.suffix or ".csv"
    return [out_path.with_name(f"{out_path.stem}_batch{index + 1}{suffix}")
            for index in range(batches)]


def write_csv(path: Path, header: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    """Write stable UTF-8 CSV with Windows-safe newline handling."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.writer(output_file, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def truth_row(record: GeneratedRecord, source_file: str, row_number: int) -> list[object]:
    """Create a truth row using the production source-record ID function."""
    source_id = ""
    if len(record.fields) >= 2 and record.fields[0] and record.fields[1]:
        source_id = source_record_id(record.fields[0], record.fields[1])
    return [
        source_file, row_number, source_id, record.entity_id,
        str(bool(record.invalid_reason)).lower(), record.invalid_reason, record.issue,
    ]
