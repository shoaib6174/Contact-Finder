"""Tests for entity-resolution disambiguation."""

from __future__ import annotations

import pytest

from contact_finder.entity_resolution import entity_resolved
from contact_finder.models import DebtorRow


@pytest.fixture
def row():
    return DebtorRow(
        row_id="1",
        company_name="Example LLC",
        address="123 Main St, Springfield, IL 62701",
        company_issuing_the_invoice="Client",
    )


@pytest.fixture
def norm():
    return {
        "clean_name": "Example",
        "city": "Springfield",
        "state": "IL",
        "zip": "62701",
        "street": "123 Main St",
    }


def test_registry_resolves_when_name_city_zip_and_street_match(row, norm):
    result = [
        {
            "name": "Example LLC",
            "state": "IL",
            "city": "Springfield",
            "zip": "62701",
            "address": "123 Main Street",
        }
    ]
    assert entity_resolved(row, norm, "opencorporates_lookup", result) is True


def test_registry_resolves_even_when_street_differs(row, norm):
    result = [
        {
            "name": "Example LLC",
            "state": "IL",
            "city": "Springfield",
            "zip": "62701",
            "address": "456 Oak Ave",
        }
    ]
    assert entity_resolved(row, norm, "opencorporates_lookup", result) is True


def test_maps_resolves_when_address_and_street_match(row, norm):
    result = [
        {
            "title": "Example LLC",
            "address": "123 Main St, Springfield, IL 62701",
        }
    ]
    assert entity_resolved(row, norm, "maps_search", result) is True


def test_maps_resolves_when_name_and_city_state_match_despite_street_diff(row, norm):
    result = [
        {
            "title": "Example LLC",
            "address": "456 Oak Ave, Springfield, IL 62701",
        }
    ]
    assert entity_resolved(row, norm, "maps_search", result) is True
