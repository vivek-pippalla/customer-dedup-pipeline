"""Tests for deterministic synthetic CSV generation."""

import csv
import hashlib
from pathlib import Path

from dedup.generate import CSV_COLUMNS, TRUTH_COLUMNS, generate_data
from dedup.wordlists import CITIES_AND_POSTCODES, FIRST_NAMES, LAST_NAMES, STREET_NAMES
from dedup.ids import row_hash


def _generate(directory: Path, seed: int = 42, rows: int = 50, batches: int = 1) -> tuple[list[Path], Path, Path]:
    """Generate a dataset with stable test parameters."""
    out = directory / "customers.csv"
    truth = directory / "truth.csv"
    files = generate_data(
        rows=rows,
        seed=seed,
        dup_rate=0.35,
        family_rate=0.20,
        invalid_rate=0.14,
        late_rate=0.10,
        batches=batches,
        out=out,
        truth_out=truth,
    )
    return files, truth, out.with_name(f"{out.stem}_manifest.json")


def _read_rows(paths: list[Path]) -> list[tuple[Path, list[dict[str, str]]]]:
    """Read generated CSV rows while keeping each source file identity."""
    result = []
    for path in paths:
        with path.open(encoding="utf-8", newline="") as csv_file:
            result.append((path, list(csv.DictReader(csv_file))))
    return result


