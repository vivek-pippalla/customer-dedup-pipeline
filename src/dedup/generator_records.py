"""Create deterministic synthetic customer entities and noisy source rows."""

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Sequence

from dedup.wordlists import (
    CITIES_AND_POSTCODES,
    EMAIL_DOMAINS,
    FIRST_NAMES,
    LAST_NAMES,
    NICKNAME_VARIANTS,
    ROLE_EMAILS,
    STREET_NAMES,
)


CSV_COLUMNS = (
    "source_system", "source_native_id", "full_name", "email", "phone",
    "address", "postcode", "dob", "updated_at",
)
TRUTH_COLUMNS = (
    "source_file", "row_number", "source_record_id", "true_entity_id",
    "is_invalid", "expected_reject_reason", "injected_issue",
)
SOURCE_SYSTEMS = ("CRM", "WEB", "IMPORT")


@dataclass
class GeneratedRecord:
    """One emitted CSV data row plus its ground-truth annotations."""

    fields: list[str]
    entity_id: str
    issue: str = ""
    invalid_reason: str = ""
    late_old: bool = False
    late_new: bool = False
    batch_index: int = 0


@dataclass
class _Profile:
    """Stable synthetic identity attributes shared by an entity's records."""

    number: int
    first_name: str
    last_name: str
    email: str
    phone: str
    address: str
    postcode: str
    dob: str
    boundary: bool = False
    family_source: int | None = None
    family_field: str = ""
    records: list[GeneratedRecord] = field(default_factory=list)


def _random_timestamp(rng: random.Random) -> str:
    """Choose a deterministic UTC timestamp within the fixed valid range."""
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    seconds = int((end - start).total_seconds())
    return (start + timedelta(seconds=rng.randint(0, seconds))).strftime("%Y-%m-%dT%H:%M:%SZ")


def _typo(rng: random.Random, value: str) -> str:
    """Introduce one small interior deletion into a word."""
    if len(value) < 5:
        return value
    index = rng.randrange(1, len(value) - 1)
    return value[:index] + value[index + 1:]


