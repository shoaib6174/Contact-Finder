"""Adapter: normalize raw company name and address."""

from __future__ import annotations

from contact_finder.models import DebtorRow
from contact_finder.normalizer import normalize_company
from contact_finder.sources.base import adapter


@adapter(category="resolver")
async def normalize_company_adapter(company_name: str, address: str) -> dict:
    """Parse the raw company name and address into clean fields, legal form, registration code, and city/state/ZIP."""
    row = DebtorRow(
        row_id="adapter",
        company_name=company_name,
        address=address,
        company_issuing_the_invoice="",
    )
    norm = normalize_company(row)
    return norm.model_dump()
