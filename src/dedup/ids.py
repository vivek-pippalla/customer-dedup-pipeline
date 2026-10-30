"""Deterministic data identifiers and execution run identifiers."""

import hashlib
import re
import secrets
from collections.abc import Callable, Iterable
from datetime import datetime, timezone


ROW_HASH_FIELDS = (
    "source_system", "source_native_id", "full_name", "email", "phone",
    "address", "postcode", "dob", "updated_at",
)


def normalize_source_system(source_system: str) -> str:
    """Trim and uppercase a source system key."""
    return source_system.strip().upper()


def normalize_native_id(source_native_id: str) -> str:
    """Trim a source native identifier."""
    return source_native_id.strip()


def normalize_source_native_id(source_native_id: str) -> str:
    """Trim a source native identifier for use in a source key."""
    return normalize_native_id(source_native_id)


def normalize_source_key(source_system: str, source_native_id: str) -> tuple[str, str]:
    """Normalize the two parts of a source record key."""
    return normalize_source_system(source_system), normalize_source_native_id(source_native_id)


def _sha1_prefix(value: str) -> str:
    """Return the first 16 lowercase hex characters of a SHA-1 digest."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def source_record_id(source_system: str, source_native_id: str) -> str:
    """Create the stable ID for a source record."""
    system, native_id = normalize_source_key(source_system, source_native_id)
    return _sha1_prefix(f"{system}|{native_id}")


def row_hash(
    source_system: str,
    source_native_id: str,
    full_name: str,
    email: str | None,
    phone: str | None,
    address: str | None,
    postcode: str | None,
    dob: str | None,
    updated_at: str,
) -> str:
    """Hash the original CSV field values in the specified fixed order."""
    values = (source_system, source_native_id, full_name, email, phone, address, postcode, dob, updated_at)
    return _sha1_prefix("\x1f".join(value if value is not None else "" for value in values))


def version_id(source_record_id: str, row_hash: str) -> str:
    """Create the ID for one source record content version."""
    return _sha1_prefix(f"{source_record_id}|{row_hash}")


def golden_id(source_record_ids: Iterable[str]) -> str:
    """Create a golden ID from sorted member source record IDs."""
    return "g_" + _sha1_prefix("|".join(sorted(source_record_ids)))


def pair_id(source_record_id_a: str, source_record_id_b: str) -> str:
    """Create a symmetric candidate pair ID from source record IDs."""
    first, second = sorted((source_record_id_a, source_record_id_b))
    return _sha1_prefix(f"{first}|{second}")


def new_run_id(
    clock: Callable[[], datetime] | None = None,
    suffix: str | None = None,
) -> str:
    """Create a run ID from a compact UTC timestamp and four random hex digits."""
    current = clock() if clock is not None else datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    timestamp = current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    random_suffix = suffix if suffix is not None else secrets.token_hex(2)
    if re.fullmatch(r"[0-9a-fA-F]{4}", random_suffix) is None:
        raise ValueError("run ID suffix must be exactly four hexadecimal characters")
    return f"run_{timestamp}_{random_suffix.lower()}"
