"""Tests for confidence scorer and candidate selection."""

import pytest

from contact_finder.models import ContactCandidate, DebtorRow, EvidenceBundle
from contact_finder.scorer import (
    evidence_from_candidate,
    score_evidence,
    select_best_candidate,
)


def _candidate(role: str = "Accounts Payable", source: str = "website", trust: float = 0.95):
    return ContactCandidate(
        name="Jane Doe",
        role=role,  # type: ignore[arg-type]
        email="ap@example.com",
        phone=None,
        source=source,
        source_url="https://example.com/contact",
        source_trust=trust,
        raw_evidence="Email on contact page",
    )


def test_score_ap_website_perfect():
    ev = EvidenceBundle(
        role="Accounts Payable",
        address_match=1.0,
        source_trust=0.95,
        source_urls=["https://example.com/contact"],
        source_categories=["website"],
        corroborated=False,
        mx_verified=False,
        candidate=_candidate(),
    )
    assert score_evidence(ev) == pytest.approx(0.95 * 1.0 * 0.95, rel=1e-3)


def test_score_with_bonuses_clamps_to_one():
    ev = EvidenceBundle(
        role="Accounts Payable",
        address_match=1.0,
        source_trust=1.0,
        source_urls=["https://registry.example"],
        source_categories=["registry"],
        corroborated=True,
        mx_verified=True,
        candidate=_candidate(source="opencorporates", trust=1.0),
    )
    assert score_evidence(ev) == 1.0


def test_generic_contact_cannot_reach_threshold():
    ev = EvidenceBundle(
        role="Generic Business Contact",
        address_match=0.75,
        source_trust=0.55,
        source_urls=["https://search.example"],
        source_categories=["web_search"],
        corroborated=False,
        mx_verified=False,
        candidate=_candidate(role="Generic Business Contact", source="web_search", trust=0.55),
    )
    assert score_evidence(ev) < 0.7


def test_select_best_candidate_picks_highest():
    row = DebtorRow(
        row_id="1",
        company_name="Example LLC",
        address="123 Main, Springfield, IL 62701",
        company_issuing_the_invoice="Client",
    )
    low = EvidenceBundle(
        role="Generic Business Contact",
        address_match=0.75,
        source_trust=0.55,
        source_urls=["https://search.example"],
        source_categories=["web_search"],
        corroborated=False,
        mx_verified=False,
        candidate=_candidate(role="Generic Business Contact", source="web_search", trust=0.55),
    )
    high = EvidenceBundle(
        role="Accounts Payable",
        address_match=1.0,
        source_trust=0.95,
        source_urls=["https://example.com/contact"],
        source_categories=["website"],
        corroborated=True,
        mx_verified=True,
        candidate=_candidate(),
    )
    enriched, _ = select_best_candidate(row, [low, high], threshold=0.7, creditor="Client")
    assert enriched.contact_role == "Accounts Payable"
    assert enriched.confidence_score >= 0.7
    assert not enriched.needs_human_review


def test_select_best_candidate_suppresses_creditor():
    row = DebtorRow(
        row_id="1",
        company_name="Example LLC",
        address="123 Main, Springfield, IL 62701",
        company_issuing_the_invoice="FedEx",
    )
    bad = EvidenceBundle(
        role="Accounts Payable",
        address_match=1.0,
        source_trust=0.95,
        source_urls=["https://fedex.com/contact"],
        source_categories=["website"],
        corroborated=False,
        mx_verified=False,
        candidate=ContactCandidate(
            name="FedEx Billing",
            role="Accounts Payable",
            email="billing@fedex.com",
            source="website",
            source_url="https://fedex.com/contact",
            source_trust=0.95,
            raw_evidence="Creditor contact",
        ),
    )
    enriched, _ = select_best_candidate(row, [bad], threshold=0.7, creditor="FedEx")
    assert enriched.needs_human_review is True
    assert enriched.contact_email_or_phone is None
