"""Pydantic models for rows, candidates, evidence, and outputs."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class DebtorRow(BaseModel):
    row_id: str
    full_name: Optional[str] = None
    address: str
    company_name: str
    email: Optional[str] = None
    phone_number: Optional[str] = None
    company_issuing_the_invoice: str


class NormalizedInput(BaseModel):
    raw_name: str
    clean_name: str
    legal_form: Optional[str] = None
    registration_code: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: str = "US"


class EntityRecord(BaseModel):
    name: str
    jurisdiction: Optional[str] = None
    registration_number: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    status: Optional[str] = None
    source: str
    source_url: str
    match_reason: str


Role = Literal[
    "Accounts Payable",
    "Owner / Founder",
    "CFO / Finance Lead",
    "Office Manager",
    "Registered Agent",
    "Generic Business Contact",
]


class ContactCandidate(BaseModel):
    name: Optional[str] = None
    role: Role
    email: Optional[str] = None
    phone: Optional[str] = None
    source: str
    source_url: str
    source_trust: float = Field(ge=0.0, le=1.0)
    raw_evidence: str


class EvidenceBundle(BaseModel):
    role: Role
    address_match: float = Field(ge=0.0, le=1.0)
    source_trust: float = Field(ge=0.0, le=1.0)
    source_urls: list[str]
    source_categories: list[str]
    corroborated: bool
    mx_verified: bool
    candidate: ContactCandidate


class EnrichedRow(BaseModel):
    # original fields
    row_id: str
    full_name: Optional[str] = None
    address: str
    company_name: str
    email: Optional[str] = None
    phone_number: Optional[str] = None
    company_issuing_the_invoice: str

    # enrichment fields
    contact_name: Optional[str] = None
    contact_role: Optional[str] = None
    contact_email_or_phone: Optional[str] = None
    confidence_score: float = 0.0
    evidence: str = ""
    source: str = ""
    needs_human_review: bool = True


class ProvenanceEntry(BaseModel):
    row_id: str
    field: str
    value: str
    source: str
    source_url: str
    rationale: str
    timestamp: str


class RunReport(BaseModel):
    summary: dict
    actions: list[dict]
    errors: list[dict]
