# Contact Finder — Product Requirements Document

> **Status:** Draft  
> **Scope:** Round 1 hiring challenge — enrich a CSV of hard debtor rows with one traceable, business-only contact per row.

---

## 1. Goal

Build a reusable, command-line contact-enrichment tool that takes a spreadsheet of debtor accounts and returns, for each row, the best reachable **business** contact it can prove, together with an explainable confidence score and full provenance. When no contact can be verified, the tool must fail honestly: emit an empty contact, set `needs_human_review = true`, and log every path it tried.

The primary user is an internal collections analyst who needs trustworthy leads, not guesses.

---

## 2. Job Story

> When I receive a spreadsheet of overdue accounts, I want to find a verified contact at the **debtor** company, so I can chase payment without wasting time on wrong numbers, dead emails, or contacts that belong to the creditor.

---

## 3. Input Schema

The tool reads a UTF-8 CSV with one header row. Column names match the provided file:

| Column | Meaning | Notes |
|---|---|---|
| `full_name` | Intended recipient or role hint at the debtor | May be empty or contain generic text such as `Accounts Payable`. It is **not** a reliable person identifier. |
| `address` | Debtor’s mailing address | Primary disambiguator when a company name collides with others. |
| `company_name` | Raw debtor company name | May include registration codes (e.g. `DUNS N° …`) or legal forms (`LLC`, `Inc`, `PLLC`). |
| `email` | Always empty in the input | This is the value we are trying to find. |
| `phone_number` | Always empty in the input | May be discovered during enrichment. |
| `company_issuing_the_invoice` | The creditor / client | **Must never be enriched.** The tool must treat this column as a suppression signal, not a target. |

### Input assumptions
- Rows are US businesses only.
- Addresses are US mailing addresses.
- A row may contain a registration code embedded in `company_name`.
- `full_name` is a hint, not a required match field.

---

## 4. Output Schema

The primary output is a CSV that preserves all input columns and appends enrichment fields:

| Output Column | Type | Description |
|---|---|---|
| `contact_name` | string or empty | Best verified contact, e.g. `Jane Doe` or `Accounts Payable Department`. Empty when nothing is verifiable. |
| `contact_role` | string or empty | `Accounts Payable`, `Owner`, `CFO / Finance Lead`, `Office Manager`, `Registered Agent`, `Generic Business Contact`, or empty. |
| `contact_email_or_phone` | string or empty | A business email or phone number. Empty when confidence is below threshold. |
| `confidence_score` | float 0–1 | Explainable score derived from role, source quality, address match strength, and independent corroboration. |
| `evidence` | string | Human-readable summary of why this value is believed to belong to this debtor (URLs, registry names, match reasons). |
| `source` | string | Pipe-separated list of public source URLs or registry records that support the contact. |
| `needs_human_review` | boolean | `true` when the row could not be confidently resolved or no contact passed verification. |

### Secondary output: provenance log (`provenance.jsonl`)
A machine-readable JSONL file is emitted alongside the CSV. Each line records one value derivation: the row identifier, the field name, the value, the source URL/record, and the match rationale. This keeps every emitted value traceable without cluttering the CSV.

### Tertiary output: run report (`run_report.json`)
A single JSON file that narrates the run and aggregates results. It must contain:

- **`summary`** — high-level stats:
  - `total_rows`
  - `entities_resolved`
  - `contacts_found`
  - `contacts_accepted` (confidence ≥ threshold)
  - `needs_human_review`
  - `average_confidence`
  - `sources_used` — list of source adapters exercised
  - `run_duration_seconds`
  - `timestamp`

- **`actions`** — chronological log of enrichment steps per row:
  - `row_id`
  - `step` (e.g. `normalize`, `search_web`, `query_registry`, `scrape_contact_page`, `verify_contact`, `dead_end`)
  - `source` / `adapter`
  - `query` or `url` attempted
  - `result` (`success`, `failure`, `no_match`, `low_confidence`)
  - `reason` — one-line explanation of what was learned

- **`errors`** — any adapter or parsing failures that did not crash the run.

This report satisfies the challenge requirement to show every path tried, including dead ends, in a reproducible, machine-readable form.

