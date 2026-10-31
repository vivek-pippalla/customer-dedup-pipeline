"""Deterministic golden-field selection and field-level lineage."""

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from dedup.ids import golden_id
from dedup.normalize import normalize_email, normalize_phone, normalize_postcode


@dataclass(frozen=True)
class FieldLineage:
    """The source and selection rule for one golden field."""
    field_name: str
    value: str | None
    version_id: str | None
    source_record_id: str | None
    source_system: str | None
    rule_applied: str


@dataclass(frozen=True)
class GoldenMember:
    """Current source-record version represented by a golden record."""
    source_record_id: str
    version_id: str


@dataclass(frozen=True)
class GoldenRecord:
    """Golden customer values, members and lineage, ready for publication."""
    golden_id: str
    full_name: str | None
    email: str | None
    phone: str | None
    address: str | None
    postcode: str | None
    dob: str | None
    member_count: int
    match_tier: str
    latest_updated_at_utc: str | None
    members: tuple[GoldenMember, ...]
    lineage: tuple[FieldLineage, ...]


Candidate = Mapping[str, object]
Criterion = tuple[str, Callable[[Candidate], object], bool]


def _text(record: Candidate, field: str) -> str | None:
    value = record.get(field)
    text = str(value).strip() if value is not None else ""
    return text or None


def _non_empty_candidates(records: Sequence[Candidate], field: str) -> list[Candidate]:
    return [record for record in records if _text(record, field)]


def _select(candidates: Sequence[Candidate], criteria: Sequence[Criterion]) -> tuple[Candidate, str]:
    """Apply ordered max/min criteria, reporting the first criterion that narrows."""
    remaining = list(candidates)
    for label, key, maximize in criteria:
        best = (max if maximize else min)(key(record) for record in remaining)
        narrowed = [record for record in remaining if key(record) == best]
        if len(narrowed) < len(remaining):
            remaining = narrowed
            rule = label
        else:
            rule = "tie_break_smallest_id"
        if len(remaining) == 1:
            return remaining[0], rule
    winner = min(remaining, key=lambda record: str(record["source_record_id"]))
    return winner, "tie_break_smallest_id"


def _priority(record: Candidate, source_priority: Mapping[str, int]) -> int:
    return int(source_priority.get(str(record.get("source_system") or "").strip().upper(), 9999))


def _updated(record: Candidate) -> str:
    return str(record.get("updated_at_utc") or "")


def _non_nickname_first(record: Candidate) -> int:
    tokens = str(record.get("name_norm") or "").split()
    return int(bool(tokens and record.get("first_name_canon") and str(record["first_name_canon"]) == tokens[0]))


