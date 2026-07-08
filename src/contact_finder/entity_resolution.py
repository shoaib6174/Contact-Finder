"""Entity-resolution helpers used by both agent modes."""

from __future__ import annotations

from typing import Any

from contact_finder.models import DebtorRow, NormalizedInput
from contact_finder.normalizer import address_match_level
from contact_finder.pii_guard import normalize_name
from contact_finder.scorer import _domain_matches


def _name_matches(debtor_name: str, record_name: str) -> bool:
    """Heuristic name match between debtor name and a public-record name."""
    if not debtor_name or not record_name:
        return False
    debtor_norm = normalize_name(debtor_name)
    record_norm = normalize_name(record_name)
    # Substring in either direction covers "LLC" vs "Inc." omissions and abbreviations.
    return debtor_norm in record_norm or record_norm in debtor_norm


_STREET_ABBREV = {
    "st": "street",
    "str": "street",
    "ave": "avenue",
    "av": "avenue",
    "rd": "road",
    "blvd": "boulevard",
    "dr": "drive",
    "ln": "lane",
    "ct": "court",
    "cir": "circle",
    "pl": "place",
    "hwy": "highway",
    "pkwy": "parkway",
    "ste": "suite",
    "fl": "floor",
}


def _street_tokens(text: str) -> set[str]:
    """Normalize a street address and expand common suffix abbreviations."""
    tokens = normalize_name(text).split()
    return {_STREET_ABBREV.get(token, token) for token in tokens}


def _street_matches(debtor_street: str | None, text: str | None) -> bool:
    """Check if the debtor's street tokens appear in a record address string."""
    if not debtor_street or not text:
        return True  # nothing to verify; don't block
    street_tokens = _street_tokens(debtor_street)
    text_tokens = _street_tokens(text)
    if not street_tokens or not text_tokens:
        return True
    return street_tokens.issubset(text_tokens)


def _address_matches(row: DebtorRow, norm: dict, text: str | None) -> bool:
    """Check if a free-text snippet (e.g. maps address) contains the debtor's city/state/ZIP."""
    if not text:
        return False
    text = text.lower()
    checks = []
    if norm.get("city"):
        checks.append(norm["city"].lower() in text)
    if norm.get("state"):
        checks.append(norm["state"].lower() in text)
    if norm.get("zip"):
        checks.append(norm["zip"] in text)
    # Require at least two of city/state/zip to reduce false positives.
    return sum(checks) >= 2


_GENERIC_NAME_TERMS = {
    "plumbing",
    "plumber",
    "electric",
    "electrical",
    "dental",
    "dentistry",
    "family",
    "services",
    "service",
    "company",
    "co",
    "corp",
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "supply",
    "supplies",
    "contractor",
    "contracting",
    "industrial",
    "landscape",
    "landscaping",
    "cable",
    "express",
    "office",
    "corporate",
    "home",
    "improvement",
}


def _distinctive_tokens(name: str) -> set[str]:
    return {t for t in normalize_name(name).split() if t not in _GENERIC_NAME_TERMS}


def _name_overlap(debtor_name: str, text: str | None) -> bool:
    """True if any distinctive normalized token from the debtor name appears in the text."""
    if not text:
        return False
    debtor_tokens = _distinctive_tokens(debtor_name)
    text_tokens = set(normalize_name(text).split())
    if not debtor_tokens or not text_tokens:
        return False
    return bool(debtor_tokens & text_tokens)


def entity_resolved(row: DebtorRow, norm: dict, tool_name: str, result: Any) -> bool:
    """Return True if a public record corroborates the debtor entity at its address."""
    items = result if isinstance(result, list) else [result] if isinstance(result, dict) else []

    normalized = NormalizedInput(
        raw_name=row.company_name,
        clean_name=norm.get("clean_name") or row.company_name,
        city=norm.get("city"),
        state=norm.get("state"),
        zip=norm.get("zip"),
    )

    for item in items:
        if not isinstance(item, dict):
            continue
        if "error" in item:
            continue

        if tool_name in {"opencorporates_lookup", "sos_lookup"}:
            name = item.get("name") or item.get("clean_name") or item.get("raw_name") or ""
            state = (item.get("state") or "").upper()
            if not _name_matches(row.company_name, name):
                continue
            if state != normalized.state.upper():
                continue
            # Tighten disambiguation: require city or ZIP match, not just state.
            level = address_match_level(
                normalized,
                item.get("city"),
                item.get("state"),
                item.get("zip"),
            )
            if level not in {"exact", "city_state"}:
                continue
            return True

        if tool_name == "maps_search":
            title = item.get("title") or ""
            address = item.get("address") or ""
            # Maps listings often use building names ("Apple Park") or nearby street
            # numbers, so we require city/state/ZIP match plus a name match, but we
            # do not require exact street alignment here.
            if _address_matches(row, norm, address) and (
                _name_matches(row.company_name, title) or _name_overlap(row.company_name, title)
            ):
                return True

        if tool_name == "website_entity_resolver":
            name = item.get("name") or ""
            source_url = item.get("source_url") or ""
            if _name_matches(row.company_name, name) and _domain_matches(
                norm.get("clean_name") or row.company_name, source_url
            ):
                return True

    return False
