"""Adapter: WHOIS domain lookup."""

from __future__ import annotations

import whois

from contact_finder.models import ContactCandidate
from contact_finder.pii_guard import is_consumer_email
from contact_finder.sources.base import adapter


@adapter(category="finder")
async def whois_lookup(domain: str) -> list[dict]:
    """Query WHOIS for a domain. Returns admin/tech contact info if publicly available."""
    try:
        info = whois.whois(domain)
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"WHOIS lookup failed: {exc}"}]

    emails = []
    for raw in [info.emails, info.admin_email, info.tech_email]:
        if not raw:
            continue
        if isinstance(raw, list):
            emails.extend(raw)
        else:
            emails.append(raw)

    phones = []
    for raw in [info.phone, info.admin_phone, info.tech_phone]:
        if not raw:
            continue
        if isinstance(raw, list):
            phones.extend(str(p) for p in raw)
        else:
            phones.append(str(raw))

    candidates = []
    seen = set()
    for email in emails:
        email = str(email).strip()
        if not email or "@" not in email or is_consumer_email(email) or email in seen:
            continue
        seen.add(email)
        candidates.append(
            ContactCandidate(
                name=None,
                role="Generic Business Contact",
                email=email,
                phone=phones[0] if phones else None,
                source="whois",
                source_url=f"https://who.is/whois/{domain}",
                source_trust=0.85,
                raw_evidence=f"WHOIS record for {domain}",
            ).model_dump()
        )

    return candidates
