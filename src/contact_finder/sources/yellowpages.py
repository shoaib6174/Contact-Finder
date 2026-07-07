"""Adapter: Yellow Pages business listing search."""

from __future__ import annotations

import httpx

from contact_finder.config import Config
from contact_finder.http_client import post
from contact_finder.models import ContactCandidate
from contact_finder.pii_guard import is_consumer_email
from contact_finder.sources.base import adapter

_config = Config()

_EMAIL_RE = __import__("re").compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = __import__("re").compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")


@adapter(category="finder")
async def yellowpages_search(name: str, address: str) -> list[dict]:
    """Search Yellow Pages for a business by name and location."""
    if not _config.serper_api_key:
        return [{"error": "SERPER_API_KEY not configured"}]

    query = f'"{name}" site:yellowpages.com {address}'
    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": _config.serper_api_key}
    payload = {"q": query, "num": 2}

    try:
        resp = await post(url, json=payload, headers=headers)
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        return [{"error": f"Serper HTTP {exc.response.status_code}"}]

    candidates = []
    for item in data.get("organic", []):
        link = item.get("link", "")
        snippet = item.get("snippet", "")
        phones = _PHONE_RE.findall(snippet)
        emails = [e for e in _EMAIL_RE.findall(snippet) if not is_consumer_email(e)]
        candidates.append(
            ContactCandidate(
                name=None,
                role="Generic Business Contact",
                email=emails[0] if emails else None,
                phone=phones[0] if phones else None,
                source="yellowpages",
                source_url=link,
                source_trust=0.75,
                raw_evidence=f"Yellow Pages listing: {item.get('title')}",
            ).model_dump()
        )

    return candidates