def _new_profile(rng: random.Random, number: int, profiles: Sequence[_Profile], family_rate: float) -> _Profile:
    """Create a synthetic entity and optionally connect it to a family member."""
    first_name = rng.choice(FIRST_NAMES)
    last_name = rng.choice(LAST_NAMES)
    city, postcode = rng.choice(CITIES_AND_POSTCODES)
    email_domain = rng.choice(EMAIL_DOMAINS)
    email = f"{first_name.lower()}.{last_name.lower()}.{number:05d}@{email_domain}"
    if number % 19 == 0:
        email = ROLE_EMAILS[(number // 19 - 1) % len(ROLE_EMAILS)]
    phone = "9" + "".join(str(rng.randrange(10)) for _ in range(9))
    street_name = rng.choice(STREET_NAMES)
    address = f"{rng.randint(1, 240)} {street_name} Road, {city}"
    if number % 37 == 0:
        address = (f"{number} Example Avenue, {city}. " * 20)[:300]
    birth_year = rng.randint(1950, 2005)
    dob = date(birth_year, rng.randint(1, 12), rng.randint(1, 28)).isoformat()
    profile = _Profile(number, first_name, last_name, email, phone, address, postcode, dob, number % 37 == 0)
    if profiles and rng.random() < family_rate:
        source = rng.choice(profiles)
        profile.family_source = source.number
        profile.family_field = rng.choice(("email", "phone"))
        setattr(profile, profile.family_field, getattr(source, profile.family_field))
    return profile


def _full_name(rng: random.Random, profile: _Profile) -> str:
    """Render a name with case, order, nickname, and typo noise."""
    first = profile.first_name
    for canonical in sorted(NICKNAME_VARIANTS):
        variants = NICKNAME_VARIANTS[canonical]
        if first == canonical and rng.random() < 0.20:
            first = rng.choice(variants)
            break
    if profile.boundary:
        return first[:1]
    if rng.random() < 0.07:
        first = first[:1]
    if rng.random() < 0.04:
        first = _typo(rng, first)
    last = _typo(rng, profile.last_name) if rng.random() < 0.04 else profile.last_name
    name = f"{first} {last}"
    if rng.random() < 0.08:
        name = f"{last}, {first}"
    if rng.random() < 0.10:
        name = name.upper()
    if rng.random() < 0.10:
        name = f"  {name}  "
    return name


def _formatted_phone(rng: random.Random, phone: str) -> str:
    """Format a synthetic phone number in one of several common ways."""
    style = rng.randrange(4)
    if style == 0:
        return f"+91 {phone[:5]}-{phone[5:]}"
    if style == 1:
        return f"0{phone}"
    if style == 2:
        return f"{phone[:5]} {phone[5:]}"
    return phone


def _record_fields(rng: random.Random, profile: _Profile, source_system: str) -> tuple[list[str], str]:
    """Create one noisy valid customer record for a source system."""
    source_native_id = f"{source_system.lower()}-{profile.number:06d}"
    email = profile.email
    if rng.random() < 0.15:
        email = email.upper()
    if rng.random() < 0.08:
        email = f" {email} "
    if rng.random() < 0.10:
        email = ""
    phone = _formatted_phone(rng, profile.phone)
    if rng.random() < 0.10:
        phone = ""
    address = profile.address
    for short, long in (("Road", "Rd"), ("Street", "St"), ("Apartment", "Apt")):
        address = address.replace(short, long) if rng.random() < 0.2 else address
    if rng.random() < 0.10 and not profile.boundary:
        address = ""
    postcode = profile.postcode if rng.random() >= 0.08 else ""
    dob = profile.dob if rng.random() >= 0.12 else ""
    updated_at = _random_timestamp(rng)
    if profile.family_source is not None:
        issue = f"family_shared_{profile.family_field}"
    else:
        issue = "shared_role_mailbox" if email.strip().lower() in ROLE_EMAILS else ""
    fields = [source_system, source_native_id, _full_name(rng, profile), email, phone, address, postcode, dob, updated_at]
    return fields, issue


def make_records(rows: int, seed_rng: random.Random, dup_rate: float, family_rate: float, late_rate: float) -> list[GeneratedRecord]:
    """Create exactly the requested number of noisy valid base rows."""
    profiles: list[_Profile] = []
    records: list[GeneratedRecord] = []
    for index in range(rows):
        eligible = [profile for profile in profiles if len(profile.records) < 4]
        force_late = index == 1 and late_rate > 0 and bool(profiles)
        if force_late:
            profile = profiles[0]
        elif eligible and seed_rng.random() < dup_rate:
            profile = seed_rng.choice(eligible)
        else:
            profile = _new_profile(seed_rng, len(profiles) + 1, profiles, family_rate)
            profiles.append(profile)

        late = force_late or (
            len(profile.records) > 0
            and late_rate > 0
            and not any(record.late_new for record in profile.records)
            and seed_rng.random() < late_rate
        )
        if late:
            prior = profile.records[0]
            source_system = prior.fields[0]
            fields, issue = _record_fields(seed_rng, profile, source_system)
            prior.fields[8] = "2025-12-31T00:00:00Z"
            fields[8] = "2025-12-30T00:00:00Z"
            prior.late_new = True
        else:
            used_systems = {record.fields[0] for record in profile.records}
            available = [system for system in SOURCE_SYSTEMS if system not in used_systems]
            source_system = seed_rng.choice(available or SOURCE_SYSTEMS)
            fields, issue = _record_fields(seed_rng, profile, source_system)
        record = GeneratedRecord(fields, f"entity_{profile.number:05d}", issue, late_old=late)
        records.append(record)
        profile.records.append(record)

    if records:
        records[0].fields[4] = ""
        records[0].issue = records[0].issue or "boundary_empty_optional"
    if family_rate > 0 and len(profiles) > 1 and not any(profile.family_source is not None for profile in profiles):
        source, family = profiles[0], profiles[-1]
        family.family_source = source.number
        family.family_field = seed_rng.choice(("email", "phone"))
        setattr(family, family.family_field, getattr(source, family.family_field))
    profile_by_number = {profile.number: profile for profile in profiles}
    for record in records:
        profile = profile_by_number[int(record.entity_id.split("_")[1])]
        if profile.family_source is not None:
            shared = profile_by_number[profile.family_source]
            column_index = 3 if profile.family_field == "email" else 4
            record.fields[column_index] = getattr(shared, profile.family_field)
            record.issue = f"family_shared_{profile.family_field}"
        elif record.fields[3].strip().lower() in ROLE_EMAILS:
            record.issue = "shared_role_mailbox"
    return records
