"""Deterministic confidence scoring and candidate selection."""

from __future__ import annotations

from contact_finder.config import (
    ADDRESS_MATCH,
    CORROBORATION_BONUS,
    MX_BONUS,
    ROLE_BASE,
    SOURCE_TRUST,
)
from contact_finder.models import ContactCandidate, DebtorRow, EnrichedRow, EvidenceBundle
from contact_finder.pii_guard import is_consumer_email, normalize_name


def score_evidence(evidence: EvidenceBundle) -> float:
    """Compute a 0–1 confidence score from structured evidence."""
    base = ROLE_BASE.get(evidence.role, ROLE_BASE["Generic Business Contact"])
    address_mult = ADDRESS_MATCH.get(_match_label(evidence.address_match), 0.5)
    score = base * address_mult * evidence.source_trust

    if evidence.corroborated:
        score += CORROBORATION_BONUS
    if evidence.mx_verified:
        score += MX_BONUS

    return round(min(1.0, score), 3)


def _match_label(value: float) -> str:
    for label, mult in ADDRESS_MATCH.items():
        if abs(value - mult) < 0.01:
            return label
    return "unknown"


def select_best_candidate(
    row: DebtorRow,
    bundles: list[EvidenceBundle],
    threshold: float,
    creditor: str,
) -> tuple[EnrichedRow, list[dict]]:
    """Score all bundles, suppress creditor matches, and return best candidate."""
    scored: list[tuple[float, EvidenceBundle]] = []
    for bundle in bundles:
        if _matches_creditor(bundle.candidate, creditor):
            continue
        if not bundle.source_urls:
            continue
        score = score_evidence(bundle)
        scored.append((score, bundle))

    scored.sort(key=lambda x: x[0], reverse=True)

    if scored:
        best_score, best = scored[0]
        if best_score >= threshold:
            contact_value = best.candidate.email or best.candidate.phone or ""
            return (
                EnrichedRow(
                    row_id=row.row_id,
                    full_name=row.full_name,
                    address=row.address,
                    company_name=row.company_name,
                    email=row.email,
                    phone_number=row.phone_number,
                    company_issuing_the_invoice=row.company_issuing_the_invoice,
                    contact_name=best.candidate.name,
                    contact_role=best.candidate.role,
                    contact_email_or_phone=contact_value,
                    confidence_score=best_score,
                    evidence=best.candidate.raw_evidence,
                    source=" | ".join(best.source_urls),
                    needs_human_review=False,
                ),
                [b.model_dump() for _, b in scored],
            )

    # Nothing passed threshold
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
            evidence="No candidate met the confidence threshold.",
        ),
        [b.model_dump() for _, b in scored],
    )


def _matches_creditor(candidate: ContactCandidate, creditor: str) -> bool:
    """Reject candidates that clearly belong to the creditor."""
    creditor_norm = normalize_name(creditor)
    candidate_norm = normalize_name(candidate.name or "")
    source_norm = normalize_name(candidate.source_url)

    if creditor_norm and creditor_norm in candidate_norm:
        return True
    if creditor_norm and creditor_norm in source_norm:
        return True
    if candidate.email and creditor_norm in candidate.email.lower():
        return True
    return False


def evidence_from_candidate(
    candidate: ContactCandidate,
    address_match: float,
    corroborated: bool,
    mx_verified: bool,
) -> EvidenceBundle:
    """Build an EvidenceBundle from a candidate and metadata."""
    category = _category_for_source(candidate.source)
    return EvidenceBundle(
        role=candidate.role,
        address_match=address_match,
        source_trust=candidate.source_trust,
        source_urls=[candidate.source_url],
        source_categories=[category],
        corroborated=corroborated,
        mx_verified=mx_verified,
        candidate=candidate,
    )


def _category_for_source(source: str) -> str:
    source = source.lower()
    if source in {"opencorporates", "sos_lookup", "secretary_of_state"}:
        return "registry"
    if source in {"scrape_contact_page", "website"}:
        return "website"
    if source in {"whois_lookup", "whois"}:
        return "whois"
    if source in {"maps_search", "maps"}:
        return "maps"
    if source in {"yellowpages_search", "yelp_search", "directory"}:
        return "directory"
    if source in {"wayback_search", "archive"}:
        return "archive"
    return "web_search"


def is_verified_email(email: str | None) -> bool:
    """Quick sanity check: not consumer domain, looks like an email."""
    if not email or "@" not in email:
        return False
    return not is_consumer_email(email)
