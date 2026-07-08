"""PII redaction before LLM context or persistence."""

from __future__ import annotations

import re

from contact_finder.config import CONSUMER_DOMAINS, RESIDENTIAL_KEYWORDS


def redact_text(text: str) -> str:
    """Redact likely personal data from free-text source output."""
    if not text:
        return text

    # Redact consumer email addresses
    text = _redact_consumer_emails(text)

    # Redact lines containing residential keywords
    text = _redact_residential_lines(text)

    return text


def _redact_consumer_emails(text: str) -> str:
    pattern = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)")

    def repl(match: re.Match) -> str:
        domain = match.group(1).lower()
        if domain in CONSUMER_DOMAINS:
            return "[REDACTED-EMAIL]"
        return match.group(0)

    return pattern.sub(repl, text)


def _redact_residential_lines(text: str) -> str:
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        lower = line.lower()
        if any(re.search(rf"\b{re.escape(kw)}\b", lower) for kw in RESIDENTIAL_KEYWORDS):
            cleaned.append("[REDACTED-ADDRESS]")
        else:
            cleaned.append(line)
    return "\n".join(cleaned)


def is_consumer_email(email: str | None) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.split("@")[-1].lower()
    return domain in CONSUMER_DOMAINS


def normalize_name(name: str) -> str:
    """Lowercase and strip legal-form noise for matching."""
    name = name.lower()
    # Collapse possessive apostrophes: Lowe's -> Lowes
    name = re.sub(r"'s\b", "s", name)
    for suffix in ["llc", "inc", "corp", "pllc", "ltd", "co", "company"]:
        name = re.sub(rf"\b{suffix}\b", "", name)
    # collapse whitespace and punctuation
    name = re.sub(r"[^a-z0-9]+", " ", name).strip()
    return name


def names_match(a: str | None, b: str | None, threshold: float = 0.85) -> bool:
    """Rough name equality based on normalized tokens or substring containment."""
    if not a or not b:
        return False
    na, nb = normalize_name(a), normalize_name(b)
    tokens_a = set(na.split())
    tokens_b = set(nb.split())
    if not tokens_a or not tokens_b:
        return False

    # short unique name containment (e.g. FedEx inside FedEx Corporation)
    if len(tokens_a) == 1 or len(tokens_b) == 1:
        shorter = na if len(na) <= len(nb) else nb
        longer = nb if shorter == na else na
        if len(shorter) >= 3 and shorter in longer:
            return True

    overlap = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return overlap / union >= threshold
