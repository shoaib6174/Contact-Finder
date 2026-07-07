"""Adapter: scrape a company website contact page."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from contact_finder.http_client import get
from contact_finder.models import ContactCandidate
from contact_finder.pii_guard import is_consumer_email
from contact_finder.sources.base import adapter

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")


@adapter(category="finder")
async def scrape_contact_page(url: str) -> list[dict]:
    """Fetch and extract business contacts from a company website page (e.g. /contact, /about)."""
    try:
        resp = await get(url, follow_redirects=True)
        text = resp.text
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"Failed to fetch {url}: {exc}"}]

    soup = BeautifulSoup(text, "lxml")

    # Try to find links to contact/about pages
    contact_urls = _find_contact_links(soup, url)

    candidates = []
    seen = set()

    for page_url in [url] + contact_urls[:3]:
        try:
            if page_url != url:
                resp = await get(page_url, follow_redirects=True)
                soup = BeautifulSoup(resp.text, "lxml")
        except Exception:  # noqa: BLE001
            continue

        page_text = soup.get_text(" ", strip=True)
        emails = [e for e in _EMAIL_RE.findall(page_text) if not is_consumer_email(e)]
        phones = _PHONE_RE.findall(page_text)

        # Avoid duplicates
        for email in emails:
            key = ("email", email)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                ContactCandidate(
                    name=None,
                    role="Generic Business Contact",
                    email=email,
                    phone=phones[0] if phones else None,
                    source="website",
                    source_url=page_url,
                    source_trust=0.95,
                    raw_evidence=f"Email found on {page_url}",
                ).model_dump()
            )

    return candidates


def _find_contact_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        text = a.get_text(strip=True).lower()
        if "contact" in href or "contact" in text or "about" in href or "about" in text:
            full = urljoin(base_url, a["href"])
            if urlparse(full).netloc == urlparse(base_url).netloc:
                links.append(full)
    return links
