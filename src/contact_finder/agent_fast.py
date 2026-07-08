"""Fast, deterministic-orchestration enrichment path.

Instead of a multi-turn tool-use loop, this module:
1. Normalizes the input.
2. Runs resolver/finder adapters concurrently.
3. Builds a compact source digest.
4. Makes a single LLM call to extract ranked candidate bundles.
5. Scores and selects the best candidate in Python.

This is much cheaper and faster than the native tool-calling loop while
still using the LLM for reasoning and ambiguity resolution.
"""

from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime, timezone
from typing import Any

from contact_finder.config import Config
from contact_finder.entity_resolution import entity_resolved
from contact_finder.groq_client import chat_completion
from contact_finder.models import DebtorRow, EnrichedRow, EvidenceBundle
from contact_finder.pii_guard import normalize_name
from contact_finder.scorer import _domain_matches, select_best_candidate
from contact_finder.sources import (
    maps_search,
    normalize_company,
    opencorporates_lookup,
    scrape_contact_page,
    sos_lookup,
    web_search,
    website_entity_resolver,
    yellowpages_search,
    yelp_search,
)
from contact_finder.system_prompt import build_system_prompt


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_domain(link: str) -> str | None:
    """Pull a bare domain from a URL."""
    if not link:
        return None
    link = link.strip()
    if link.startswith("http"):
        from urllib.parse import urlparse

        netloc = urlparse(link).netloc
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or None
    return link.split("/")[0] or None


def _shorten(text: str | None, limit: int = 200) -> str:
    if not text:
        return ""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _candidate_websites(results: dict[str, Any], clean_name: str, limit: int = 3) -> list[str]:
    """Collect likely company websites from web search and maps results.

    Only keep domains that match the cleaned company name so we don't scrape
    unrelated pages (e.g. a supplier directory) for contacts.
    """
    excluded = {"yelp.com", "yellowpages.com", "opencorporates.com", "sos.", "google.com", "bing.com", "linkedin.com"}
    links: list[str] = []
    seen: set[str] = set()

    def add(link: str) -> None:
        domain = _extract_domain(link)
        if not domain:
            return
        if any(domain.endswith(e) or e in domain for e in excluded):
            return
        if domain in seen:
            return
        if not _domain_matches(clean_name, link):
            return
        seen.add(domain)
        links.append(link)

    for item in results.get("web", [])[:8]:
        add(item.get("link", ""))
    for item in results.get("maps", [])[:3]:
        add(item.get("website", ""))

    return links[:limit]


def _serialize_digest(results: dict[str, Any]) -> str:
    """Convert adapter results into a compact LLM-readable digest."""
    lines: list[str] = []

    norm = results.get("normalize") or {}
    lines.append(f"NORMALIZED: {norm.get('clean_name') or norm.get('raw_name')} | {norm.get('city')}, {norm.get('state')} {norm.get('zip')}")

    oc = results.get("opencorporates") or []
    if oc and not any("error" in r for r in oc):
        lines.append("OPENCORPORATES:")
        for r in oc[:2]:
            lines.append(f"  - {r.get('name')} | {r.get('jurisdiction')} | {r.get('address')} | {r.get('source_url')}")

    sos = results.get("sos") or []
    if sos and not any("error" in r for r in sos):
        lines.append("SECRETARY_OF_STATE:")
        for r in sos[:2]:
            lines.append(f"  - {r.get('name')} | {r.get('jurisdiction')} | {r.get('source_url')}")

    maps = results.get("maps") or []
    if maps and not any("error" in r for r in maps):
        lines.append("MAPS:")
        for r in maps[:2]:
            lines.append(f"  - {r.get('title')} | {r.get('address')} | phone={r.get('phone')} | website={r.get('website')}")

    web = results.get("web") or []
    if web:
        lines.append("WEB_SEARCH:")
        for r in web[:3]:
            lines.append(f"  - {_shorten(r.get('title'))} | {r.get('link')} | {_shorten(r.get('snippet'))}")

    yp = results.get("yellowpages") or []
    if yp and not any("error" in r for r in yp):
        lines.append("YELLOW_PAGES:")
        for r in yp[:2]:
            lines.append(f"  - phone={r.get('phone')} | email={r.get('email')} | {r.get('source_url')}")

    yelp = results.get("yelp") or []
    if yelp and not any("error" in r for r in yelp):
        lines.append("YELP:")
        for r in yelp[:2]:
            lines.append(f"  - phone={r.get('phone')} | email={r.get('email')} | {r.get('source_url')}")

    website = results.get("website") or []
    if website and not any("error" in r for r in website):
        lines.append("WEBSITE_CONTACT:")
        for r in website[:3]:
            lines.append(f"  - name={r.get('name')} role={r.get('role')} email={r.get('email')} phone={r.get('phone')} | {r.get('source_url')}")

    return "\n".join(lines) or "No public sources returned useful data."