---

## 5. Functional Requirements

### FR-1 Entity resolution — find the real debtor, not a namesake
- The system shall normalize the raw `company_name` by stripping legal-form noise and extracting registration codes (e.g. DUNS, state filing numbers) when present.
- The system shall use `address` as the primary disambiguator: a resolved entity must match at least the state, and ideally the city/ZIP, of the debtor’s mailing address.
- The system shall never enrich the value in `company_issuing_the_invoice`.

### FR-2 Cost-first discovery hierarchy
- The system shall attempt the cheapest, lowest-effort resolution paths first and escalate to higher-effort paths only when cheaper paths do not produce a confident result.
- The hierarchy is defined in `spec.md`; the PRD only requires that cost/effort be a first-class ordering principle.
- Regardless of order, the final confidence score must reward independent corroboration across multiple sources.

### FR-2a Agentic reasoning
- The system may use an LLM (Groq) to reason about ambiguous rows, choose among sources, and resolve conflicts.
- The LLM shall invoke deterministic source adapters as tools; it shall not perform HTTP requests, parsing, or scoring itself.
- The LLM must receive compliance instructions forbidding outreach, personal data use, and creditor enrichment.

### FR-3 Contact target priority
- Preferred contact roles, in order:
  1. Accounts Payable (AP) contact
  2. Owner / Founder (for small businesses)
  3. CFO / Finance Lead
  4. Office Manager
  5. Registered Agent or other business contact-of-record
- The role label must be honest; a registered agent must not be labeled as AP.

### FR-4 Passive verification only
- Allowed: public business registries, DUNS/D&B public records, company-owned websites/social pages, archived pages, general web search, MX/catch-all detection.
- Optional and logged only: SMTP `RCPT TO` existence checks that stop before `DATA` and never actually send mail.
- Forbidden: sending email/SMS/calls/web forms, paywalled PII brokers, scraping behind a login, or any action that contacts a real person.

### FR-5 Confidence scoring
- Every emitted contact shall carry a `confidence_score` between 0 and 1.
- The score shall be explainable: it must be possible to reconstruct the score from documented source-quality weights, address-match strength, role relevance, and independent-corroboration bonuses.
- A default threshold of **0.7** shall separate accepted contacts from `needs_human_review` rows. The threshold is configurable.

### FR-6 Cannot-verify handling
- If the real entity cannot be resolved, or no contact passes the confidence threshold, the system shall:
  - leave `contact_email_or_phone` empty,
  - set `needs_human_review = true`,
  - populate `evidence` with the dead ends tried and why each failed.
- A confident wrong answer is worse than an honest “cannot verify.”

### FR-7 Provenance
- Every value in the output must be traceable to a public source URL or registry record.
- The provenance log shall record row id, field, value, source, and rationale.

### FR-8 Run reporting
- The tool shall emit a `run_report.json` file that records every significant action taken per row (sources queried, matches attempted, dead ends, verification results) and a summary of the run.
- The report must be detailed enough that a reviewer can reproduce the reasoning for each row without reading code.
- Dead ends and failures must be logged as explicitly as successes.

### FR-9 Generalization
- The implementation must not hardcode behavior for the five provided rows.
- Source adapters, normalization rules, and scoring weights must be configurable/extendable so the tool works on unseen rows.

### FR-10 Creditor suppression
- The system shall treat `company_issuing_the_invoice` as a suppression signal, not a target.
- The creditor name/website/domain shall be redacted from adapter inputs and shall never be returned as a contact.
- A deterministic post-adapter validator shall reject any candidate whose source URL, name, or domain matches the creditor.

### FR-11 Candidate ranking
- The LLM may return multiple candidate contacts in ranked order.
- The system shall score every candidate deterministically and select the highest-scoring candidate that meets the confidence threshold.
- If no candidate meets the threshold, the row shall be marked `needs_human_review = true`.

### FR-12 Evidence traceability
- Every confidence score must be derived from an `EvidenceBundle` that includes the public source URLs and source categories supporting the candidate.
- A candidate without source URLs or with mismatched source categories shall be rejected before scoring.

