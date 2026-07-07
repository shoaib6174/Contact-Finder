# Round 1 — Find the contact nobody else can find (plan-first, ~2h)

This challenge is **language-agnostic**. Use any language, any stack, any AI tools (Claude Code, Cursor,
Copilot — we expect and want it). We are not testing whether you know our stack. We are testing **how you
think**: do you plan and ask high-value questions before you build, and can you reach a contact that an
off-the-shelf tool can't?

> This is **Round 1 of 2**. Round 2 is released only to candidates who clear Round 1. Do Round 1 well.

---

## What we do

We collect overdue invoices for our clients. Each client hands us a spreadsheet of debtors. To chase a
payment we need a **reachable, correct contact** at the **debtor** company — ideally the person who
handles accounts payable, otherwise a usable corporate contact.

## The task

You are given **5 debtor rows** in [`data/hard_cases.csv`](data/hard_cases.csv). For each row, find the
best reachable contact you can **and give us the evidence to trust or reject it.** The rows are
**hand-picked to be HARD** — tiny companies, no obvious web presence, ambiguous names that collide with
many others, registration codes instead of clean names.

> **Getting ONE right and proving it beats half-answers on all five.** We care far more about one
> "impossible" row solved and proven than five easy guesses.

### Read the columns carefully
- `Company name` often carries a **registration code** (e.g. `DUNS N° …`) or a **legal form** (`LLC`,
  `Inc`, `PLLC`). That code is often the key to resolving the *real* entity.
- `Address` is the **debtor's** mailing address. It is your single best disambiguator when a name
  collides — use it.
- `Email` is **empty — this is what you find.**
- `Company issuing the invoice` is **our client — NOT the debtor. Never enrich it.** (The single most
  common failure is enriching the creditor instead of the debtor.)

