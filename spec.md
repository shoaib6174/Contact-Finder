# Contact Finder — Technical Specification

> **Status:** Draft  
> **Stack:** Python 3.10+ CLI, Groq LLM with native tool calling, public passive sources only.

---

## 1. Overview

The contact finder is an **agentic CLI tool**. A Groq-hosted LLM drives a loop of tool calls that resolve a messy debtor row into a real entity, discover candidate business contacts, verify them passively, and produce an explainable confidence score. All heavy lifting (HTTP, parsing, scoring, output formatting) is done by deterministic Python code; the LLM is only used for reasoning, planning tool calls, and resolving ambiguity.

---

## 2. High-level architecture

### End-to-end runtime flow

```
input.csv
    │
    ▼
┌────────────────────────────────────────┐
│  CLI reads rows → DebtorRow objects    │
└──────────────┬─────────────────────────┘
               │ for each row
               ▼
┌────────────────────────────────────────┐
│  ContactFinderAgent.run(row)           │
│  - builds conversation context         │
│  - sends system prompt + row           │
└──────────────┬─────────────────────────┘
               │ LLM response:
               │   tool_calls  OR  final_answer
               ▼
┌────────────────────────────────────────┐
│  ToolExecutor.dispatch(tool_calls)     │
│  - looks up adapter by name            │
│  - validates arguments                 │
│  - runs adapter(s)                     │
│  - caches result in memory             │
│  - logs action + result shape          │
└──────────────┬─────────────────────────┘
               │ observations
               ▼
┌────────────────────────────────────────┐
│  Append observations to context        │
│  decrement remaining tool budget       │
└──────────────┬─────────────────────────┘
               │ loop until final answer
               │ or budget exhausted
               ▼
┌────────────────────────────────────────┐
│  Python validates final evidence       │
│  scorer.compute(evidence) → score      │
└──────────────┬─────────────────────────┘
               │
               ▼
┌────────────────────────────────────────┐
│  Reporter writes:                      │
│  - enriched.csv                        │
│  - provenance.jsonl                    │
│  - run_report.json                     │
└────────────────────────────────────────┘
```

### Tool-call lifecycle

1. **LLM decides.** The model receives the system prompt, the debtor row, and the history of prior observations. It emits either:
   - one or more `tool_calls` (each with a function name and JSON arguments), or
   - a `final_answer` JSON object containing structured evidence.

2. **Dispatch.** `ToolExecutor` maps each `tool_call.name` to a Python function in `sources/`. Arguments are validated against the JSON Schema registered for that tool.

3. **Execute.** The adapter performs the actual work (HTTP request, parse, lookup). It returns a JSON-serializable `dict` or `list[dict]`. Errors are caught and returned as `{ "error": "..." }` so the LLM can react instead of crashing the run.

4. **Cache.** The result is stored in an in-memory cache keyed by `(tool_name, normalized_arguments)`. If the LLM asks for the same thing again in the same row, the cached value is returned without a network request.

5. **Log.** Every call is appended to the run report as an `action` with `row_id`, `turn`, `tool`, `input`, `result`, and `reason`.

6. **Observe.** The result is serialized to a short string and returned to the LLM as a `tool` message. The loop continues.

7. **Budget check.** The run stops if the model returns a final answer or if the configured max number of tool calls is reached.

### Adapter layer

All adapters live under `src/contact_finder/sources/` and are **function-based**. Each adapter is a plain Python function with a consistent contract:

```python
@adapter(category="resolver")  # or "finder" / "verifier"
def opencorporates_lookup(name: str, state: str) -> list[dict]:
    """Look up a company in OpenCorporates by name and US state jurisdiction."""
    ...
```

The `@adapter` decorator provides cross-cutting behavior:
- logs entry/exit
- applies polite rate limiting
- checks the in-memory cache
- catches exceptions and returns a structured error
- redacts personal data before returning observations

Adapters are grouped by purpose:

| Category | Adapters | Purpose |
|---|---|---|
| **Entity resolvers** | `normalize_company`, `web_search`, `maps_search`, `opencorporates_lookup`, `sos_lookup` | Identify the real debtor entity and prove it matches the mailing address. |
| **Contact finders** | `scrape_contact_page`, `yellowpages_search`, `yelp_search`, `whois_lookup`, `wayback_search` | Discover business email addresses, phones, and named contacts. |
| **Verifier** | `mx_verify` | Passively check that an email domain is reachable without sending mail. |

