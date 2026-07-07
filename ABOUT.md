# About this submission

**Project:** `contact-finder`  
**Challenge:** Round 1 — Find the contact nobody else can find  
**Author:** Mohammad Shoaib  
**Repository:** `/Users/mohammadshoaib/Codes/personal/contact-finder`

## What this is

A precision-first, agentic CLI tool that enriches debtor CSV rows with a verified business contact, a 0–1 confidence score, evidence, source URLs, and a `needs_human_review` flag. It is designed for a collections/research workflow where a wrong contact is worse than no contact.

## Core philosophy

1. **Prove the entity first.** Before any contact is extracted, the debtor name + address must be corroborated by an independent public source (business registry, maps listing, or the company’s own website at a matching domain).
2. **Contacts are bound to the entity.** A candidate is accepted only when its source URL/domain, address evidence, and role all point back to the resolved debtor.
3. **Fail honestly.** If public sources cannot verify the entity or a credible contact, the row is flagged for human review with a reason, not fabricated.
4. **Passive and privacy-safe.** No email, SMS, calls, or paywalled PII brokers are used. Personal/residential data is redacted and never sent to an LLM.

## Repository layout

```text
src/contact_finder/
  agent.py              # Native Groq tool-calling agent
  agent_fast.py         # Default fast path: concurrent adapters + one LLM call
  config.py             # Environment config, scoring constants
  entity_resolution.py  # Shared entity-resolution gate
  groq_client.py        # Groq client with API-key fallback
  models.py             # Pydantic row/candidate/bundle models
  normalizer.py         # Address and company-name normalization
  pii_guard.py          # Field-aware PII redaction
  scorer.py             # Deterministic confidence scoring
  sources/              # Public-source adapters (web, maps, registries, etc.)
  cli.py                # Entrypoint

data/hard_cases.csv     # The 5 challenge rows
out/                    # Enriched CSV, provenance JSONL, run report
PLAN.md                 # Initial plan, committed before code
APPROACH.md             # Final implemented architecture and deviations from plan
CLEVER.md               # Proven clever tricks, including failures
README.md               # How to run, architecture, configuration
```

## How to run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Add keys to .env
cp .env.example .env
# GROQ_API_KEY=...
# SERPER_API_KEY=...

python -m contact_finder enrich data/hard_cases.csv \
  --output out/hard_cases_enriched.csv \
  --provenance out/hard_cases_provenance.jsonl \
  --run-report out/hard_cases_run_report.json
```

## Result on the 5 hard cases

| Row | Debtor | Result |
| --- | --- | --- |
| 1 | LAKE CABLE LLC (DUNS N° 927410308), Bensenville IL | ✅ Accepted: `+1 888-505-1457`, Office Manager, confidence **0.915** |
| 2 | SUMMIT ELECTRIC (Inc.), Albuquerque NM | ⚠️ Human review — only social/generic contacts, no verified AP path |
| 3 | CEDAR RIDGE PLUMBING LLC, Lincoln NE | ❌ Rejected — no corroborated Nebraska entity |
| 4 | MAGNOLIA FAMILY DENTAL, Macon GA | ❌ Rejected — no matching public listing at the debtor address |
| 5 | PIONEER LANDSCAPING INC, Boise ID | ❌ Rejected — listing found in Meridian ID, not Boise |

One strong, provable contact beats five weak guesses.

## Verification discipline

- Every accepted value has a source URL and raw evidence in `out/hard_cases_provenance.jsonl`.
- Every rejected row has a reason in `out/hard_cases_run_report.json`.
- The creditor (`FedEx`) is suppressed at scoring and adapter layers so it is never returned as the debtor contact.

## Compliance

- **Passive only:** MX checks without sending mail, public registry/maps lookups, scraping public `/contact` pages.
- **No paywalled PII brokers.**
- **Data minimization:** PII redaction runs before any text is sent to Groq or persisted; residential keywords are stripped.

## Notes

`PLAN.md` was committed before any solution code, as required. This implementation evolved beyond the original plan (see `APPROACH.md` for the final architecture and the key deviations).
