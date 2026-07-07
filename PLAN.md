# PLAN.md

## Architecture

The contact finder is a **Python CLI tool** built around an agentic loop:

```
CSV row
  → normalize name/address
  → Groq LLM reasons and chooses source adapters as tools
  → ToolExecutor runs adapters (OpenCorporates, SOS, Yellow Pages, Yelp, website, maps, WHOIS, Wayback, MX verify)
  → LLM returns ranked candidate contacts with structured evidence
  → deterministic scorer computes confidence for each candidate
  → best passing candidate is emitted, or row is marked needs_human_review
  → outputs: enriched.csv + provenance.jsonl + run_report.json
```

Key components:

- **`ContactFinderAgent`** — Groq native tool-use loop (max 8 calls/row). It plans, calls adapters, and resolves ambiguity. It does not perform HTTP requests, parse pages, or emit scores.
- **`ToolExecutor`** — maps LLM tool calls to Python adapter functions, validates arguments, applies rate limits and caching, catches errors, and logs every action.
- **Adapters (`sources/`)** — function-based, each wrapping one public passive source. They return JSON-serializable records or errors.
- **`scorer.py`** — deterministic rule-based confidence formula using role, address match, source trust, corroboration, and MX verification.
- **`pii_guard.py`** — redacts residential addresses, consumer emails, and unrelated personal names before they reach the LLM or outputs.
- **`reporter.py`** — writes the CSV, JSONL provenance log, and JSON run report.

This design generalizes because every source is an adapter with the same contract, every row goes through the same loop, and no behavior is hardcoded for the five provided rows.

---

## Sources & strategy

### Entity resolution

Resolution runs in parallel across:

| Source | Why use it | How it fails |
|---|---|---|
| **OpenCorporates** | Free API, stable records for US LLCs/Inc. | Rate limits; misses some small businesses; stale data. |
| **Secretary of State registry** | Ground truth for legal name, status, registered agent, principal address. | No uniform API; many states require fragile scraping; some block automated access. |
| **Web search** | Finds registry pages, websites, directory listings. | Noisy; same-named companies; snippets lack address detail. |
| **Maps listings** | Confirms operating name and physical address. | Not every SMB is listed; address must match debtor to avoid wrong location. |

**Proving the right entity:** a candidate entity is accepted only when (a) its city/state matches the debtor address, (b) a registration code from the input matches, or (c) a phone/domain is cross-referenced with another source. The LLM must explain the match.

### Contact discovery

Discovery follows a cost-first escalation:

| Tier | Source | Why use it | How it fails |
|---|---|---|---|
| 1 | **Company website** (`/contact`, `/about`) | Direct AP/owner email or phone. | Many hard rows have no real site. |
| 2 | **Yellow Pages / Yelp** | Business phone + website; widely indexed. | Outdated; not every SMB; roles rarely listed. |
| 3 | **Maps listings** | Phone + address confirmation. | Limited contact depth. |
| 4 | **OpenCorporates / SOS** | Registered agent or officer filings. | Often only a registered agent; may be a residential address. |
| 5 | **WHOIS** | Admin/tech email if not privacy-protected. | Most domains now privacy-guarded. |
| 6 | **Wayback Machine** | Recovers dead contact pages. | Hit-or-miss; may have stale contacts. |
| 7 | **MX verify** | Confirms email domain accepts mail. | Only validates domain, not role or correctness of address. |

**Cross-source rule:** a contact is trusted only when independent sources agree on the same channel (email, phone, or exact name+role). A single-source guess is downgraded or rejected.

---

## Quality

- **Dedupe.** Candidates are compared by email, phone, or (name + role). Duplicates from the same source are collapsed; matches across sources trigger the corroboration bonus.
- **Confidence scoring.** Multiplicative formula: `role_base × address_match × source_trust`, plus small additive bonuses for independent corroboration (+0.10) and MX verification (+0.05). Threshold = 0.70.
- **Provenance.** Every emitted value carries source URLs. `provenance.jsonl` records row, field, value, source, URL, and rationale. `run_report.json` records every action and dead end.
- **`cannot-verify` state.** If no entity is resolved or no candidate reaches 0.70, the row returns an empty contact, `needs_human_review = true`, and a log of every path tried.
- **False-positive risk.** Mitigated by (a) creditor suppression validator, (b) address matching, (c) requiring corroboration for low-trust sources, and (d) forbidding the LLM from emitting the score itself.
- **Hallucination guard.** The LLM returns evidence bundles; a deterministic Python function computes the score. Any candidate missing source URLs is rejected.