### Tool definitions

The set of tools exposed to Groq is derived from the adapters. Each adapter registers:
- `name`: function name
- `description`: docstring
- `parameters`: JSON Schema built from type hints

This keeps the agent’s tool list in sync with the adapter layer automatically.

### Concurrency

If the LLM requests multiple independent tool calls in one turn (e.g. `opencorporates_lookup` + `sos_lookup` + `yellowpages_search`), the executor runs them concurrently up to a small pool (default 4). Results are returned together as separate observations.

### Scoring boundary

The LLM is **not** allowed to emit the numeric `confidence_score`. It returns an `EvidenceBundle` with fields like `role`, `address_match`, `source_trust`, `corroborated`, and `mx_verified`. A deterministic Python scorer then computes the final score using the formula in §10.

If the LLM returns a score anyway, it is ignored. If it cannot produce acceptable evidence, the pipeline falls back to `needs_human_review = true`.

### Failure modes

| Scenario | Behavior |
|---|---|
| Adapter throws | Caught, logged, returns `{ "error": "..." }` to LLM. |
| LLM emits invalid tool args | Validator rejects; LLM gets an error observation. |
| Budget exhausted | Row returns `needs_human_review = true` with dead-end log. |
| Score below threshold | `contact_email_or_phone` blanked, `needs_human_review = true`. |
| No entity resolved | Row returns `needs_human_review = true` with explanation. |

---

## 3. File structure

```
contact-finder/
├── README.md
├── PRD.md
├── spec.md
├── PLAN.md
├── requirements.txt
├── pyproject.toml
├── .env.example
├── data/
│   └── hard_cases.csv              # input (not committed)
├── out/                            # generated per run (gitignored)
├── src/
│   └── contact_finder/
│       ├── __init__.py
│       ├── __main__.py             # CLI entry point
│       ├── cli.py                  # argparse / typer interface
│       ├── config.py               # settings, env vars, constants
│       ├── models.py               # dataclasses / Pydantic models
│       ├── pipeline.py             # per-row orchestration
│       ├── agent.py                # LLM tool-use loop
│       ├── system_prompt.py        # prompt text for Groq
│       ├── normalizer.py           # name/address parsing
│       ├── scorer.py               # confidence formula
│       ├── reporter.py             # CSV / JSONL / run_report writers
│       ├── http_client.py          # polite requests + in-memory cache
│       ├── pii_guard.py            # strip/redact personal data
│       └── sources/
│           ├── __init__.py
│           ├── base.py             # common types / decorators
│           ├── normalize_company.py
│           ├── web_search.py
│           ├── maps_search.py
│           ├── opencorporates.py
│           ├── secretary_of_state.py
│           ├── website_contact.py
│           ├── yellowpages.py
│           ├── yelp.py
│           ├── whois_lookup.py
│           ├── wayback.py
│           └── mx_verify.py
└── tests/
    ├── test_normalizer.py
    ├── test_scorer.py
    ├── test_agent.py
    └── fixtures/
        └── sample_rows.json
```

---

## 4. Data models

All models are Pydantic dataclasses for validation and serialization.

### `DebtorRow`

```python
class DebtorRow(BaseModel):
    row_id: str                      # stable identifier (e.g. row index)
    full_name: Optional[str]         # recipient hint, often generic
    address: str                     # debtor mailing address
    company_name: str                # raw company name
    email: Optional[str]             # always empty in input
    phone_number: Optional[str]      # always empty in input
    company_issuing_the_invoice: str # creditor — must not be enriched
```

### `NormalizedInput`

```python
class NormalizedInput(BaseModel):
    raw_name: str
    clean_name: str
    legal_form: Optional[str]        # LLC, Inc, PLLC, etc.
    registration_code: Optional[str] # DUNS or state filing number
    street: Optional[str]
    city: Optional[str]
    state: Optional[str]             # two-letter code
    zip: Optional[str]
    country: str = "US"
```

### `EntityRecord`

