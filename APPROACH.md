# Implemented architecture

This document describes the architecture that was actually built and how it differs from the original `PLAN.md`.

## High-level pipeline

```text
CSV row
  │
  ▼
Normalizer ──► PII Guard ──► Concurrent public-source adapters
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
   Registry              Maps / directories          Website entity
   (OpenCorporates,      (Google Maps, Yellow        resolver
    Secretary of State)   Pages, Yelp)                (official site +
        │                        │                    address check)
        └────────────────────────┼────────────────────────┘
                                 ▼
                    Entity-resolution gate
                    (must prove name + address)
                                 │
              pass ──────────────┴───────────── fail
              │                                      │
              ▼                                      ▼
   Scrape candidate websites              Return needs_human_review
   + single LLM extraction                with reason
              │
              ▼
   Deterministic scorer + creditor suppression
              │
              ▼
   enriched.csv + provenance.jsonl + run_report.json
```

## What changed from the plan

1. **Added a fast, deterministic-orchestration mode.**
   - `PLAN.md` assumed a native Groq tool-calling loop (`agent.py`).
   - The final default is `agent_fast.py`: it runs all public-source adapters concurrently, builds a compact digest, and makes **one** LLM call. This is much cheaper and faster while preserving the same verification discipline.

2. **Tightened entity resolution into a hard gate.**
   - The plan described entity resolution as a scoring input.
   - The implementation makes it a **binary gate**: no contact extraction happens unless a public record corroborates the debtor name + address. This eliminated synthetic-row hallucinations.

3. **Added domain-name binding.**
   - Not in the original plan. Websites are only scraped if their domain matches the company name, and a domain-match bonus is added to the score. This prevents supplier lists, news articles, and competitor pages from polluting results.

4. **Added generic-token filtering for name overlap.**
   - Maps listings often share industry words ("plumbing", "electric", "dental"). The implementation strips these before comparing names, which fixed the Cedar Ridge false positive.

5. **Added API-key fallbacks.**
   - `GROQ_API_KEY_2` and `SERPER_API_KEY_2` are used automatically when the primary key hits rate/credit limits. This was necessary because free tiers were exhausted during testing.

6. **Field-aware PII redaction.**
   - The plan mentioned redaction; the implementation only redacts values for sensitive keys (`email`, `phone`, `address`, `snippet`, `body`, `evidence`) so business titles like “Lowe's Home Improvement” are preserved for the LLM.

## Entity-resolution rules

The gate is in `src/contact_finder/entity_resolution.py`.

| Source | Requirement to open the gate |
| --- | --- |
| Registry (OpenCorporates / SOS) | Name matches **and** state matches **and** city or ZIP matches. |
| Maps | City/state/ZIP matches **and** name matches via substring or distinctive-token overlap. |
| Website entity resolver | Name matches **and** domain matches company name **and** debtor address appears on the site. |

Generic terms (`plumbing`, `electric`, `dental`, `services`, `inc`, `llc`, …) are ignored in the distinctive-token check.

## Confidence scoring

Implemented in `src/contact_finder/scorer.py`:

```
score = role_base × address_match × source_trust
        + corroboration_bonus
        + mx_bonus
        + domain_match_bonus
```

- `role_base`: Accounts Payable 0.95, Owner/Founder 0.85, CFO 0.80, Office Manager 0.70, Registered Agent 0.55, Generic 0.50.
- `address_match`: exact 1.0, city/state 0.9, state only 0.75, unknown 0.5.
- `source_trust`: registry 1.0, website 0.95, WHOIS 0.85, maps 0.80, directory 0.75, archive 0.65, web search 0.55. LLM-provided trust is clamped to this canonical map.
- `corroboration_bonus` = +0.10.
- `mx_bonus` = +0.05.
- `domain_match_bonus` = +0.15.

The final score is clamped to `[0, 1]`. A candidate must score `>= CONFIDENCE_THRESHOLD` (default 0.70) and must not match the creditor.

## Creditor suppression

The creditor (`company_issuing_the_invoice`) is suppressed at two layers:

1. **Adapter layer:** search queries are built from the debtor name/address, never the creditor.
2. **Scoring layer:** any candidate whose name, source URL, or email contains the creditor name is discarded.

## Privacy / compliance

- Passive verification only: MX checks without sending mail, public registry lookups, public `/contact` page scraping.
- No paywalled PII brokers, no email/SMS/calls, no login-required pages.
- PII redaction runs before text is sent to Groq or persisted.
- Residential keywords are stripped from addresses; only business-corporate contacts are returned.

## Output files

- `enriched.csv` — one row per input with contact fields and `needs_human_review`.
- `provenance.jsonl` — one entry per accepted value tracing value → source → rationale.
- `run_report.json` — summary stats plus a full action/dead-end log.

## Test coverage

```bash
pytest tests/ -q
```

Covers: address parsing, name normalization, PII redaction, creditor suppression, deterministic scoring, entity-resolution gate, and the agent loop with mocked Groq calls.
