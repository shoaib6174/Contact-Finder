"""Tests for normalizer and address matching."""

import pytest

from contact_finder.models import DebtorRow
from contact_finder.normalizer import (
    address_match_level,
    normalize_company,
    state_name_to_abbrev,
)


def test_normalize_company_extracts_duns():
    row = DebtorRow(
        row_id="1",
        company_name="LAKE CABLE LLC (DUNS N° 927410308)",
        address="529 Thomas Drive, Bensenville, IL 60106",
        company_issuing_the_invoice="FedEx",
    )
    norm = normalize_company(row)
    assert norm.registration_code == "927410308"
    assert norm.legal_form == "LLC"
    assert "DUNS" not in norm.clean_name
    assert norm.state == "IL"
    assert norm.city == "Bensenville"


def test_normalize_company_strips_legal_form():
    row = DebtorRow(
        row_id="2",
        company_name="Summit Electric (Inc.)",
        address="2900 Stanford Dr NE, Albuquerque, NM 87107",
        company_issuing_the_invoice="FedEx",
    )
    norm = normalize_company(row)
    assert norm.legal_form == "INC"
    assert "Inc" not in norm.clean_name
    assert norm.state == "NM"


def test_address_match_level_exact():
    from contact_finder.models import NormalizedInput

    norm = NormalizedInput(
        raw_name="x", clean_name="x", city="Lincoln", state="NE", zip="68504"
    )
    assert address_match_level(norm, "Lincoln", "NE", "68504") == "exact"


def test_address_match_level_state_only():
    from contact_finder.models import NormalizedInput

    norm = NormalizedInput(raw_name="x", clean_name="x", city="Lincoln", state="NE")
    assert address_match_level(norm, "Omaha", "NE", None) == "state_only"


def test_address_match_level_unknown_state():
    from contact_finder.models import NormalizedInput

    norm = NormalizedInput(raw_name="x", clean_name="x", city="Lincoln", state="NE")
    assert address_match_level(norm, "Austin", "TX", None) == "unknown"


def test_state_name_to_abbrev():
    assert state_name_to_abbrev("California") == "CA"
    assert state_name_to_abbrev("new york") == "NY"
    assert state_name_to_abbrev(None) is None
