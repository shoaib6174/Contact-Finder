"""Groq tool-use agent loop."""

from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime, timezone
from typing import Any

from contact_finder.config import Config
from contact_finder.entity_resolution import entity_resolved
from contact_finder.groq_client import chat_completion
from contact_finder.models import ContactCandidate, DebtorRow, EnrichedRow, EvidenceBundle
from contact_finder.pii_guard import normalize_name
from contact_finder.scorer import select_best_candidate
from contact_finder.sources import (
    maps_search,
    mx_verify,
    normalize_company,
    opencorporates_lookup,
    scrape_contact_page,
    sos_lookup,
    wayback_search,
    web_search,
    website_entity_resolver,
    whois_lookup,
    yellowpages_search,
    yelp_search,
)
from contact_finder.system_prompt import build_system_prompt, build_user_message


_TOOL_MAP = {
    "normalize_company": normalize_company,
    "web_search": web_search,
    "maps_search": maps_search,
    "opencorporates_lookup": opencorporates_lookup,
    "sos_lookup": sos_lookup,
    "scrape_contact_page": scrape_contact_page,
    "yellowpages_search": yellowpages_search,
    "yelp_search": yelp_search,
    "whois_lookup": whois_lookup,
    "wayback_search": wayback_search,
    "mx_verify": mx_verify,
    "website_entity_resolver": website_entity_resolver,
}

_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "normalize_company",
            "description": "Parse the raw company name and address into clean fields, legal form, registration code, and city/state/ZIP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string"},
                    "address": {"type": "string"},
                },
                "required": ["company_name", "address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Run a public web search. Use for finding websites, registry pages, or directory listings.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "maps_search",
            "description": "Search public map business listings by name and address. Helps confirm the right physical location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "address": {"type": "string"},
                },
                "required": ["name", "address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opencorporates_lookup",
            "description": "Look up a company in OpenCorporates by name and US state jurisdiction. City and ZIP help disambiguate same-named companies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "state": {"type": "string"},
                    "city": {"type": "string"},
                    "zip": {"type": "string"},
                },
                "required": ["name", "state"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sos_lookup",
            "description": "Query the relevant US Secretary of State business registry by company name and state. City and ZIP help disambiguate same-named companies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "state": {"type": "string"},
                    "city": {"type": "string"},
                    "zip": {"type": "string"},
                },
                "required": ["name", "state"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scrape_contact_page",
            "description": "Fetch and extract business contacts from a company website page (e.g. /contact, /about).",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "yellowpages_search",
            "description": "Search Yellow Pages for a business by name and location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "address": {"type": "string"},
                },
                "required": ["name", "address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "yelp_search",
            "description": "Search Yelp for a business by name and location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "address": {"type": "string"},
                },
                "required": ["name", "address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "whois_lookup",
            "description": "Query WHOIS for a domain. Returns admin/tech contact info if publicly available.",
            "parameters": {
                "type": "object",
                "properties": {"domain": {"type": "string"}},
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wayback_search",
            "description": "Find archived snapshots of a URL via the Wayback Machine.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mx_verify",
            "description": "Passively verify that an email domain has MX records without sending mail.",
            "parameters": {
                "type": "object",
                "properties": {"email_or_domain": {"type": "string"}},
                "required": ["email_or_domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "website_entity_resolver",
            "description": "Confirm the debtor entity by checking its official website for the debtor address. Helps when registry/maps are unavailable.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "address": {"type": "string"},
                },
                "required": ["name", "address"],
            },
        },
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _human_review(
    row: DebtorRow, reason: str
) -> tuple[EnrichedRow, list, list, list]:
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
                "tool": "agent",
                "result": "human_review",
                "reason": reason,
                "timestamp": _now(),
            }
        ],
        [],
    )


def _serialize(result: Any) -> str:
    try:
        text = json.dumps(result, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        text = str(result)
    # Keep observations short to preserve context window
    if len(text) > 1200:
        text = text[:1150] + "\n...[truncated]"
    return text


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


def _compact_messages(messages: list[dict], max_chars: int = 6000) -> list[dict]:
    """Drop oldest assistant/tool exchange pairs to stay within context budget."""
    while True:
        payload = json.dumps(messages, default=str, ensure_ascii=False)
        if len(payload) <= max_chars:
            return messages
        # Find the oldest assistant message with tool_calls after the user message.
        assistant_idx = None
        for i, m in enumerate(messages):
            if i <= 1:
                continue
            if m.get("role") == "assistant" and m.get("tool_calls"):
                assistant_idx = i
                break
        if assistant_idx is None:
            return messages
        # Count how many tool responses follow it.
        tool_call_ids = {tc["id"] for tc in messages[assistant_idx].get("tool_calls", [])}
        remove_count = 1
        while (
            assistant_idx + remove_count < len(messages)
            and messages[assistant_idx + remove_count].get("tool_call_id") in tool_call_ids
        ):
            remove_count += 1
        messages = messages[:assistant_idx] + messages[assistant_idx + remove_count :]


async def _execute_tool(name: str, arguments: dict) -> Any:
    fn = _TOOL_MAP.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return await fn(**arguments)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "detail": traceback.format_exc(limit=2)}


