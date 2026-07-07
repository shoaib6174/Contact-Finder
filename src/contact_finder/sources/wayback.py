"""Adapter: Wayback Machine archived snapshots."""

from __future__ import annotations

import httpx

from contact_finder.http_client import get
from contact_finder.sources.base import adapter
from contact_finder.sources.website_contact import scrape_contact_page


@adapter(category="finder")
async def wayback_search(url: str) -> list[dict]:
    """Find archived snapshots of a URL via the Wayback Machine."""
    cdx_url = "https://web.archive.org/cdx/search/cdx"
    params = {
        "url": url,
        "output": "json",
        "limit": 3,
        "collapse": "timestamp:8",
    }

    try:
        resp = await get(cdx_url, params=params, use_cache=True)
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        return [{"error": f"Wayback CDX HTTP {exc.response.status_code}"}]

    if len(data) <= 1:
        return [{"error": "No archived snapshots found"}]

    # data[0] is header row
    results = []
    for row in data[1:]:
        timestamp = row[1]
        original = row[2]
        archived_url = f"https://web.archive.org/web/{timestamp}/{original}"
        try:
            page_results = await scrape_contact_page(archived_url)
            results.extend(page_results)
        except Exception as exc:  # noqa: BLE001
            results.append({"error": f"Failed to scrape archived {archived_url}: {exc}"})

    return results