def _extract_json(content: str) -> dict:
    """Parse the final answer, tolerating markdown fences and trailing text."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


def _human_review(row: DebtorRow, reason: str) -> tuple[EnrichedRow, list, list, list]:
    return (
        EnrichedRow(
            row_id=row.row_id,
            full_name=row.full_name,
            address=row.address,
            company_name=row.company_name,
            email=row.email,
            phone_number=row.phone_number,
            company_issuing_the_invoice=row.company_issuing_the_invoice,
            needs_human_review=True,
            evidence=reason,
        ),
        [],
        [
            {
                "row_id": row.row_id,
                "tool": "agent_fast",
                "result": "human_review",
                "reason": reason,
                "timestamp": _now(),
            }
        ],
        [],
    )


def _parse_bundles(data: list[dict]) -> list[EvidenceBundle]:
    from contact_finder.models import ContactCandidate

    bundles = []
    for item in data:
        try:
            cand_data = item.get("candidate", {})
            ev_data = item.get("evidence", {})
            candidate = ContactCandidate(**cand_data)
            bundle = EvidenceBundle(
                role=candidate.role,
                address_match=ev_data.get("address_match", 0.5),
                source_trust=ev_data.get("source_trust", 0.5),
                source_urls=ev_data.get("source_urls", []),
                source_categories=ev_data.get("source_categories", []),
                corroborated=ev_data.get("corroborated", False),
                mx_verified=ev_data.get("mx_verified", False),
                candidate=candidate,
            )
            bundles.append(bundle)
        except Exception:  # noqa: BLE001
            continue
    return bundles


async def enrich_row_fast(
    row: DebtorRow, config: Config
) -> tuple[EnrichedRow, list, list, list]:
    """One-LLM-call enrichment path with concurrent adapters."""
    if not config.groq_api_key:
        return _human_review(row, "GROQ_API_KEY not configured")

    actions: list[dict] = []
    errors: list[dict] = []

    # 1. Normalize
    try:
        norm = await normalize_company(row.company_name, row.address)
    except Exception as exc:  # noqa: BLE001
        errors.append({"row_id": row.row_id, "tool": "normalize_company", "error": str(exc)})
        norm = {}

    state = (norm.get("state") or "").upper()
    city = norm.get("city")
    zip_code = norm.get("zip")
    clean_name = norm.get("clean_name") or row.company_name

    # 2. Run public-source adapters concurrently
    async def run_adapters() -> dict[str, Any]:
        web_task = asyncio.create_task(web_search(f"{clean_name} contact", num=8))
        web_ap_task = asyncio.create_task(web_search(f"{clean_name} accounts payable email", num=5))
        maps_task = asyncio.create_task(maps_search(clean_name, row.address))
        oc_task = asyncio.create_task(
            opencorporates_lookup(clean_name, state, city, zip_code)
        ) if state else asyncio.create_task(asyncio.sleep(0))
        sos_task = asyncio.create_task(
            sos_lookup(clean_name, state, city, zip_code)
        ) if state else asyncio.create_task(asyncio.sleep(0))
        yp_task = asyncio.create_task(yellowpages_search(clean_name, row.address))
        yelp_task = asyncio.create_task(yelp_search(clean_name, row.address))
        web_entity_task = asyncio.create_task(website_entity_resolver(clean_name, row.address))

        web_results = await web_task
        web_ap_results = await web_ap_task
        combined_web = web_results + web_ap_results

        return {
            "normalize": norm,
            "web": combined_web,
            "maps": await maps_task,
            "opencorporates": await oc_task if state else [],
            "sos": await sos_task if state else [],
            "yellowpages": await yp_task,
            "yelp": await yelp_task,
            "website_entity": await web_entity_task,
        }

    results = await run_adapters()
    await asyncio.sleep(config.request_delay)

    # 2b. Entity-resolution gate: only spend LLM tokens once public records
    # corroborate the debtor at its address. This prevents synthetic/ambiguous
    # names from producing hallucinated contacts.
    resolver_map = {
        "opencorporates": "opencorporates_lookup",
        "sos": "sos_lookup",
        "maps": "maps_search",
        "website_entity": "website_entity_resolver",
    }
    resolved = any(
        entity_resolved(row, norm, resolver_map[key], results[key])
        for key in resolver_map
        if key in results
    )
    if not resolved:
        return _human_review(
            row,
            "Entity not resolved in public records (registry/maps) before contact search.",
        )

    # 3. Optionally scrape the top company websites for contacts
    candidate_urls = _candidate_websites(results, clean_name, limit=3)
    website_candidates = []
    for url in candidate_urls:
        try:
            contact_page = await scrape_contact_page(url)
            if isinstance(contact_page, list):
                website_candidates.extend(contact_page)
        except Exception as exc:  # noqa: BLE001
            errors.append({"row_id": row.row_id, "tool": "scrape_contact_page", "error": str(exc)})
    if website_candidates:
        results["website"] = website_candidates

    digest = _serialize_digest(results)

    # 4. Single LLM call for extraction
    creditor_hint = normalize_name(row.company_issuing_the_invoice)

    prompt = f"""{build_system_prompt()}