---

## 6. Non-Functional Requirements

### Compliance & privacy
- **NFR-1 Business contacts only.** Never return residential addresses, personal emails, or personal phone numbers.
- **NFR-2 Data minimization.** Scrape only what is needed. Do not persist raw HTML, screenshots, or intermediate personal data longer than the run.
- **NFR-2a PII redaction.** Before any source result is returned to the LLM or persisted, residential addresses, consumer email domains, and unrelated personal names are redacted. Redactions are logged.
- **NFR-3 No outreach.** No email, SMS, phone call, or web form submission to real people.
- **NFR-4 No paywalled PII brokers.** Free public sources only. If a paid API would improve the design, its slot is documented but not used.
- **NFR-5 Safe LLM use.** Groq powers the reasoning agent. Raw personal data is stripped before any text is sent to the model, and the LLM is not allowed to emit final scores or perform active verification itself.
- **NFR-6 Suppression support.** The design must support an opt-out / suppression list so a row or source can be excluded from future runs.
- **NFR-6a Retention policy.** Intermediate scraped content (HTML, raw page text, screenshots) is deleted at the end of each run. Enriched outputs, `provenance.jsonl`, and `run_report.json` are retained for **30 days after submission** to support reviewer reproduction, then deleted.

### Reliability & observability
- **NFR-7 Idempotent, reproducible runs.** Given the same input and config, the tool should produce the same logical output (external sources may change over time, but the pipeline is deterministic).
- **NFR-8 Logging.** Every source query, match decision, and dead end is logged at the appropriate level.
- **NFR-9 Rate limiting & respect.** HTTP requests use polite delays, clear user-agent strings, and honor `robots.txt`.
- **NFR-10 Failure isolation.** A failure in one source adapter must not crash the entire run; the row degrades gracefully to `needs_human_review`.

### Performance
- **NFR-11 Single-row budget.** A single hard row should complete in seconds to a few minutes of wall time on a normal connection.
- **NFR-12 Local-first.** The tool runs locally with no required remote service beyond free public web sources and the user’s own LLM key if an LLM is enabled.

---

## 7. Success Metrics

| Metric | Target | Why |
|---|---|---|
| Provenance coverage | 100% of emitted values | Hard gate: every value traceable |
| Creditor-enrichment incidents | 0 | Hard gate: never enrich `company_issuing_the_invoice` |
| Confident wrong contacts | 0 | Hard gate: precision over recall |
| Contacts with confidence ≥ 0.7 | As many as honestly achievable | Primary value metric |
| Honest `needs_human_review` rate | Accurate reflection of difficulty | High rate on hard rows is acceptable |
| Generalization evidence | No hardcoded row behavior | Hard gate |

---

## 8. Out of Scope

- Paid contact APIs (RocketReach, Hunter paid tier, Apollo, Clearbit, etc.) — their integration point may be documented, but no spending occurs.
- Active outreach or payment-collection workflow.
- Long-term storage / CRM integration.
- Real-time monitoring or scheduled batch jobs.
- Non-US entities.

---

## 9. Assumptions

- The user has a free web-search option (e.g. Serper free tier) or is willing to use direct search with polite rate limits.
- The user has a local Python environment (3.10+) and can install packages from PyPI.
- LLM usage uses Groq for agentic reasoning and source selection, using the user’s own Groq API key.
- The five hard rows are representative of the harder end of the target distribution; the design must degrade gracefully when no public contact exists.

---

## 10. Decisions Log

The following open questions from the initial draft are now decided:

1. **LLM usage:** Yes — Groq powers the agentic reasoning layer. The LLM invokes deterministic source adapters as tools and supplies structured evidence for scoring. Personal data is stripped before any text is sent to Groq.
2. **Source acceptability:** Any public, passive source is acceptable. The hierarchy orders sources by cost/effort, not by permission.
3. **Output style:** The CSV stays clean. The canonical trace is the combination of `provenance.jsonl` (value-level) and `run_report.json` (action-level + summary).
4. **Retention policy:** Intermediate scraped data is deleted at end-of-run. Enriched outputs and logs are kept for 30 days after submission, then deleted.
