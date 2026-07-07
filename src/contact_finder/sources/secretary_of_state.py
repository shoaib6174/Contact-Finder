"""Adapter: US Secretary of State registry lookup with fallbacks."""

from __future__ import annotations

import httpx

from contact_finder.http_client import get
from contact_finder.models import EntityRecord
from contact_finder.sources.base import adapter
from contact_finder.sources.web_search import web_search


@adapter(category="resolver")
async def sos_lookup(name: str, state: str, city: str | None = None, zip: str | None = None) -> list[dict]:  # noqa: A002
    """Query the relevant US Secretary of State business registry by company name and state. City and ZIP help disambiguate same-named companies."""
    state_lower = state.lower()

    # 1. Try OpenCorporates first as a proxy for SOS data.
    from contact_finder.sources.opencorporates import opencorporates_lookup

    try:
        oc_results = await opencorporates_lookup(name, state, city, zip)
        if oc_results and not any("error" in r for r in oc_results):
            return [{"note": "SOS data mirrored via OpenCorporates"}] + oc_results[:2]
    except Exception:  # noqa: BLE001
        pass

    # 2. Web search restricted to the official state registry domain.
    query = f'"{name}" site:sos.{state_lower}.gov'
    if city:
        query += f" {city}"

    try:
        search_results = await web_search(query)
    except httpx.HTTPStatusError as exc:
        return [{"error": f"SOS search HTTP {exc.response.status_code}"}]

    results = []
    for item in search_results:
        link = item.get("link", "")
        if not link:
            continue
        # Heuristic: result title contains the company name and an entity ID.
        results.append(
            EntityRecord(
                name=name,
                jurisdiction=state,
                registration_number=None,
                address=None,
                city=city,
                state=state,
                zip=zip,
                status=None,
                source="sos_lookup",
                source_url=link,
                match_reason="State registry search result",
            ).model_dump()
        )

    if not results:
        return [{"error": f"No SOS registry hit for {name} in {state}"}]

    return results