Public-source digest for the debtor:
{digest}

Debtor row:
- company_name: {row.company_name}
- address: {row.address}
- creditor (DO NOT ENRICH): {row.company_issuing_the_invoice}

INSTRUCTIONS
- Use the digest to resolve the real entity and choose the best business contact.
- Only return contacts that clearly belong to the debtor at the address above.
- For each candidate, set address_match to 1.0 if the source address matches the debtor address exactly, 0.9 if same city and state, 0.75 if same state only, and 0.5 if unknown or unclear.
- Prefer Accounts Payable, then Owner/Founder, CFO/Finance Lead, Office Manager, Registered Agent, then Generic Business Contact.
- Return exactly one JSON object with "status": "final" and "ranked_bundles". If no credible contact is found, return an empty ranked_bundles list."""

    try:
        response = await chat_completion(
            config,
            model=config.default_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # noqa: BLE001
        errors.append({"row_id": row.row_id, "error": f"Groq API error: {exc}"})
        return _human_review(row, f"Groq API error: {exc}")

    content = (response.choices[0].message.content or "").strip()
    data = _extract_json(content)

    actions.append(
        {
            "row_id": row.row_id,
            "tool": "agent_fast",
            "result": "success",
            "ranked_bundles": data.get("ranked_bundles", []),
            "timestamp": _now(),
        }
    )

    if data.get("status") != "final" and "ranked_bundles" not in data:
        return _human_review(row, "Final answer missing status: final")

    bundles = _parse_bundles(data.get("ranked_bundles", []))
    enriched, ranked = select_best_candidate(
        row, bundles, config.confidence_threshold, row.company_issuing_the_invoice, clean_name
    )
    actions[-1]["ranked_bundles"] = ranked
    return enriched, [], actions, errors