def _parse_bundles(data: list[dict]) -> list[EvidenceBundle]:
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


async def enrich_row(
    row: DebtorRow, config: Config
) -> tuple[EnrichedRow, list, list, list]:
    """Run the Groq tool-use agent for a single row."""
    if not config.groq_api_key:
        return _human_review(row, "GROQ_API_KEY not configured")

    creditor_hint = normalize_name(row.company_issuing_the_invoice)

    # Resolve the input once so we have clean state/address for the entity gate.
    try:
        norm = await normalize_company(row.company_name, row.address)
    except Exception:  # noqa: BLE001
        norm = {}

    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt()},
        {
            "role": "user",
            "content": build_user_message(row, creditor_hint),
        },
    ]

    actions: list[dict] = []
    errors: list[dict] = []
    resolved = False

    for turn in range(config.max_tool_calls):
        messages = _compact_messages(messages)
        await asyncio.sleep(config.request_delay)

        is_last_turn = turn == config.max_tool_calls - 1
        try:
            response = await chat_completion(
                config,
                model=config.default_model,
                messages=messages,
                tools=_TOOL_DEFINITIONS,
                tool_choice="none" if is_last_turn else "auto",
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"row_id": row.row_id, "error": f"Groq API error: {exc}"})
            return _human_review(row, f"Groq API error: {exc}")

        msg = response.choices[0].message

        if msg.tool_calls and not is_last_turn:
            tool_calls_payload = []
            for tc in msg.tool_calls:
                tool_calls_payload.append(
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": tool_calls_payload,
                }
            )

            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError as exc:
                    errors.append(
                        {"row_id": row.row_id, "tool": name, "error": f"Invalid JSON args: {exc}"}
                    )
                    continue

                result = await _execute_tool(name, arguments)
                resolved = resolved or entity_resolved(row, norm, name, result)
                actions.append(
                    {
                        "row_id": row.row_id,
                        "turn": turn,
                        "tool": name,
                        "input": arguments,
                        "result": "error" if isinstance(result, dict) and "error" in result else "success",
                        "timestamp": _now(),
                    }
                )
                if isinstance(result, dict) and "error" in result:
                    errors.append({"row_id": row.row_id, "tool": name, "error": result["error"]})

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": _serialize(result),
                    }
                )
            continue

        # Final answer path
        content = (msg.content or "").strip()
        data = _extract_json(content)
        if not data:
            errors.append({"row_id": row.row_id, "error": "Final answer not valid JSON"})
            return _human_review(row, "Final answer not valid JSON")

        if data.get("status") != "final":
            errors.append({"row_id": row.row_id, "error": "Final answer missing status: final"})
            return _human_review(row, "Final answer missing status: final")

        bundles = _parse_bundles(data.get("ranked_bundles", []))
        enriched, ranked = select_best_candidate(
            row, bundles, config.confidence_threshold, row.company_issuing_the_invoice, norm.get("clean_name")
        )

        # Entity-resolution gate: do not accept a website-only contact for a row
        # that never matched a registry or maps record. This prevents hallucinated
        # contacts on synthetic/unresolvable inputs.
        if not enriched.needs_human_review and not resolved:
            enriched = EnrichedRow(
                row_id=enriched.row_id,
                full_name=enriched.full_name,
                address=enriched.address,
                company_name=enriched.company_name,
                email=enriched.email,
                phone_number=enriched.phone_number,
                company_issuing_the_invoice=enriched.company_issuing_the_invoice,
                needs_human_review=True,
                evidence="Contact found but entity not resolved in public records (registry/maps).",
            )

        actions.append(
            {
                "row_id": row.row_id,
                "turn": turn,
                "tool": "final_answer",
                "result": "success",
                "ranked_bundles": ranked,
                "timestamp": _now(),
            }
        )
        return enriched, [], actions, errors

    return _human_review(row, "Tool-call budget exhausted")