### What a strong answer does
1. **Resolves the real entity** behind a messy name or a registration code — and **proves** it's the
   right one (e.g. the registry/D&B record's city matches the debtor address), not a same-named company.
2. **Reaches a contact by an unobvious path** when the obvious one is dead — public business registries,
   registered-agent records, the company's own site/socials, archived pages. Triangulate across
   **independent** sources; no single-source guesses.
3. **Verifies before trusting** (passive only — see rules below). A confident wrong answer is worse than
   **"no contact found, and here's every path I tried and why each one died."**
4. **Fails honestly.** We read the dead ends as carefully as the wins.

---

## Required — "what I tried that was clever" (≤1 page)

List the **2–3 most unconventional things you tried, INCLUDING the ones that failed.** For each: the
hypothesis, what you ran, what happened, what you learned.

> **Every claimed step must carry proof** — the exact query, the URL, a timestamp or screenshot, and one
> line on why that source links to *this* debtor. **Unproven cleverness scores 0.** We reproduce a random
> sample of your claimed tricks; a trick that doesn't reproduce scores 0 and flags the whole submission.

This page is where we read your creativity directly. Don't be modest, and don't sanitize the failures.

---

## Verification rules (read carefully — passive only)

**Allowed:** MX / catch-all detection, SMTP existence checks **without sending**, cross-referencing
public sources, public business-registry and registered-agent lookups, archived pages.

**Forbidden:** sending any email / SMS / web-form / call to a real person; paywalled-PII brokers; anything
that requires contacting a real person or scraping behind a login.

**Data minimization (required):** return **business-corporate contacts only.** Registered-agent records
sometimes list a **residential / personal address** (sole-proprietor agents) — do NOT include personal or
home addresses, personal emails, or any data beyond what's needed to reach the *business*. Don't store
personal data; delete any scraped data after you finish. If you use an LLM, don't paste personal data
into a third-party model.

**Acceptable evidence:** public registries (Secretary of State, D&B/DUNS), the company's own
site/socials, archived pages, search results with a clear link to *this* debtor.

---

## Tooling (use anything — these are just cheap options)
- Web search: [Serper](https://serper.dev) free tier is plenty; use your own free account.
- LLM: any provider. Anthropic Claude mirrors our stack; OpenAI / local are fine. Use your own key.
  (If you'd rather not spend, tell us — free tiers cover this; we can hand finalists a small capped key.)
- Scraping a public `/contact` or `/about` page is fair game. Paid contact APIs (RocketReach, Hunter) are
  **not required** — don't spend money; if your design would use one, say where it slots in.
- **Don't hardcode answers for these 5 rows.** Your approach should generalize to thousands of rows you
  haven't seen — the rows you'll never see coming are the point.

---

## STAGE A — PLAN ONLY (do this first, ~20 min)

**Commit `PLAN.md` BEFORE you write any solution code.** Use [`PLAN.template.md`](../PLAN.template.md).
The git timestamp on this commit is part of how we read your process — commit it on its own.

Your `PLAN.md` should cover: your resolution **architecture** (row → real entity → verified contact);
**sources & strategy** and how each fails; **quality** (dedupe, confidence scoring, provenance,
`cannot-verify` state, false-positive risk); **privacy/compliance**; and your **clarifying questions** —
for each: (a) why it matters, (b) your default assumption if we never answer, (c) what changes in your
design depending on the answer. **3 sharp questions beat 15 shallow ones.**

## STAGE B — BUILD (the rest of your time)

Build a minimal working slice that takes the 5 rows and, per row, outputs:
`contact_name`, `contact_role`, `contact_email_or_phone`, `confidence_score` (0–1, your own explainable
logic), `source` / evidence (every value traceable), and `needs_human_review` (true when you can't
verify). Questions are encouraged; if no one answers in time, state your assumptions and proceed.

---

## What to submit
1. **Code** — runnable, with a short README (how to run, what keys it needs).
2. **The 5 rows enriched** — each found contact with a 0–1 confidence score and the evidence/source. A
   colored spreadsheet (contact on the row below its source, fill-colored) is ideal; a clearly-labelled
   CSV/JSONL is an accepted fallback.
3. **The "what I tried that was clever" page** (above).
4. **`ABOUT.md`** at the repo root — template: [`../ABOUT.template.md`](../ABOUT.template.md).
5. `PLAN.md` committed **first**. **Do not squash or rewrite commits** before submitting — we read the
   commit timeline.
6. **The "how you START" recording (≤20 min) or written `PLAN.md` walkthrough** — see the *First gate*
   in the [README](../README.md#first-gate--show-how-you-start). Required and reviewed first: show a
   planning-first start before coding. Silent+captions or a written walkthrough are accepted; no judgment
   on accent/delivery/setup.

## How to submit
Your own repo (private is fine — add **`johnbanr`** as a collaborator), `PLAN.md` committed first, then
your slice + the 5 enriched rows + the clever-tricks page + `ABOUT.md`.

## How we score
| Area | Weight | What we look for |
|---|---|---|
| **Reasoning** (resolve the real entity; refuse the surface; go to the source of truth) | **Highest** | Did you prove the entity (e.g. registry/D&B city matches the debtor address)? Did you separate same-named companies instead of conflating them? |
| **Creativity / ingenuity** | **Highest** | Non-obvious, *correct* paths on the hard rows; clever, cheap, passive verification; the proven clever-tricks page |
| **The right questions** | High | Sharp clarifying questions in PLAN.md, each with why / default / what-changes |
| **Reliability** | Hard gate | No hallucinated emails; failures explicit and explained |
| **Debtor targeting** | Hard gate | You enriched the debtor, not the creditor (`Company issuing the invoice`) |
| **Generalization** | Hard gate | A resolver that scales, not a hardcoded path per company. Enumerating the scenarios = reject. |
| **Communication** | Medium | Write-up shows you understand your own trade-offs |

**Hard reject** regardless of code quality: you enriched the creditor; you faked a precise contact with
no evidence/`cannot-verify` state; or your approach hardcodes/enumerates the 5 rows instead of
generalizing.