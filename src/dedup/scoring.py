"""Evidence feature calculation for candidate customer pairs."""

from dataclasses import dataclass
from typing import Mapping

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler


@dataclass(frozen=True)
class PairFeatures:
    """Weighted pair scores, feature coverage, and evidence-only flags."""
    email: float | None
    phone: float | None
    name: float | None
    address: float | None
    dob: float | None
    score: float
    coverage: float
    strong_id: bool
    dob_conflict: bool
    shared_conflict: bool
    names_compatible: bool
    email_equal: bool = False
    name_equal: bool = False
    phone_exact_for_tier: bool = True


def _present(record: Mapping[str, object], field: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def score_pair(
    rec_a: Mapping[str, object], rec_b: Mapping[str, object], weights: Mapping[str, float],
    last_name_min_jw: float = 0.90,
) -> PairFeatures:
    """Score shared evidence using normalized weighted features, without deciding."""
    email_a, email_b = _present(rec_a, "email_norm"), _present(rec_b, "email_norm")
    phone_a, phone_b = _present(rec_a, "phone_norm"), _present(rec_b, "phone_norm")
    name_a, name_b = _present(rec_a, "name_norm"), _present(rec_b, "name_norm")
    address_a, address_b = _present(rec_a, "address_norm"), _present(rec_b, "address_norm")
    postcode_a, postcode_b = _present(rec_a, "postcode_norm"), _present(rec_b, "postcode_norm")
    address_a = " ".join(value for value in (address_a, postcode_a) if value) or None
    address_b = " ".join(value for value in (address_b, postcode_b) if value) or None
    dob_a, dob_b = _present(rec_a, "dob_norm"), _present(rec_b, "dob_norm")

    email = float(email_a == email_b) if email_a and email_b else None
    phone = float(phone_a == phone_b) if phone_a and phone_b else None
    name = None
    if name_a and name_b:
        name = JaroWinkler.normalized_similarity(name_a, name_b)
        first_a, first_b = _present(rec_a, "first_name_canon"), _present(rec_b, "first_name_canon")
        if first_a and first_a == first_b:
            name = min(1.0, name + 0.10)
    address = fuzz.token_set_ratio(address_a, address_b) / 100.0 if address_a and address_b else None
    dob = float(dob_a == dob_b) if dob_a and dob_b else None
    features = {"email": email, "phone": phone, "name": name, "address": address, "dob": dob}
    weight_total = sum(float(value) for value in weights.values())
    present_weight = sum(float(weights.get(key, 0.0)) for key, value in features.items() if value is not None)
    score = (
        sum(float(weights.get(key, 0.0)) * value for key, value in features.items() if value is not None) / present_weight
        if present_weight else 0.0
    )
    coverage = present_weight / weight_total if weight_total else 0.0

    email_equal = bool(email_a and email_b and email_a == email_b)
    phone_equal = bool(phone_a and phone_b and phone_a == phone_b)
    dob_conflict = bool(dob_a and dob_b and dob_a != dob_b)
    strong_id = email_equal or phone_equal or bool(name_a and name_b and name_a == name_b and dob_a and dob_b and dob_a == dob_b)
    first_a, first_b = _present(rec_a, "first_name_canon"), _present(rec_b, "first_name_canon")
    initial_a = bool(rec_a.get("first_is_initial"))
    initial_b = bool(rec_b.get("first_is_initial"))
    shared_conflict = bool((email_equal or phone_equal) and first_a and first_b and not initial_a and not initial_b and first_a != first_b)

    last_a, last_b = _present(rec_a, "last_name_norm"), _present(rec_b, "last_name_norm")
    names_compatible = False
    if first_a and first_a == first_b and not initial_a and not initial_b and last_a and last_b:
        names_compatible = JaroWinkler.normalized_similarity(last_a, last_b) >= last_name_min_jw

    return PairFeatures(email, phone, name, address, dob, score, coverage,
                        strong_id, dob_conflict, shared_conflict, names_compatible,
                        email_equal, bool(name_a and name_b and name_a == name_b),
                        not (phone_a and phone_b) or phone_a == phone_b)
