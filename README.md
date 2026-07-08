# Contact-Finder

A precision-first, agentic CLI tool that enriches debtor rows from a CSV with a verified business contact, evidence, confidence score, and a `needs_human_review` flag.

Built for a collections/research workflow where:
- The debtor is a **business**, not a consumer.
- The creditor (`company_issuing_the_invoice`) must **never** be enriched.
- Every decision must be explainable via a JSON action log and provenance trail.
- Public, passive sources only — no outreach, no paywalled PII brokers.

## What it does

Given an input CSV like:

```csv
full_name,address,company_name,email,phone_number,company_issuing_the_invoice
Accounts Payable,"745 Commerce Blvd, Schaumburg, IL 60173",MIDWEST INDUSTRIAL SUPPLY LLC,,,UPS
```

It produces:

1. **`enriched.csv`** — one row per input, with added contact fields and `needs_human_review`.
2. **`provenance.jsonl`** — one entry per accepted field, tracing value → source → rationale.
3. **`run_report.json`** — summary stats plus a full action/dead-end log.

## Quick start

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configure

Copy `.env.example` to `.env` and add your keys:

```bash
GROQ_API_KEY=gsk_...
SERPER_API_KEY=...
```

`GROQ_API_KEY` is required. `SERPER_API_KEY` is strongly recommended — without it, web search, maps, and directory adapters return errors.

### 3. Run

```bash
python -m contact_finder enrich contact_finder_test_dataset.csv \
  --output out/enriched.csv \
  --provenance out/provenance.jsonl \
  --run-report out/run_report.json
```

Override knobs on the fly:

```bash
python -m contact_finder enrich input.csv \
  --model llama-3.1-8b-instant \
  --max-calls 6 \
  --threshold 0.7
```

## Architecture

```
CSV rows
   │
   ▼
PII Guard ──► Normalizer ──► ContactFinderAgent (Groq tool use)
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              Resolver       Finder        Verifier
              adapters       adapters      adapters
         (OpenCorporates,   (web search,  (MX verify,
          SOS, maps,        Yellow Pages, WHOIS, Wayback)
          Yellow Pages,     Yelp,
          Yelp, WHOIS,      scrape website)
          Wayback)
                    │             │             │
                    └─────────────┴─────────────┘
                                  ▼
                     Deterministic scorer
                     (role × address × source + bonuses)
                                  │
                                  ▼
                    Enriched CSV + provenance + run report
```

### Agent loop

The LLM is given a system prompt, a single debtor row, and a set of tool definitions. It decides which public sources to query, then returns a structured JSON final answer with ranked candidate bundles. Python — not the LLM — computes the final confidence score, enforces the creditor-suppression rule, and decides whether the row passes the threshold.

### Confidence scoring

`score = role_base × address_match × source_trust + corroboration_bonus + mx_bonus`, clamped to `[0, 1]`.

| Factor | Notes |
|--------|-------|
| `role_base` | Accounts Payable = 0.95, Owner/Founder = 0.85, CFO = 0.80, Office Manager = 0.70, Registered Agent = 0.55, Generic = 0.50 |
| `address_match` | exact = 1.0, city/state = 0.9, state only = 0.75, unknown = 0.5 |
| `source_trust` | registry = 1.0, website = 0.95, WHOIS = 0.85, maps = 0.80, directory = 0.75, archive = 0.65, web search = 0.55 |
| `corroboration_bonus` | +0.10 when multiple independent sources agree |
| `mx_bonus` | +0.05 when the email domain has valid MX records |

A candidate must also be free of creditor matches and have at least one source URL.

## Outputs

### `enriched.csv`

```csv
row_id,full_name,address,company_name,email,phone_number,company_issuing_the_invoice,contact_name,contact_role,contact_email_or_phone,confidence_score,evidence,source,needs_human_review
2,Finance Department,"2210 Innovation Way, Raleigh, NC 27606",TRIANGLE TECHNOLOGY SOLUTIONS INC.,,,DHL,Finance Department,Accounts Payable,finance@triangle-tech.com,1.0,Finance Department email listed on /contact page,https://triangle-tech.com/contact,False
```

### `run_report.json`

```json
{
  "summary": {
    "total_rows": 15,
    "entities_resolved": 2,
    "contacts_found": 2,
    "contacts_accepted": 2,
    "needs_human_review": 13,
    "average_confidence": 0.89,
    "run_duration_seconds": 662.7,
    "timestamp": "2026-07-07T09:02:38+00:00"
  },
  "actions": [...],
  "errors": []
}
```

### `provenance.jsonl`

One JSON object per accepted field:

```json
{"row_id": "2", "field": "contact_email_or_phone", "value": "finance@triangle-tech.com", "source": "selected_candidate", "source_url": "https://triangle-tech.com/contact", "rationale": "Finance Department email listed on /contact page", "timestamp": "..."}
```

## Testing

```bash
pytest tests/ -q
```

The suite covers:
- Address parsing and company-name normalization
- PII redaction and creditor-name matching
- Deterministic confidence scoring and creditor suppression
- The Groq tool-use agent loop (mocked)

## Configuration

All knobs are environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `GROQ_API_KEY` | — | Required. Groq API key. |
| `SERPER_API_KEY` | — | Optional but recommended. Powers web/maps/directory search. |
| `DEFAULT_MODEL` | `llama-3.1-8b-instant` | Groq model ID. |
| `MAX_TOOL_CALLS` | `8` | Max agent turns per row. |
| `CONFIDENCE_THRESHOLD` | `0.7` | Minimum score to accept a candidate. |
| `REQUEST_DELAY` | `1.0` | Seconds between external requests. |

## Design principles

1. **Hierarchical, cost-first resolution.** Start with cheap registry/directory lookups; escalate to website scraping and MX verification only when needed.
2. **Creditor suppression at every gate.** The creditor named in `company_issuing_the_invoice` is never returned as the debtor contact.
3. **Deterministic scoring.** The LLM returns evidence; Python computes the score.
4. **Full provenance.** Every accepted value is traceable to a public source URL.
5. **Honest human review.** Rows without sufficient evidence are flagged for manual review instead of fabricated.

## Limitations

- Requires publicly available contact information. If a business hides its AP email/phone, the row is flagged for review.
- Rate limits: Groq’s free/on-demand tier has tokens-per-day and tokens-per-minute caps. The tool adds delays and context compaction to stay within them, but large files may still need a paid tier or multiple keys.
- Small-model reliability: the 8b model is cheaper but occasionally emits malformed JSON or trailing text. The extractor tolerates markdown fences and extra text, but some rows may still need review.

## License

MIT
