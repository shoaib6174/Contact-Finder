"""Adapter: passive email-domain verification."""

from __future__ import annotations

import dns.resolver

from contact_finder.sources.base import adapter


@adapter(category="verifier")
async def mx_verify(email_or_domain: str) -> dict:
    """Passively verify that an email domain has MX records and supports catch-all detection without sending mail."""
    domain = email_or_domain.split("@")[-1].strip().lower()

    try:
        answers = dns.resolver.resolve(domain, "MX")
        mx_records = sorted([str(r.exchange).rstrip(".") for r in answers])
    except Exception as exc:  # noqa: BLE001
        return {
            "domain": domain,
            "mx_records": [],
            "catch_all": False,
            "smtp_probe_reachable": None,
            "note": f"MX lookup failed: {exc}",
        }

    # Simple catch-all heuristic: common catch-all hostnames
    catch_all_hosts = {"mx0.", "mx1.", "smtp.", "mail.", "relay."}
    catch_all = any(any(h in mx.lower() for h in catch_all_hosts) for mx in mx_records)

    return {
        "domain": domain,
        "mx_records": mx_records,
        "catch_all": catch_all,
        "smtp_probe_reachable": None,
        "note": "MX records found; no mail sent",
    }
