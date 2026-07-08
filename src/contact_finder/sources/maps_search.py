"""Adapter: public maps business listing search."""

from __future__ import annotations

import httpx

from contact_finder.config import Config
from contact_finder.http_client import post
from contact_finder.sources.base import adapter

_config = Config()


@adapter(category="resolver")
async def maps_search(name: str, address: str) -> list[dict]:
    """Search public map business listings by name and address. Helps confirm the right physical location."""
    if not _config.serper_api_keys:
        return [{"error": "SERPER_API_KEY not configured"}]

    url = "https://google.serper.dev/maps"
    payload = {"q": f"{name} {address}", "num": 2}

    last_error = "No Serper API keys available"
    for key in _config.serper_api_keys:
        headers = {"X-API-KEY": key}
        try:
            resp = await post(url, json=payload, headers=headers)
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            last_error = f"Serper maps HTTP {exc.response.status_code}"
            continue

        results = []
        for item in data.get("places", []):
            results.append(
                {
                    "title": item.get("title"),
                    "address": item.get("address"),
                    "phone": item.get("phoneNumber"),
                    "website": item.get("website"),
                    "source_url": item.get("website") or item.get("cid"),
                }
            )
        return results

    return [{"error": last_error}]
