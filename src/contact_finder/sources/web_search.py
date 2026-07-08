"""Adapter: public web search via Serper.dev."""

from __future__ import annotations

import httpx

from contact_finder.config import Config
from contact_finder.http_client import post
from contact_finder.sources.base import adapter

_config = Config()


@adapter(category="resolver")
async def web_search(query: str, num: int = 3) -> list[dict]:
    """Run a public web search. Use for finding websites, registry pages, or directory listings."""
    if not _config.serper_api_keys:
        return [{"error": "SERPER_API_KEY not configured"}]

    url = "https://google.serper.dev/search"
    payload = {"q": query, "num": num}

    last_error = "No Serper API keys available"
    for key in _config.serper_api_keys:
        headers = {"X-API-KEY": key}
        try:
            resp = await post(url, json=payload, headers=headers)
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            last_error = f"Serper HTTP {exc.response.status_code}"
            continue

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

    return [{"error": last_error}]