```python
class EntityRecord(BaseModel):
    name: str
    jurisdiction: Optional[str]      # e.g. "DE", "California"
    registration_number: Optional[str]
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip: Optional[str]
    status: Optional[str]            # active / dissolved
    source: str                      # adapter name
    source_url: str
    match_reason: str                # why this record is believed correct
```

### `ContactCandidate`

```python
from typing import Literal

class ContactCandidate(BaseModel):
    name: Optional[str]
    role: Literal[
        "Accounts Payable",
        "Owner / Founder",
        "CFO / Finance Lead",
        "Office Manager",
        "Registered Agent",
        "Generic Business Contact",
    ]
    email: Optional[str]
    phone: Optional[str]
    source: str                      # adapter name
    source_url: str
    source_trust: float              # 0–1, see §10
    raw_evidence: str                # one-line human-readable provenance
```

### `EvidenceBundle`

Structured evidence returned for one candidate so the scorer can compute deterministically. Every bundle must be traceable to the sources that produced it.

```python
class EvidenceBundle(BaseModel):
    role: str
    address_match: float             # see §10
    source_trust: float              # highest-trust confirming source
    source_urls: list[str]           # public URLs / registry records supporting this candidate
    source_categories: list[str]     # e.g. ["registry", "website"] for corroboration checks
    corroborated: bool               # independent second source agrees
    mx_verified: bool                # email domain passes passive check
    candidate: ContactCandidate
```

### `EnrichedRow`

```python
class EnrichedRow(BaseModel):
    # original fields
    row_id: str
    full_name: Optional[str]
    address: str
    company_name: str
    email: Optional[str]
    phone_number: Optional[str]
    company_issuing_the_invoice: str

    # enrichment fields
    contact_name: Optional[str]
    contact_role: Optional[str]
    contact_email_or_phone: Optional[str]
    confidence_score: float
    evidence: str                    # human-readable reasoning
    source: str                      # pipe-separated URLs/records
    needs_human_review: bool
```

### `ProvenanceEntry`

```python
class ProvenanceEntry(BaseModel):
    row_id: str
    field: str                       # e.g. "contact_email_or_phone"
    value: str
    source: str
    source_url: str
    rationale: str
    timestamp: str
```

### `RunReport`

```python
class RunReport(BaseModel):
    summary: dict
    actions: list[dict]
    errors: list[dict]
```

---

## 5. Agent loop

The agent is implemented in `src/contact_finder/agent.py`.

### Tool-call mechanics

Groq native tool calling is used. Each adapter is exposed to the LLM as a JSON Schema tool definition. The model may request one or more tool calls in a single turn; Python executes them and returns observations.

### Loop contract

```python
def enrich_row(row: DebtorRow, config: Config) -> EnrichedRow:
    context = []
    creditor = normalize_name(row.company_issuing_the_invoice)

    for turn in range(config.max_tool_calls):      # default 8
        response = groq.chat.completions.create(
            model=config.model,
            messages=[
                system_message,
                user_message(row, creditor_hint=creditor),
                *context,
            ],
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
        )

        if response finishes with a final answer:
            bundles = parse_final_answer(response)
            return select_best_candidate(row, bundles)

        tool_calls = response.tool_calls
        observations = execute_tool_calls(tool_calls, row, creditor_hint=creditor)
        context.extend(tool_call_messages(tool_calls, observations))

    # budget exhausted
    return human_review(row, reason="tool-call budget exhausted")
```

### Creditor suppression

The creditor name is **never** sent to source adapters as a search target. Two guards enforce this:

1. **Input redaction.** `company_issuing_the_invoice` is normalized into a suppression token and withheld from all adapter inputs.
2. **Post-call validation.** Every `ContactCandidate` returned by an adapter is checked against the creditor name/website/domain. If a candidate matches the creditor, it is discarded and logged as `creditor_match_rejected`.

### Candidate ranking

The LLM does not choose a single winner. Its final answer returns a **ranked list** of `EvidenceBundle` objects, ordered by the LLM’s belief. Python then:

1. scores every bundle deterministically,
2. selects the highest-scoring bundle whose score is ≥ threshold,
3. falls back to `needs_human_review = true` if none qualify,
4. logs why lower-ranked bundles were not selected.

This prevents the LLM from under-selecting a stronger contact or over-selecting a weaker one.

### Final-answer schema

When the agent is ready to finish, it must return a JSON object matching:

```json
{
  "status": "final",
  "reasoning": "...",
  "ranked_bundles": [
    {
      "candidate": { /* ContactCandidate */ },
      "evidence": {
        "role": "Accounts Payable",
        "address_match": 1.0,
        "source_trust": 0.95,
        "source_urls": ["https://example.com/contact"],
        "source_categories": ["website"],
        "corroborated": true,
        "mx_verified": true
      }
    }
  ]
}
```

The Python layer validates every bundle, scores each one, and selects the best. The LLM **does not** emit the numeric `confidence_score`.

### System prompt highlights

The system prompt must instruct the LLM to:
- Never enrich `company_issuing_the_invoice`.
- Only use passive public sources; never send email/SMS/calls.
- Prefer business contacts; reject personal/home addresses and personal emails.
- Use address matching to disambiguate same-named companies.
- Return multiple ranked candidates when possible, not just one.
- Include the public URL or registry record that supports every candidate.
- Explain every tool choice briefly.

---

## 6. Tool definitions

Every tool returns a JSON-serializable result. Errors are caught by the adapter and returned as `{ "error": "..." }` so the LLM can react.

### `normalize_company`

```json
{
  "name": "normalize_company",
  "description": "Parse the raw company name and address into clean fields, legal form, registration code, and city/state/ZIP.",
  "parameters": {
    "type": "object",
    "properties": {
      "company_name": { "type": "string" },
      "address": { "type": "string" }
    },
    "required": ["company_name", "address"]
  }
}
```

### `web_search`

```json
{
  "name": "web_search",
  "description": "Run a public web search. Use for finding websites, registry pages, or directory listings.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": { "type": "string" }
    },
    "required": ["query"]
  }
}
```

### `maps_search`

```json
{
  "name": "maps_search",
  "description": "Search public map business listings by name and address. Helps confirm the right physical location.",
  "parameters": {
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "address": { "type": "string" }
    },
    "required": ["name", "address"]
  }
}
```

### `opencorporates_lookup`

```json
{
  "name": "opencorporates_lookup",
  "description": "Look up a company in OpenCorporates by name and US state jurisdiction. City and ZIP help disambiguate same-named companies.",
  "parameters": {
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "state": { "type": "string" },
      "city": { "type": "string" },
      "zip": { "type": "string" }
    },
    "required": ["name", "state"]
  }
}
```

### `sos_lookup`

```json
{
  "name": "sos_lookup",
  "description": "Query the relevant US Secretary of State business registry by company name and state. City and ZIP help disambiguate same-named companies.",
  "parameters": {
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "state": { "type": "string" },
      "city": { "type": "string" },
      "zip": { "type": "string" }
    },
    "required": ["name", "state"]
  }
}
```

### `scrape_contact_page`

```json
{
  "name": "scrape_contact_page",
  "description": "Fetch and extract business contacts from a company website page (e.g. /contact, /about).",
  "parameters": {
    "type": "object",
    "properties": {
      "url": { "type": "string" }
    },
    "required": ["url"]
  }
}
```

### `yellowpages_search`

```json
{
  "name": "yellowpages_search",
  "description": "Search Yellow Pages for a business by name and location.",
  "parameters": {
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "address": { "type": "string" }
    },
    "required": ["name", "address"]
  }
}
```

### `yelp_search`

```json
{
  "name": "yelp_search",
  "description": "Search Yelp for a business by name and location.",
  "parameters": {
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "address": { "type": "string" }
    },
    "required": ["name", "address"]
  }
}
```

### `whois_lookup`

```json
{
  "name": "whois_lookup",
  "description": "Query WHOIS for a domain. Returns admin/tech contact info if publicly available.",
  "parameters": {
    "type": "object",
    "properties": {
      "domain": { "type": "string" }
    },
    "required": ["domain"]
  }
}
```

### `wayback_search`

```json
{
  "name": "wayback_search",
  "description": "Find archived snapshots of a URL via the Wayback Machine.",
  "parameters": {
    "type": "object",
    "properties": {
      "url": { "type": "string" }
    },
    "required": ["url"]
  }
}
```

### `mx_verify`

