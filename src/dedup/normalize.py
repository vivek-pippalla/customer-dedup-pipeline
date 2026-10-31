"""Pure customer-field normalization functions."""

import re
import tomllib
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


TITLES = {"mr", "mrs", "ms", "dr"}
ADDRESS_ABBREVIATIONS = {"rd": "road", "st": "street", "apt": "apartment"}
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


@dataclass(frozen=True)
class NormalizedRow:
    """Derived clean fields for one valid raw customer record."""
    email_norm: str | None
    phone_norm: str | None
    name_norm: str
    first_name_canon: str | None
    first_is_initial: bool
    last_name_norm: str
    address_norm: str | None
    postcode_norm: str | None
    updated_at_utc: str | None
    dob_norm: str | None
    soundex_last: str | None
    phone_invalid: bool = False


def normalize_email(value: str | None) -> str | None:
    """Trim/lowercase a syntactically valid email; preserve dots and tags."""
    text = (value or "").strip().lower()
    return text if text and EMAIL_RE.fullmatch(text) else None


def normalize_phone(value: str | None) -> str | None:
    """Return ten digits after the specified country/leading-zero cleanup."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits if len(digits) == 10 else None


def normalize_name(value: str | None) -> str:
    """Normalize names, reordering a single Last, First comma first."""
    text = (value or "").strip()
    if text.count(",") == 1:
        last, first = text.split(",", 1)
        text = f"{first} {last}"
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    return " ".join(token for token in tokens if token not in TITLES)


def load_nicknames(path: str | Path | None = None) -> dict[str, str]:
    """Load explicit single-step nickname mappings from TOML."""
    nickname_path = Path(path) if path else Path(__file__).resolve().parents[2] / "config" / "nicknames.toml"
    with nickname_path.open("rb") as source:
        data = tomllib.load(source).get("nicknames", {})
    return {str(key).lower(): str(value).lower() for key, value in data.items()}


def canonical_first_name(name_norm: str, nicknames: Mapping[str, str] | None = None) -> str | None:
    """Map the first token once; mappings are deliberately never chained."""
    tokens = name_norm.split()
    if not tokens:
        return None
    first = tokens[0]
    return (nicknames if nicknames is not None else load_nicknames()).get(first, first)


def first_is_initial(name_norm: str) -> bool:
    """Whether a normalized name has a one-letter first token."""
    tokens = name_norm.split()
    return bool(tokens and len(tokens[0]) == 1)


def last_name(name_norm: str) -> str:
    """Return the last normalized token, or empty string."""
    tokens = name_norm.split()
    return tokens[-1] if len(tokens) > 1 else ""


def normalize_address(value: str | None) -> str | None:
    """Lowercase, expand known abbreviations, remove punctuation and collapse."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    expanded = [ADDRESS_ABBREVIATIONS.get(token, token) for token in tokens]
    return " ".join(expanded) or None


def normalize_postcode(value: str | None) -> str | None:
    """Keep a postcode only when it contains exactly six digits."""
    digits = re.sub(r"\D", "", value or "")
    return digits if len(digits) == 6 else None


def normalize_timestamp(value: str | None) -> str | None:
    """Parse ISO timestamp as UTC; naive timestamps are assumed UTC."""
    try:
        parsed = datetime.fromisoformat((value or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_dob(value: str | None) -> str | None:
    """Return a valid ISO calendar date or None."""
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def soundex(value: str | None) -> str | None:
    """Compute a standard four-character Soundex code by hand."""
    letters = [char for char in (value or "").upper() if "A" <= char <= "Z"]
    if not letters:
        return None
    groups = {**dict.fromkeys("BFPV", "1"), **dict.fromkeys("CGJKQSXZ", "2"),
              **dict.fromkeys("DT", "3"), **dict.fromkeys("L", "4"),
              **dict.fromkeys("MN", "5"), **dict.fromkeys("R", "6")}
    result = [letters[0]]
    previous = groups.get(letters[0], "")
    for char in letters[1:]:
        code = groups.get(char, "")
        if code and code != previous:
            result.append(code)
        previous = code
    return ("".join(result) + "000")[:4]


def normalize_row(raw: object, nicknames: Mapping[str, str] | None = None) -> NormalizedRow:
    """Derive every clean field from a raw-row object or field mapping."""
    fields = raw if isinstance(raw, Mapping) else getattr(raw, "fields")
    name = normalize_name(fields.get("full_name"))
    phone_raw = (fields.get("phone") or "").strip()
    phone = normalize_phone(phone_raw)
    return NormalizedRow(
        normalize_email(fields.get("email")), phone, name,
        canonical_first_name(name, nicknames), first_is_initial(name), last_name(name),
        normalize_address(fields.get("address")), normalize_postcode(fields.get("postcode")),
        normalize_timestamp(fields.get("updated_at")), normalize_dob(fields.get("dob")),
        soundex(last_name(name)), bool(phone_raw and phone is None),
    )
