"""Adapter: resolve a debtor entity by checking its official website for the address."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from contact_finder.config import Config
from contact_finder.entity_resolution import _address_matches, _name_matches
from contact_finder.models import DebtorRow
from contact_finder.pii_guard import normalize_name
from contact_finder.scorer import _domain_matches
from contact_finder.sources.base import adapter
from contact_finder.sources.web_search import web_search

_config = Config()


async def _fetch_page_text(url: str) -> str:
    """Fetch a URL and return plain-text body content."""
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": _config.user_agent})
            resp.raise_for_status()
    except Exception:  # noqa: BLE001
        return ""

    soup = BeautifulSoup(resp.text, "lxml")
    # Remove script/style noise
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return " ".join(soup.stripped_strings)


@adapter(category="resolver")
async def website_entity_resolver(name: str, address: str) -> list[dict]:
    """Confirm the debtor entity by finding an official website that lists its address."""
    if not _config.serper_api_keys:
        return [{"error": "SERPER_API_KEY not configured"}]

    row = DebtorRow(
        row_id="resolver",
        company_name=name,
        address=address,
        company_issuing_the_invoice="",
    )

    # Normalize the query name for domain matching.
    clean_name = normalize_name(name)

    queries = [
        f"{name} official website",
        f"{name} contact address",
    ]
    seen_domains: set[str] = set()

    for query in queries:
        results = await web_search(query, num=5)
        if isinstance(results, dict) and "error" in results:
            continue
        for item in results:
            link = item.get("link", "")
            title = item.get("title", "")
            if not link:
                continue

            parsed = urlparse(link)
            netloc = parsed.netloc or link.split("/")[0]
            if netloc.startswith("www."):
                netloc = netloc[4:]
            if netloc in seen_domains:
                continue
            seen_domains.add(netloc)

            # Skip obvious directory/aggregator sites.
            excluded = {"yelp.com", "yellowpages.com", "bbb.org", "linkedin.com", "facebook.com", "pissedconsumer.com"}
            if any(domain in netloc for domain in excluded):
                continue

            # Domain must match the company name.
            if not _domain_matches(clean_name, link):
                continue

            # Name should also appear in the page title or snippet.
            snippet = item.get("snippet", "")
            if not (_name_matches(name, title) or _name_matches(name, snippet)):
                continue

            # Fetch the page and look for the debtor address.
            page_text = await _fetch_page_text(link)
            if _address_matches(row, {"city": None, "state": None, "zip": None}, page_text):
                # We need city/state/zip from the input; build norm via a quick parse.
                from contact_finder.normalizer import normalize_company

                norm = normalize_company(row).model_dump()
                if _address_matches(row, norm, page_text):
                    return [
                        {
                            "name": name,
                            "source": "website_entity",
                            "source_url": link,
                            "match_reason": "Official website domain matches company and page contains debtor address",
                            "address": address,
                        }
                    ]

    return [{"error": f"No official website corroborated {name} at {address}"}]
