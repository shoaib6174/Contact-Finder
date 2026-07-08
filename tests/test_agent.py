"""Tests for the agent loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from contact_finder.config import Config
from contact_finder.models import DebtorRow
from contact_finder.agent import enrich_row


@pytest.fixture
def config():
    cfg = Config()
    cfg.groq_api_key = "fake-key"
    cfg.default_model = "llama-3.1-8b-instant"
    cfg.max_tool_calls = 4
    cfg.confidence_threshold = 0.7
    return cfg


@pytest.fixture
def row():
    return DebtorRow(
        row_id="1",
        company_name="Example LLC",
        address="123 Main St, Springfield, IL 62701",
        company_issuing_the_invoice="Client",
    )


def _make_tool_call(name: str, arguments: dict, call_id: str = "call_1"):
    tc = MagicMock()
    tc.id = call_id
    tc.type = "function"
    tc.function.name = name
    tc.function.arguments = __import__("json").dumps(arguments)
    return tc


def _make_message(content: str | None = None, tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    return msg


def _make_choice(message):
    choice = MagicMock()
    choice.message = message
    return choice


def _make_response(choices):
    resp = MagicMock()
    resp.choices = choices
    return resp


@pytest.mark.asyncio
async def test_agent_calls_tool_and_returns_human_review_on_empty(config, row):
    """The agent calls a tool and, with no candidates, marks the row for review."""

    mock_completion = AsyncMock()
    mock_completion.side_effect = [
        _make_response([
            _make_choice(_make_message(tool_calls=[_make_tool_call("normalize_company", {"company_name": "Example LLC", "address": "123 Main St, Springfield, IL 62701"})])),
        ]),
        _make_response([
            _make_choice(_make_message(content='{"status": "final", "reasoning": "No contacts found", "ranked_bundles": []}')),
        ]),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_completion

    with patch("contact_finder.groq_client.AsyncGroq", return_value=mock_client):
        enriched, _, actions, errors = await enrich_row(row, config)

    assert enriched.needs_human_review is True
    assert any(a["tool"] == "normalize_company" for a in actions)
    assert not errors


@pytest.mark.asyncio
async def test_agent_returns_accepted_contact(config, row):
    """The agent returns a candidate that passes the confidence threshold."""

    bundle = {
        "candidate": {
            "name": "Jane Doe",
            "role": "Accounts Payable",
            "email": "ap@example.com",
            "phone": None,
            "source": "website",
            "source_url": "https://example.com/contact",
            "source_trust": 0.95,
            "raw_evidence": "Email on contact page",
        },
        "evidence": {
            "role": "Accounts Payable",
            "address_match": 1.0,
            "source_trust": 0.95,
            "source_urls": ["https://example.com/contact"],
            "source_categories": ["website"],
            "corroborated": True,
            "mx_verified": True,
        },
    }

    final_payload = {"status": "final", "reasoning": "Found contact", "ranked_bundles": [bundle]}
    mock_completion = AsyncMock()
    mock_completion.side_effect = [
        _make_response([
            _make_choice(_make_message(tool_calls=[
                _make_tool_call("opencorporates_lookup", {"name": "Example LLC", "state": "IL"}, "call_1"),
            ])),
        ]),
        _make_response([
            _make_choice(_make_message(content=__import__("json").dumps(final_payload))),
        ]),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_completion

    fake_registry = [
        {
            "name": "Example LLC",
            "jurisdiction": "us_il",
            "state": "IL",
            "city": "Springfield",
            "zip": "62701",
            "address": "123 Main St",
            "source_url": "https://opencorporates.com/companies/us_il/12345",
            "match_reason": "test",
        }
    ]

    with patch("contact_finder.groq_client.AsyncGroq", return_value=mock_client):
        with patch("contact_finder.agent._execute_tool", new=AsyncMock(return_value=fake_registry)):
            enriched, _, actions, errors = await enrich_row(row, config)

    assert enriched.needs_human_review is False
    assert enriched.contact_role == "Accounts Payable"
    assert enriched.confidence_score >= 0.7
    assert not errors