```json
{
  "name": "mx_verify",
  "description": "Passively verify that an email domain has MX records and supports catch-all detection without sending mail. SMTP RCPT TO probes, if used, are optional, stop before DATA, and are logged as exploratory only.",
  "parameters": {
    "type": "object",
    "properties": {
      "email_or_domain": { "type": "string" }
    },
    "required": ["email_or_domain"]
  }
}
```

---

## 7. Adapter implementation notes

### `normalize_company`
- Strip legal forms (`LLC`, `Inc.`, `PLLC`, `Ltd.`) into a separate field.
- Extract DUNS codes (`DUNS N° \d+`) and state filing numbers if present.
- Parse US address with `usaddress` or a lightweight regex fallback.
- Return `NormalizedInput`.

### `web_search`
- Use Serper.dev free tier or direct search with polite rate limits.
- Return top 5 results: title, snippet, URL.
- Search queries should include company name + city/state.

### `maps_search`
- Use Google/Bing public Places API free tier or scrape public map result pages.
- Return business name, address, phone, website URL.
- Match address city/state before trusting.

### `opencorporates_lookup`
- Call `https://api.opencorporates.com/v0.4/companies/search`.
- Filter by US state jurisdiction.
- Return company name, registered address, company number, status, source URL.

### `sos_lookup`
- Tiered fallback strategy:
  1. If a state filing number is present in the input name, query the state registry directly.
  2. Otherwise, try OpenCorporates first (it often mirrors SOS data with a stable API).
  3. If OpenCorporates fails or returns ambiguous results, attempt a state-specific scraper for the debtor’s state.
  4. If no state-specific scraper exists, fall back to web search restricted to the state’s official registry domain, then scrape the result page.
- Return the same `EntityRecord` shape as OpenCorporates, including `city`/`state`/`zip` so address matching can happen deterministically.

### `scrape_contact_page`
- Fetch the URL with `http_client`.
- Extract emails, phones, and names/roles using regex + LLM parsing.
- LLM parsing only sees stripped page text; no personal addresses passed to Groq.
- Return `ContactCandidate` list.

### `yellowpages_search` / `yelp_search`
- Search public listing pages by name + city/state.
- Extract business phone, website, and any listed owner/manager name.
- Return `ContactCandidate` list with role `Generic Business Contact` unless a specific role is found.

### `whois_lookup`
- Query a WHOIS server or use a free API.
- Return admin/tech email and phone only if not privacy-protected.
- Validate that the registrant organization matches the debtor name.

### `wayback_search`
- Call `https://web.archive.org/cdx/search/cdx` for snapshots of a domain.
- Fetch the newest snapshot and run the same extraction as `scrape_contact_page`.

### `mx_verify`
- Resolve MX records for the domain. The presence of valid MX records is the primary passive signal and contributes the `mx_verified` bonus.
- Catch-all detection is performed by comparing MX records against known catch-all patterns if possible.
- An SMTP `RCPT TO` probe may be used **only** as an optional, exploratory step: connect, issue `MAIL FROM`, `RCPT TO`, and abort before `DATA`. The probe is logged, never used as the sole verification, and does not count as the primary `mx_verified` signal if the challenge’s passive-only interpretation is strict.
- Return `{ "mx_records": [...], "catch_all": bool, "smtp_probe_reachable": Optional[bool], "note": str }`.

### `pii_guard` redaction rules
Before any source result is returned to the LLM or persisted, the following rules are applied:
- Strip residential address keywords (`apt`, `unit`, `residence`, `home`) when paired with a non-business context.
- Redact personal email domains that are clearly consumer (`@gmail.com`, `@yahoo.com`, `@hotmail.com`, etc.). Business domains are retained.
- Mask or drop any full name that cannot be tied to a business role at the resolved entity.
- Drop phone numbers annotated as “home” or “mobile” in the source text.
- All redactions are logged so the reviewer can see what was removed and why.

---

## 8. Entity resolution strategy

Entity resolution runs **in parallel** across:
- `web_search`
- `maps_search`
- `opencorporates_lookup` (with optional `city`/`zip`)
- `sos_lookup` (with optional `city`/`zip`)

Results are ranked by address closeness:
1. Exact city + state + ZIP match
2. City + state match
3. State match
4. No address match but registration code matches

The LLM receives all results and must select an entity that meets at least the state-level match unless a registration code provides a stronger anchor. If multiple same-named companies appear, the LLM must explain why it chose one. If no entity can be confidently matched, the agent returns `needs_human_review = true`.