def _lineage(field: str, candidates: Sequence[Candidate], source_priority: Mapping[str, int]) -> FieldLineage:
    """Choose the source for a golden field according to its exact rule chain."""
    if not candidates:
        return FieldLineage(field, None, None, None, None, "no_value")
    if field == "full_name":
        criteria: list[Criterion] = [
            ("non_nickname_first_name", _non_nickname_first, True),
            ("most_tokens", lambda row: len(str(row.get("name_norm") or "").split()), True),
            ("longest_name", lambda row: len(_text(row, "full_name") or ""), True),
            ("source_priority", lambda row: _priority(row, source_priority), False),
            ("latest_updated_at", _updated, True),
        ]
    elif field == "email":
        criteria = [("source_priority", lambda row: _priority(row, source_priority), False),
                    ("latest_updated_at", _updated, True)]
    elif field == "phone":
        criteria = [("latest_updated_at", _updated, True),
                    ("source_priority", lambda row: _priority(row, source_priority), False)]
    elif field == "address":
        criteria = [("most_complete_address", lambda row: sum(bool(part.strip()) for part in
                    str(row.get("address") or "").split(",")), True),
                    ("latest_updated_at", _updated, True),
                    ("source_priority", lambda row: _priority(row, source_priority), False)]
    elif field == "postcode":
        address_winner = next((row for row in candidates if row.get("_address_winner")), None)
        if address_winner:
            return FieldLineage(field, _text(address_winner, field), _text(address_winner, "version_id"),
                                _text(address_winner, "source_record_id"), _text(address_winner, "source_system"),
                                "follows_address_winner")
        criteria = [("source_priority", lambda row: _priority(row, source_priority), False),
                    ("latest_updated_at", _updated, True)]
    elif field == "dob":
        counts = Counter(str(row.get("dob_norm")) for row in candidates)
        most_common = counts.most_common()
        has_majority = len(most_common) == 1 or most_common[0][1] > most_common[1][1]
        if has_majority:
            candidates = [row for row in candidates if str(row.get("dob_norm")) == most_common[0][0]]
        winner, source_rule = _select(candidates, [("source_priority", lambda row: _priority(row, source_priority), False)])
        rule = "majority_value" if has_majority else source_rule
        value = _text(winner, "dob") or _text(winner, "dob_norm")
        return FieldLineage(field, value, _text(winner, "version_id"), _text(winner, "source_record_id"),
                            _text(winner, "source_system"), rule)
    else:
        raise ValueError(f"unknown golden field: {field}")
    winner, rule = _select(candidates, criteria)
    value = _text(winner, field)
    if field == "dob":
        value = _text(winner, "dob") or _text(winner, "dob_norm")
    return FieldLineage(field, value, _text(winner, "version_id"), _text(winner, "source_record_id"),
                        _text(winner, "source_system"), rule)


def build_golden(
    cluster: Sequence[str], records_by_id: Mapping[str, Mapping[str, object]],
    source_priority: Mapping[str, int], edge_tiers: Sequence[str] | None = None,
) -> GoldenRecord:
    """Select six golden fields and their source lineage for one cluster."""
    member_ids = tuple(sorted(cluster))
    records: list[Candidate] = [records_by_id[identifier] for identifier in member_ids]
    fields_and_filters = {
        "full_name": lambda row: bool(_text(row, "full_name")),
        "email": lambda row: bool(_text(row, "email")) and normalize_email(_text(row, "email")) is not None,
        "phone": lambda row: bool(_text(row, "phone")) and normalize_phone(_text(row, "phone")) is not None,
        "address": lambda row: bool(_text(row, "address")),
        "postcode": lambda row: normalize_postcode(_text(row, "postcode")) is not None,
        "dob": lambda row: bool(_text(row, "dob_norm")),
    }
    chosen: dict[str, FieldLineage] = {}
    for field, eligible in fields_and_filters.items():
        candidates = [row for row in records if eligible(row)]
        if field == "postcode":
            address_lineage = chosen["address"]
            if address_lineage.source_record_id:
                address_record = records_by_id[address_lineage.source_record_id]
                address_postcode = normalize_postcode(_text(address_record, "postcode"))
                if address_postcode:
                    candidates = [dict(address_record, postcode=address_record.get("postcode"), _address_winner=True)]
        if field == "address" and candidates:
            chosen[field] = _lineage(field, candidates, source_priority)
            winner_id = chosen[field].source_record_id
            records = [dict(row, _address_winner=(str(row["source_record_id"]) == winner_id)) for row in records]
        else:
            chosen[field] = _lineage(field, candidates, source_priority)

    by_field = {field: chosen[field].value for field in fields_and_filters}
    latest = max((str(row.get("updated_at_utc") or "") for row in records), default="") or None
    match_tier = "single" if len(member_ids) == 1 else (
        "exact" if edge_tiers and all(tier == "exact" for tier in edge_tiers) else "probable"
    )
    members = tuple(GoldenMember(identifier, str(records_by_id[identifier]["version_id"])) for identifier in member_ids)
    return GoldenRecord(
        golden_id(member_ids), by_field["full_name"], by_field["email"], by_field["phone"],
        by_field["address"], by_field["postcode"], by_field["dob"], len(member_ids), match_tier,
        latest, members, tuple(chosen[field] for field in fields_and_filters),
    )
