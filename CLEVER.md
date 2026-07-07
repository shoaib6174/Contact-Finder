# What I tried that was clever

> Proven tricks and failures from the `contact-finder` build.

---

## 1. Entity-resolution gate before contact extraction

**Hypothesis:** Most false positives come from asking the LLM to “find a contact” before the tool has proven *which* entity it is looking at. If the debtor row is synthetic or ambiguous, the LLM will happily hallucinate a plausible contact for the wrong company.

**What I ran:**
- First pass: agent loops with broad web search and no gate. On synthetic data it returned contacts for obviously fake rows.
- Second pass: added `entity_resolved()` in `src/contact_finder/entity_resolution.py` that returns `True` only when OpenCorporates, Secretary of State, maps, or a verified website corroborates the debtor **name + state + city/ZIP**.
- The fast path (`agent_fast.py`) now calls this gate immediately after the concurrent adapters and **skips the LLM scrape/extraction entirely** if the gate fails.

**What happened:**
- All synthetic rows now correctly route to `needs_human_review`.
- On the real challenge CSV, only **Lake Cable LLC** passed the gate and produced a verified contact.
- Cedar Ridge Plumbing, Summit Electric, Magnolia Family Dental, and Pioneer Landscaping all failed the gate and were rejected.

**Proof:** `out/hard_cases_run_report.json` (timestamp `2026-07-07T17:06:59.530433+00:00`):
- Row 1 accepted: `+1 888-505-1457` from `https://www.lakecable.com/`.
- Rows 2–5: `reason: "Entity not resolved in public records (registry/maps) before contact search."`

**What I learned:** The easiest way to avoid wrong contacts is to refuse to look for one until you can prove the entity. This costs recall on genuinely hard rows but is the right trade-off when a confident wrong answer is a hard reject.

---

## 2. Domain-name binding so scraping doesn’t chase the wrong site

**Hypothesis:** Web search for a company name often returns unrelated pages that mention the name — supplier lists, news articles, competitor directories. Scraping those for contacts produces nonsense like `help@summit.com` for a Summit Electric in Albuquerque.

**What I ran:**
- Added `_domain_matches()` in `scorer.py` and `_candidate_websites()` in `agent_fast.py`.
- `_candidate_websites()` only scrapes URLs whose registered domain contains the distinctive tokens of the company name.
- `score_evidence()` adds a `+0.15` bonus when the candidate’s source URL domain matches the debtor name.

**What happened:**
- Before the fix, Summit Electric returned a Facebook page for *Summit Electric Supply* and a generic `help@summit.com` email.
- After the fix, unrelated `summit.com`, WSDOT supplier pages, and similar directory noise are filtered out before scraping.
- Lake Cable’s `lakecable.com` domain matched the company name and received the bonus, pushing its score to **0.915**.

**Proof:** Row 1 `run_report.json`:
```json
"source_urls": ["https://www.lakecable.com/"],
"source_categories": ["website"],
"corroborated": true,
"candidate": { "role": "Office Manager", "phone": "+1 888-505-1457" }
```

**What I learned:** “Search then scrape” is dangerous without a domain filter. Binding the scrape step to the company name is a cheap, generalizable way to stay on the right entity.

---

## 3. Generic-token filtering for maps name-overlap (the Cedar Ridge fix)

**Hypothesis:** Maps and website lookups were opening the entity gate just because the debtor and a record shared an industry term (e.g., “plumbing”). For Cedar Ridge Plumbing in Lincoln, NE, this initially accepted a website for a Cedar City, UT plumber.

**What I ran:**
- Added `_GENERIC_NAME_TERMS` and `_distinctive_tokens()` in `entity_resolution.py`.
- Common noise words — `plumbing`, `electric`, `dental`, `family`, `services`, `landscaping`, etc. — are ignored when checking name overlap.
- The gate now requires a distinctive token (e.g., “cedar”, “ridge”, “summit”, “magnolia”) to match.

**What happened:**
- Cedar Ridge Plumbing no longer resolves against a generic “plumbing” company in the same city.
- `cedarridgeplumbing.com` (UT) is rejected because the address does not match the NE debtor address and the distinctive-token overlap no longer exists.
- Lake Cable still resolves because “lake” and “cable” are distinctive.

**Proof:** Row 3 result in `run_report.json`:
```json
{
  "row_id": "3",
  "tool": "agent_fast",
  "result": "human_review",
  "reason": "Entity not resolved in public records (registry/maps) before contact search."
}
```

**What I learned:** Same-name collisions are easy; same-*industry* collisions are subtle. Filtering generic terms makes name matching much safer without requiring an exact business-registry hit.

---

## Failures I kept

- **OpenCorporates registry lookup is currently dead.** It now returns `401 Invalid Api Token` for unauthenticated calls. The tool does not have a paid OpenCorporates key, so the registry branch of the gate is disabled in practice and the system relies on maps + website verification.
- **Summit Electric has a real-looking maps listing at the Albuquerque address**, but the only contacts found are social pages (Facebook) and generic help lines. The current scoring keeps these below the 0.70 threshold because the source is not entity-matched and not an AP role.
- **Magnolia Family Dental and Pioneer Landscaping** simply have no corroborated public presence at the debtor addresses. The tool fails honestly rather than invent contacts.

These failures are intentional: a conservative, explainable rejection is scored higher than a plausible guess.