The resolved entity is then used to validate contact candidates: a contact is only accepted if its source page or listing can be tied to the resolved entity’s address or registration number.

---

## 9. Contact-discovery hierarchy

The LLM is free to call tools in any order, but the system prompt encourages this cost-first escalation:

1. **Company website** (`scrape_contact_page`) — direct, high trust.
2. **Maps / directories** (`maps_search`, `yellowpages_search`, `yelp_search`) — cheap, good for phone/website.
3. **Registries** (`opencorporates_lookup`, `sos_lookup`) — ground truth, but can return only registered agent.
4. **Technical / archive** (`whois_lookup`, `wayback_search`) — fallback when live site is dead.
5. **Verification** (`mx_verify`) — final confidence bump.

The agent stops early if it finds a high-confidence AP or owner contact from an independent source pair.

---

## 10. Confidence scoring

Scoring is deterministic and lives in `src/contact_finder/scorer.py`.

### Formula

```python
def score(evidence: EvidenceBundle) -> float:
    base = ROLE_BASE[evidence.role]
    score = base * evidence.address_match * evidence.source_trust
    if evidence.corroborated:
        score += 0.10
    if evidence.mx_verified:
        score += 0.05
    return round(min(1.0, score), 3)
```

The maximum unclamped score for any valid combination is bounded by design:
- Highest base role (AP = 0.95) × perfect address match (1.0) × highest source trust (1.0) = 0.95.
- With both bonuses, the score becomes 1.10, which is clamped to 1.0.
- This means the bonus is effectively a small boost, not a way to rescue a low-base candidate. A `Generic Business Contact` from a single web-search snippet can never reach 0.70 without strong corroboration.

### Selecting the best candidate

After the agent returns `ranked_bundles`, the pipeline runs:

```python
def select_best_candidate(row, bundles):
    scored = [(score(b), b) for b in bundles]
    scored.sort(reverse=True)

    for score_value, bundle in scored:
        if score_value >= THRESHOLD:
            return finalize(row, bundle, score_value)

    # none passed threshold
    return human_review(row, ranked_bundles=scored)
```

All bundles and their scores are written to `run_report.json` so the reviewer can see why the winner was chosen and why others were rejected.

### Role base

| Role | Base |
|---|---|
| Accounts Payable | 0.95 |
| Owner / Founder | 0.85 |
| CFO / Finance Lead | 0.80 |
| Office Manager | 0.70 |
| Registered Agent | 0.55 |
| Generic Business Contact | 0.50 |

### Address match

| Match level | Multiplier |
|---|---|
| Exact city + state + ZIP | 1.00 |
| City + state | 0.90 |
| State only | 0.75 |
| Unknown / no match | 0.50 |

### Source trust

| Source category | Trust |
|---|---|
| Registry (OpenCorporates, SOS) | 1.00 |
| Company website | 0.95 |
| WHOIS | 0.85 |
| Maps listing | 0.80 |
| Directory (Yellow Pages, Yelp, BBB) | 0.75 |
| Archived page | 0.65 |
| Web search snippet | 0.55 |

### Corroboration rule

A candidate is **corroborated** when a second source from a different category confirms the same contact channel (email, phone, or exact name+role) and the same entity address. The `source_categories` field in `EvidenceBundle` is used to verify independence.

### Evidence traceability

Every `EvidenceBundle` must contain `source_urls` and `source_categories`. Before a score is accepted, the pipeline checks that:
- `source_urls` is non-empty,
- every URL is reachable (well-formed and not empty),
- `source_categories` matches the adapters that produced the candidate.

If traceability is missing, the bundle is discarded and the row goes to `needs_human_review`.

---

## 11. Output generation

Implemented in `src/contact_finder/reporter.py`.

### `enriched.csv`

Appends the enrichment columns defined in the PRD to the original CSV rows. Rows are written in input order.

### `provenance.jsonl`

One JSON object per emitted value. Includes timestamp, row_id, field, value, source, source_url, and rationale.

### `run_report.json`

Single JSON file with:

```json
{
  "summary": {
    "total_rows": 5,
    "entities_resolved": 4,
    "contacts_found": 3,
    "contacts_accepted": 2,
    "needs_human_review": 3,
    "average_confidence": 0.68,
    "sources_used": ["website_contact", "yellowpages", "opencorporates"],
    "run_duration_seconds": 142,
    "timestamp": "2026-07-07T12:34:56Z"
  },
  "actions": [
    {
      "row_id": "1",
      "turn": 1,
      "tool": "normalize_company",
      "input": {...},
      "result": "success",
      "reason": "Parsed LLC and Chicago, IL address"
    }
  ],
  "errors": []
}
```

---

## 12. Error handling & observability

- Every adapter is wrapped in a decorator that catches exceptions and returns `{ "error": str(e) }`.
- Timeouts, 4xx/5xx, and parse failures are logged but do not crash the run.
- The agent loop logs every tool call, its arguments, and the result shape to `run_report.json`.
- CLI prints a per-row progress line: `row 1/5: resolved → 3 candidates → score 0.82`.

---

## 13. Compliance & privacy

- `pii_guard.py` redacts residential addresses and personal emails before they enter the LLM context.
- Adapters never send email/SMS/calls or scrape behind a login.
- No paywalled PII broker is used.
- Raw HTML and intermediate text are held only in memory and discarded at end-of-run.
- Enriched outputs and logs are retained for 30 days post-submission, then deleted.

---

## 14. CLI

```bash
python -m contact_finder enrich data/hard_cases.csv \
  --output out/enriched.csv \
  --provenance out/provenance.jsonl \
  --run-report out/run_report.json \
  --max-calls 8 \
  --model llama-3.3-70b-versatile \
  --threshold 0.7
```

### Required environment variables

- `GROQ_API_KEY`

### Optional environment variables

- `SERPER_API_KEY` — for web search; if omitted, direct search with rate limits is used.
- `REQUEST_DELAY` — seconds between HTTP requests (default 1.0).
- `MAX_TOOL_CALLS` — default 8.
- `CONFIDENCE_THRESHOLD` — default 0.7.

---

## 15. Configuration

`src/contact_finder/config.py` loads settings from environment variables and a `config.yaml` if present. It also exports:

- `ROLE_BASE`
- `ADDRESS_MATCH`
- `SOURCE_TRUST`
- `CORROBORATION_BONUS`
- `MX_BONUS`
- `DEFAULT_MODEL`
- `MAX_TOOL_CALLS`

---

## 16. Testing strategy

| Test | Purpose |
|---|---|
| `test_normalizer.py` | Verify name/address parsing, registration-code extraction, legal-form stripping, and creditor-name normalization. |
| `test_scorer.py` | Confirm confidence formula produces expected scores for sample evidence bundles and that scores never exceed 1.0. |
| `test_select_best_candidate.py` | Verify that multiple ranked bundles are scored and the highest passing bundle is selected; verify fallback to `needs_human_review`. |
| `test_provenance_chain.py` | Integration test: take an `EvidenceBundle`, produce an `EnrichedRow`, and assert that `ProvenanceEntry` records match `source_urls` and `source_categories`. |
| `test_creditor_suppression.py` | Assert that any candidate matching `company_issuing_the_invoice` is rejected, even if it would otherwise score above threshold. |
| `test_agent.py` | Mock Groq responses and assert the loop calls the right tools, respects the call budget, and handles creditor suppression. |
| `test_pii_guard.py` | Assert redaction rules strip consumer emails, residential keywords, and unrelated personal names. |
| Adapter tests | Mock HTTP responses for each source; assert correct `ContactCandidate` / `EntityRecord` shapes. |
| End-to-end | Run on a synthetic row with a known small local business and verify output schema, provenance coverage, and run-report completeness. |

---

## 17. Decisions baked into this spec

- Native Groq tool calling with `llama-3.3-70b-versatile` as default.
- Max 8 tool calls per row.
- Function-based adapters.
- In-memory HTTP cache only.
- Rule-based scorer owns the confidence score; the LLM only supplies evidence.
- LLM returns **ranked candidates**, not a single winner.
- Deterministic creditor suppression at the adapter input and output validation layers.
- Sources: OpenCorporates, Secretary of State, Yellow Pages, Yelp, plus website, maps, web search, WHOIS, Wayback, MX verify.
- CSV + JSONL + `run_report.json` outputs.
