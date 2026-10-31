"""Deterministic in-memory candidate pair generation."""

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CappedBlock:
    """One skipped oversized block and its potential pair count."""
    key_type: str
    key_value: str
    size: int
    pairs_skipped: int


@dataclass(frozen=True)
class BlockingStats:
    """Candidate generation counts and cap diagnostics."""
    comparisons_naive: int
    comparisons_blocked: int
    reduction_ratio: float
    per_key_block_counts: dict[str, int]
    capped_block_count: int
    capped_blocks: tuple[CappedBlock, ...]
    pairs_skipped_cap: int


def block_keys(record: Mapping[str, object]) -> list[tuple[str, str]]:
    """Return the applicable email, phone and composite blocking keys."""
    keys: list[tuple[str, str]] = []
    email = record.get("email_norm")
    phone = record.get("phone_norm")
    if email:
        keys.append(("email", str(email)))
    if phone:
        keys.append(("phone", str(phone)))
    soundex = record.get("soundex_last")
    first = str(record.get("name_norm") or "").split()
    postcode = record.get("postcode_norm")
    if soundex and first and postcode:
        composite = f"{soundex}|{first[0][0]}|{postcode}"
        keys.append(("soundex_first_postcode", composite))
    return keys


def build_blocks(
    records: Sequence[Mapping[str, object]], block_cap: int,
) -> tuple[list[tuple[str, str]], BlockingStats]:
    """Build sorted unique pairs and report potential comparisons skipped by caps."""
    if block_cap < 1:
        raise ValueError("block_cap must be at least 1")
    by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    record_ids = sorted({str(record["source_record_id"]) for record in records})
    for record in records:
        record_id = str(record["source_record_id"])
        for key in block_keys(record):
            by_key[key].add(record_id)

    pairs: set[tuple[str, str]] = set()
    counts: dict[str, int] = defaultdict(int)
    capped: list[CappedBlock] = []
    skipped = 0
    for (key_type, key_value), members in sorted(by_key.items()):
        counts[key_type] += 1
        ordered_members = sorted(members)
        if len(ordered_members) > block_cap:
            skipped_pairs = len(ordered_members) * (len(ordered_members) - 1) // 2
            capped.append(CappedBlock(key_type, key_value, len(ordered_members), skipped_pairs))
            skipped += skipped_pairs
            continue
        pairs.update(combinations(ordered_members, 2))
    naive = len(record_ids) * (len(record_ids) - 1) // 2
    blocked = len(pairs)
    stats = BlockingStats(
        comparisons_naive=naive,
        comparisons_blocked=blocked,
        reduction_ratio=(1.0 - blocked / naive) if naive else 0.0,
        per_key_block_counts=dict(sorted(counts.items())),
        capped_block_count=len(capped),
        capped_blocks=tuple(sorted(capped, key=lambda block: (-block.size, block.key_type, block.key_value))[:20]),
        pairs_skipped_cap=skipped,
    )
    return sorted(pairs), stats
