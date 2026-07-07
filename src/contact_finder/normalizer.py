"""Normalize raw company names and addresses."""

from __future__ import annotations

import re
from typing import Optional

import usaddress

from contact_finder.models import DebtorRow, NormalizedInput
from contact_finder.pii_guard import normalize_name


LEGAL_FORMS = [
    "llc",
    "l.l.c.",
    "inc",
    "inc.",
    "incorporated",
    "corp",
    "corp.",
    "corporation",
    "pllc",
    "p.l.l.c.",
    "ltd",
    "ltd.",
    "limited",
    "co",
    "co.",
    "company",
    "llp",
    "l.l.p.",
    "lp",
    "l.p.",
]

REGEX_DUNS = re.compile(r"DUNS\s*N[°o]?\s*(\d+)", re.IGNORECASE)
REGEX_FILING = re.compile(r"(?:file|registration|entity)\s*#?\s*(\d+)", re.IGNORECASE)


def normalize_company(row: DebtorRow) -> NormalizedInput:
    """Parse raw company name and address into clean fields."""
    name = row.company_name.strip()
    address = row.address.strip()

    registration_code = _extract_registration_code(name)
    legal_form = _extract_legal_form(name)
    clean_name = _clean_name(name)

    parsed = _parse_address(address)

    return NormalizedInput(
        raw_name=name,
        clean_name=clean_name,
        legal_form=legal_form,
        registration_code=registration_code,
        street=parsed.get("street"),
        city=parsed.get("city"),
        state=parsed.get("state"),
        zip=parsed.get("zip"),
    )


def _extract_registration_code(name: str) -> Optional[str]:
    for pattern in [REGEX_DUNS, REGEX_FILING]:
        match = pattern.search(name)
        if match:
            return match.group(1)
    return None


def _extract_legal_form(name: str) -> Optional[str]:
    lowered = name.lower()
    for form in LEGAL_FORMS:
        # escape dots for regex
        escaped = re.escape(form)
        if re.search(rf"\b{escaped}\b", lowered):
            return form.replace(".", "").upper()
    return None


def _clean_name(name: str) -> str:
    # remove registration code snippets first
    name = REGEX_DUNS.sub("", name)
    name = REGEX_FILING.sub("", name)
    # strip legal forms
    for form in LEGAL_FORMS:
        escaped = re.escape(form)
        name = re.sub(rf"\b{escaped}\b", "", name, flags=re.IGNORECASE)
    # clean punctuation/whitespace
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name.title() if name else ""


def _parse_address(address: str) -> dict:
    """Parse US address into street, city, state, zip."""
    try:
        tagged, _ = usaddress.tag(address)
    except Exception:  # noqa: BLE001
        return _fallback_parse(address)

    street_parts = []
    for key in [
        "AddressNumber",
        "AddressNumberPrefix",
        "StreetNamePreDirectional",
        "StreetName",
        "StreetNamePostType",
        "StreetNamePostDirectional",
    ]:
        if tagged.get(key):
            street_parts.append(tagged[key])

    return {
        "street": " ".join(street_parts) or None,
        "city": tagged.get("PlaceName") or None,
        "state": tagged.get("StateName") or None,
        "zip": tagged.get("ZipCode") or None,
    }


def _fallback_parse(address: str) -> dict:
    """Lightweight regex fallback when usaddress fails."""
    # state + zip at end
    m = re.search(r",?\s*([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)\s*$", address)
    state = m.group(1) if m else None
    zip_code = m.group(2) if m else None

    city = None
    if state:
        prefix = address[: address.rfind(state)].rstrip(", ")
        # last comma before state is usually city
        if "," in prefix:
            city = prefix.split(",")[-1].strip()

    return {
        "street": None,
        "city": city,
        "state": state,
        "zip": zip_code,
    }


def state_name_to_abbrev(state: str | None) -> str | None:
    """Map full state names to two-letter codes."""
    mapping = {
        "alabama": "AL",
        "alaska": "AK",
        "arizona": "AZ",
        "arkansas": "AR",
        "california": "CA",
        "colorado": "CO",
        "connecticut": "CT",
        "delaware": "DE",
        "florida": "FL",
        "georgia": "GA",
        "hawaii": "HI",
        "idaho": "ID",
        "illinois": "IL",
        "indiana": "IN",
        "iowa": "IA",
        "kansas": "KS",
        "kentucky": "KY",
        "louisiana": "LA",
        "maine": "ME",
        "maryland": "MD",
        "massachusetts": "MA",
        "michigan": "MI",
        "minnesota": "MN",
        "mississippi": "MS",
        "missouri": "MO",
        "montana": "MT",
        "nebraska": "NE",
        "nevada": "NV",
        "new hampshire": "NH",
        "new jersey": "NJ",
        "new mexico": "NM",
        "new york": "NY",
        "north carolina": "NC",
        "north dakota": "ND",
        "ohio": "OH",
        "oklahoma": "OK",
        "oregon": "OR",
        "pennsylvania": "PA",
        "rhode island": "RI",
        "south carolina": "SC",
        "south dakota": "SD",
        "tennessee": "TN",
        "texas": "TX",
        "utah": "UT",
        "vermont": "VT",
        "virginia": "VA",
        "washington": "WA",
        "west virginia": "WV",
        "wisconsin": "WI",
        "wyoming": "WY",
    }
    if not state:
        return None
    return mapping.get(state.lower().strip())


def address_match_level(normalized: NormalizedInput, record_city: str | None, record_state: str | None, record_zip: str | None) -> str:
    """Return address match tier: exact, city_state, state_only, unknown."""
    if not record_state:
        return "unknown"

    norm_state = (normalized.state or "").upper()
    rec_state = (record_state or "").upper()

    if rec_state != norm_state:
        return "unknown"

    norm_city = (normalized.city or "").lower().strip()
    rec_city = (record_city or "").lower().strip()

    norm_zip = (normalized.zip or "").split("-")[0]
    rec_zip = (record_zip or "").split("-")[0]

    city_match = norm_city and rec_city and norm_city == rec_city
    zip_match = norm_zip and rec_zip and norm_zip == rec_zip

    if city_match and zip_match:
        return "exact"
    if city_match:
        return "city_state"
    return "state_only"
