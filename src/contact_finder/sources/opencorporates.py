"""Adapter: OpenCorporates company lookup."""

from __future__ import annotations

import httpx

from contact_finder.http_client import get
from contact_finder.models import EntityRecord
from contact_finder.sources.base import adapter


@adapter(category="resolver")
async def opencorporates_lookup(name: str, state: str, city: str | None = None, zip: str | None = None) -> list[dict]:  # noqa: A002
    """Look up a company in OpenCorporates by name and US state jurisdiction. City and ZIP help disambiguate same-named companies."""
    url = "https://api.opencorporates.com/v0.4/companies/search"
    params = {
        "q": name,
        "jurisdiction_code": f"us_{state.lower()}",
        "format": "json",
    }

    try:
        resp = await get(url, params=params, use_cache=True)
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        return [{"error": f"OpenCorporates HTTP {exc.response.status_code}"}]

    results = []
    companies = data.get("results", {}).get("companies", [])[:3]
    for item in companies:
        company = item.get("company", {})
        registered_address = company.get("registered_address", {}) or {}
        record = EntityRecord(
            name=company.get("name", ""),
            jurisdiction=company.get("jurisdiction_code", ""),
            registration_number=company.get("company_number"),
            address=registered_address.get("street_address"),
            city=registered_address.get("locality"),
            state=registered_address.get("region"),
            zip=registered_address.get("postal_code"),
            status=company.get("current_status"),
            source="opencorporates",
            source_url=company.get("opencorporates_url", ""),
            match_reason="OpenCorporates registry result",
        )
        results.append(record.model_dump())

    return results
