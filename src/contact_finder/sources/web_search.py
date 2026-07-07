"""Adapter: public web search via Serper.dev."""

from __future__ import annotations

import httpx

from contact_finder.config import Config
from contact_finder.http_client import post
from contact_finder.sources.base import adapter

_config = Config()


@adapter(category="resolver")
async def web_search(query: str) -> list[dict]:
    """Run a public web search. Use for finding websites, registry pages, or directory listings."""
    if not _config.serper_api_key:
        return [{"error": "SERPER_API_KEY not configured"}]

    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": _config.serper_api_key}
    payload = {"q": query, "num": 3}

    try:
        resp = await post(url, json=payload, headers=headers)
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        return [{"error": f"Serper HTTP {exc.response.status_code}"}]

    results = []
    for item in data.get("organic", []):
        results.append(
            {
                "title": item.get("title"),
                "link": item.get("link"),
                "snippet": item.get("snippet"),
            }
        )
    return results
