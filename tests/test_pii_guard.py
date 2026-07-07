"""Tests for PII guard."""

from contact_finder.pii_guard import (
    is_consumer_email,
    names_match,
    redact_text,
)


def test_redact_consumer_email():
    text = "Contact us at owner@gmail.com or office@company.com"
    cleaned = redact_text(text)
    assert "owner@gmail.com" not in cleaned
    assert "office@company.com" in cleaned


def test_redact_residential_line():
    text = "\n".join([
        "Business address: 123 Main St",
        "Home address: 456 Oak Ave, Apt 2",
    ])
    cleaned = redact_text(text)
    assert "456 Oak Ave" not in cleaned
    assert "[REDACTED-ADDRESS]" in cleaned
    assert "123 Main St" in cleaned


def test_is_consumer_email():
    assert is_consumer_email("bob@gmail.com") is True
    assert is_consumer_email("ap@company.com") is False
    assert is_consumer_email(None) is False


def test_names_match():
    assert names_match("Lake Cable LLC", "Lake Cable") is True
    assert names_match("FedEx Corporation", "FedEx") is True
    assert names_match("Acme Plumbing", "Beta Roofing") is False
