"""Deterministic union-find clustering and transitive-conflict checks."""

from itertools import combinations
from typing import Mapping, Sequence


Pair = tuple[str, str]
Cluster = tuple[str, ...]


def build_clusters(record_ids: Sequence[str], auto_pairs: Sequence[Pair]) -> list[Cluster]:
    """Build connected components with the smallest ID as each root."""
    parent = {str(identifier): str(identifier) for identifier in record_ids}

    def find(identifier: str) -> str:
        root = identifier
        while parent[root] != root:
            root = parent[root]
        while parent[identifier] != identifier:
            next_id = parent[identifier]
            parent[identifier] = root
            identifier = next_id
        return root

    for left, right in sorted({tuple(sorted((str(a), str(b)))) for a, b in auto_pairs}):
        if left not in parent or right not in parent:
            continue
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            small, large = sorted((root_left, root_right))
            parent[large] = small
    groups: dict[str, list[str]] = {}
    for identifier in sorted(parent):
        groups.setdefault(find(identifier), []).append(identifier)
    return [tuple(members) for _, members in sorted(groups.items())]


def _pair_conflicts(record_a: Mapping[str, object], record_b: Mapping[str, object]) -> bool:
    """Check hard DOB and shared-style canonical first-name conflicts."""
    dob_a = str(record_a.get("dob_norm") or "").strip()
    dob_b = str(record_b.get("dob_norm") or "").strip()
    if dob_a and dob_b and dob_a != dob_b:
        return True
    first_a = str(record_a.get("first_name_canon") or "").strip()
    first_b = str(record_b.get("first_name_canon") or "").strip()
    initial_a = bool(record_a.get("first_is_initial"))
    initial_b = bool(record_b.get("first_is_initial"))
    return bool(first_a and first_b and not initial_a and not initial_b and first_a != first_b)


def check_clusters(
    clusters: Sequence[Cluster], records: Mapping[str, Mapping[str, object]],
) -> tuple[list[Cluster], list[Pair]]:
    """Split clusters with any all-pairs conflict and demote their member pairs."""
    final: list[Cluster] = []
    demoted: set[Pair] = set()
    for cluster in sorted((tuple(sorted(cluster)) for cluster in clusters), key=lambda members: members[0]):
        if len(cluster) < 3:
            final.append(cluster)
            continue
        has_conflict = any(
            _pair_conflicts(records[left], records[right])
            for left, right in combinations(cluster, 2)
        )
        if has_conflict:
            final.extend((identifier,) for identifier in cluster)
            demoted.update(combinations(cluster, 2))
        else:
            final.append(cluster)
    final.sort(key=lambda members: members[0])
    return final, sorted(demoted)