def _file_hash(path: Path) -> str:
    """Hash file bytes for reproducibility assertions."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_same_arguments_produce_byte_identical_files(tmp_path: Path) -> None:
    """Reusing the same paths and arguments reproduces every output byte."""
    files, truth, manifest = _generate(tmp_path, rows=80, batches=2)
    before = [_file_hash(path) for path in (*files, truth, manifest)]
    _generate(tmp_path, rows=80, batches=2)
    after = [_file_hash(path) for path in (*files, truth, manifest)]
    assert before == after


def test_different_seeds_change_generated_rows(tmp_path: Path) -> None:
    """Different seeds produce different customer CSV bytes."""
    first, _, _ = _generate(tmp_path / "seed1", seed=1, rows=100)
    second, _, _ = _generate(tmp_path / "seed2", seed=2, rows=100)
    assert _file_hash(first[0]) != _file_hash(second[0])


def test_exact_row_count_truth_and_headers(tmp_path: Path) -> None:
    """Rows include invalid records, and truth has one row for every emitted record."""
    files, truth_path, _ = _generate(tmp_path, rows=53, batches=3)
    data_rows = []
    for path, rows in _read_rows(files):
        assert list(rows[0]) == list(CSV_COLUMNS)
        data_rows.extend(rows)
    with truth_path.open(encoding="utf-8", newline="") as truth_file:
        truth_rows = list(csv.DictReader(truth_file))
    assert len(data_rows) == 53
    assert len(truth_rows) == 53
    assert list(truth_rows[0]) == list(TRUTH_COLUMNS)
    assert {row["source_file"] for row in truth_rows} == {path.name for path in files}


def test_invalid_rows_are_labelled(tmp_path: Path) -> None:
    """Every generated invalid row has an injected issue and a reject reason."""
    _, truth_path, _ = _generate(tmp_path, rows=100)
    with truth_path.open(encoding="utf-8", newline="") as truth_file:
        truth_rows = list(csv.DictReader(truth_file))
    invalid_rows = [row for row in truth_rows if row["is_invalid"] == "true"]
    assert invalid_rows
    assert all(row["injected_issue"] for row in invalid_rows)
    assert all(row["expected_reject_reason"] for row in invalid_rows)


def test_family_and_late_versions_exist_in_large_run(tmp_path: Path) -> None:
    """A 500-row run includes a cross-entity shared identifier and an older late row."""
    files, truth_path, _ = _generate(tmp_path, rows=500)
    with truth_path.open(encoding="utf-8", newline="") as truth_file:
        truth_rows = list(csv.DictReader(truth_file))
    entity_by_row = {(row["source_file"], int(row["row_number"])): row["true_entity_id"] for row in truth_rows}
    records = [
        (path.name, row_number, row)
        for path, rows in _read_rows(files)
        for row_number, row in enumerate(rows, start=1)
    ]
    family_pair_exists = any(
        entity_by_row[(left_file, left_number)] != entity_by_row[(right_file, right_number)]
        and (left["email"].strip().lower() == right["email"].strip().lower() != ""
             or "".join(char for char in left["phone"] if char.isdigit())
             == "".join(char for char in right["phone"] if char.isdigit()) != "")
        for index, (left_file, left_number, left) in enumerate(records)
        for right_file, right_number, right in records[index + 1:]
    )
    late_pair_exists = any(
        left["source_system"] == right["source_system"]
        and left["source_native_id"] == right["source_native_id"]
        and left["updated_at"] > right["updated_at"]
        for index, (_, _, left) in enumerate(records)
        for _, _, right in records[index + 1:]
    )
    assert family_pair_exists
    assert late_pair_exists


def test_duplicate_key_marks_larger_row_hash_invalid(tmp_path: Path) -> None:
    """A same-source same-time pair labels exactly its larger content hash invalid."""
    files, truth_path, _ = _generate(tmp_path, rows=200)
    records = {path.name: rows for path, rows in _read_rows(files)}
    with truth_path.open(encoding="utf-8", newline="") as truth_file:
        truth_rows = list(csv.DictReader(truth_file))
    duplicate_truth = [row for row in truth_rows if row["expected_reject_reason"] == "duplicate_key"]
    assert duplicate_truth
    truth_index = {(row["source_file"], int(row["row_number"])): row for row in truth_rows}
    checked: set[tuple[str, int]] = set()
    for victim_truth in duplicate_truth:
        rows = records[victim_truth["source_file"]]
        row_number = int(victim_truth["row_number"])
        victim = rows[row_number - 1]
        key = (victim_truth["source_file"], row_number)
        if key in checked:
            continue
        pair = [
            (index, row) for index, row in enumerate(rows, start=1)
            if truth_index[(victim_truth["source_file"], index)]["source_record_id"] == victim_truth["source_record_id"]
            and row["updated_at"] == victim["updated_at"]
        ]
        assert len(pair) == 2
        assert sum(truth_index[(victim_truth["source_file"], index)]["is_invalid"] == "true"
                   for index, _ in pair) == 1
        hashes = [(row_hash(*(row[column] for column in CSV_COLUMNS)), index) for index, row in pair]
        larger_index = max(hashes)[1]
        assert truth_index[(victim_truth["source_file"], larger_index)]["expected_reject_reason"] == "duplicate_key"
        assert victim_truth["injected_issue"] == "duplicate_key"
        checked.update((victim_truth["source_file"], index) for index, _ in pair)


def test_valid_updated_timestamps_stay_in_fixed_range(tmp_path: Path) -> None:
    """Only rows explicitly labelled invalid may carry timestamps outside the fixed range."""
    files, truth_path, _ = _generate(tmp_path, rows=500)
    with truth_path.open(encoding="utf-8", newline="") as truth_file:
        truth_rows = list(csv.DictReader(truth_file))
    invalid = {(row["source_file"], int(row["row_number"])) for row in truth_rows if row["is_invalid"] == "true"}
    for path, rows in _read_rows(files):
        for row_number, row in enumerate(rows, start=1):
            if (path.name, row_number) in invalid:
                continue
            assert "2023-01-01T" <= row["updated_at"] <= "2025-12-31T23:59:59Z"


def test_wordlists_and_boundary_values_are_present(tmp_path: Path) -> None:
    """The generator uses the planned list sizes and emits required boundaries."""
    assert len(FIRST_NAMES) == 60
    assert len(LAST_NAMES) == 60
    assert len(CITIES_AND_POSTCODES) == 20
    assert len(STREET_NAMES) == 20
    files, _, _ = _generate(tmp_path, rows=500)
    rows = [row for _, batch in _read_rows(files) for row in batch]
    assert any(len(row["full_name"].strip()) == 1 for row in rows)
    assert any(len(row["address"]) == 300 for row in rows)
    assert any(value == "" for row in rows for value in row.values())


def test_late_versions_are_in_later_batch_file(tmp_path: Path) -> None:
    """When batches are requested, a late version is placed in a later file."""
    files, _, _ = _generate(tmp_path, rows=100, batches=3)
    assert [path.name for path in files] == ["customers_batch1.csv", "customers_batch2.csv", "customers_batch3.csv"]
    records = [(index, row) for index, path in enumerate(files)
               for row in next(iter(_read_rows([path])))[1]]
    assert any(
        later_file > earlier_file
        and earlier["source_system"] == later["source_system"]
        and earlier["source_native_id"] == later["source_native_id"]
        and earlier["updated_at"] > later["updated_at"]
        for earlier_file, earlier in records for later_file, later in records
    )