---

## Privacy / compliance

- **Passive only.** No email/SMS/calls/web forms. No scraping behind a login. No paywalled PII brokers.
- **Business contacts only.** Registered-agent residential addresses, personal emails, and home phones are redacted and never returned.
- **LLM safety.** Groq is used only for reasoning over sanitized public text. Personal data is stripped before sending anything to the model.
- **Data minimization.** Raw HTML, screenshots, and intermediate text are held in memory only and discarded at end-of-run.
- **Retention.** Enriched outputs and logs are kept for 30 days after submission, then deleted.
- **Suppression.** `company_issuing_the_invoice` is treated as a suppression signal and is blocked from adapter inputs and output candidates.

---

## Clarifying questions

### 1. Registered-agent fallback

**Question:** If a Secretary of State or OpenCorporates record returns only a registered-agent name/address and no other contact path exists, should we return that as a `Registered Agent` contact with low confidence and `needs_human_review = true`, or treat the row as `cannot-verify`?

- **Why it matters:** The challenge says a registered-agent address is an acceptable contact-of-record when no direct AP path exists, but the rubric also prioritizes AP/owner/CFO contacts. The decision changes the human-review rate and the kind of evidence we present.
- **Default assumption:** We will return the registered agent as a fallback, label the role honestly as `Registered Agent`, cap the confidence at 0.55, and set `needs_human_review = true` because it is not an AP/owner contact.
- **What changes if answered:** If the evaluator prefers us not to return registered agents at all, we will treat them as dead ends and increase the `needs_human_review` rate without emitting a contact.

### 2. Scale of the proof-of-concept

**Question:** Should the submitted solution be judged only on the five provided hard rows, or do you want evidence that it generalizes to a larger unseen sample?

- **Why it matters:** The rubric says the approach must generalize and that enumerating scenarios for the five rows is a hard reject. However, the time budget may only allow running against the five rows. The answer determines how much synthetic/unseen testing we build in.
- **Default assumption:** We will optimize for the five rows as the demonstration, but the code will be adapter-driven and config-driven with no hardcoded row behavior. We will also run at least one synthetic row to prove generalization.
- **What changes if answered:** If a larger sample is required, we will allocate time to generate or find additional realistic SMB rows and run the tool against them, then report aggregate stats.

### 3. LLM reasoning under passive-only rules

**Question:** Is using Groq as a reasoning agent acceptable under the challenge’s passive-only constraint, provided the LLM only invokes passive public-source adapters and never sends messages or scrapes behind logins?

- **Why it matters:** Some interpretations of “passive only” focus on human outreach, while others might view any LLM-mediated reasoning as an active external query. We want to confirm the reasoning layer does not violate the spirit of the rules.
- **Default assumption:** We will proceed with Groq as an internal reasoning layer that calls only passive adapters, with all source results coming from public pages/registries and no outbound contact to debtors.
- **What changes if answered:** If an LLM reasoning layer is considered too active, we will downgrade Groq to a parsing/normalization helper and move the orchestration logic into deterministic Python heuristics.

---

## Implementation sketch

This is not a commitment to code; it is the rough order of work after `PLAN.md` is committed.

1. Scaffold Python project, config, models, and CLI.
2. Build `normalizer`, `pii_guard`, and `http_client` with polite delays.
3. Implement adapter stubs and tests for OpenCorporates, SOS, Yellow Pages, Yelp, website, maps, WHOIS, Wayback, MX verify.
4. Build `scorer` with the rule-based formula and unit tests.
5. Build `ContactFinderAgent` with Groq tool calling and creditor suppression.
6. Wire pipeline, reporter, and run-report generation.
7. Run against the five hard rows, record dead ends, and produce the enriched output + clever-tricks write-up.
