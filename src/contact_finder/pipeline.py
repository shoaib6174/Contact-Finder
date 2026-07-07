"""End-to-end enrichment pipeline."""

from __future__ import annotations

import asyncio
import csv
from datetime import datetime, timezone
from pathlib import Path

from contact_finder.agent import enrich_row
from contact_finder.config import Config
from contact_finder.models import DebtorRow, EnrichedRow, ProvenanceEntry, RunReport
from contact_finder.reporter import write_csv, write_jsonl, write_run_report


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def enrich_csv(
    input_path: Path,
    output_path: Path,
    provenance_path: Path,
    run_report_path: Path,
    config: Config,
) -> None:
    """Read input CSV, enrich each row, and write outputs."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    run_report_path.parent.mkdir(parents=True, exist_ok=True)

    rows = _read_input(input_path)

    enriched_rows: list[EnrichedRow] = []
    provenance: list[ProvenanceEntry] = []
    actions: list[dict] = []
    errors: list[dict] = []

    start = datetime.now(timezone.utc)

    for row in rows:
        try:
            result, _, row_actions, row_errors = await enrich_row(row, config)
        except Exception as exc:  # noqa: BLE001
            result = EnrichedRow(
                row_id=row.row_id,
                full_name=row.full_name,
                address=row.address,
                company_name=row.company_name,
                email=row.email,
                phone_number=row.phone_number,
                company_issuing_the_invoice=row.company_issuing_the_invoice,
                needs_human_review=True,
                evidence=f"Pipeline error: {exc}",
            )
            row_actions = []
            row_errors = [{"row_id": row.row_id, "error": str(exc)}]

        enriched_rows.append(result)
        provenance.extend(_build_provenance(result))
        actions.extend(row_actions)
        errors.extend(row_errors)
        await asyncio.sleep(config.request_delay)

    duration = (datetime.now(timezone.utc) - start).total_seconds()

    accepted = [r for r in enriched_rows if not r.needs_human_review]
    run_report = RunReport(
        summary={
            "total_rows": len(rows),
            "entities_resolved": len([r for r in enriched_rows if r.source]),
            "contacts_found": len([r for r in enriched_rows if r.contact_email_or_phone]),
            "contacts_accepted": len(accepted),
            "needs_human_review": len(enriched_rows) - len(accepted),
            "average_confidence": (
                sum(r.confidence_score for r in accepted) / len(accepted) if accepted else 0.0
            ),
            "run_duration_seconds": duration,
            "timestamp": _now(),
        },
        actions=actions,
        errors=errors,
    )

    write_csv(output_path, enriched_rows)
    write_jsonl(provenance_path, provenance)
    write_run_report(run_report_path, run_report)


def _build_provenance(row: EnrichedRow) -> list[ProvenanceEntry]:
    """Create provenance entries for accepted rows."""
    if row.needs_human_review or not row.source:
        return []

    entries = []
    sources = [s.strip() for s in row.source.split("|") if s.strip()]
    primary_url = sources[0] if sources else ""

    if row.contact_email_or_phone:
        entries.append(
            ProvenanceEntry(
                row_id=row.row_id,
                field="contact_email_or_phone",
                value=row.contact_email_or_phone,
                source="selected_candidate",
                source_url=primary_url,
                rationale=row.evidence,
                timestamp=_now(),
            )
        )
    if row.contact_name:
        entries.append(
            ProvenanceEntry(
                row_id=row.row_id,
                field="contact_name",
                value=row.contact_name,
                source="selected_candidate",
                source_url=primary_url,
                rationale=row.evidence,
                timestamp=_now(),
            )
        )
    if row.contact_role:
        entries.append(
            ProvenanceEntry(
                row_id=row.row_id,
                field="contact_role",
                value=row.contact_role,
                source="selected_candidate",
                source_url=primary_url,
                rationale=row.evidence,
                timestamp=_now(),
            )
        )
    return entries


def _read_input(path: Path) -> list[DebtorRow]:
    expected = [
        "full_name",
        "address",
        "company_name",
        "email",
        "phone_number",
        "company_issuing_the_invoice",
    ]

    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        has_expected = all(col in fieldnames for col in expected)

        rows = []
        for idx, record in enumerate(reader, start=1):
            if has_expected:
                rows.append(
                    DebtorRow(
                        row_id=str(idx),
                        full_name=record.get("full_name") or None,
                        address=record.get("address", ""),
                        company_name=record.get("company_name", ""),
                        email=record.get("email") or None,
                        phone_number=record.get("phone_number") or None,
                        company_issuing_the_invoice=record.get(
                            "company_issuing_the_invoice", ""
                        ),
                    )
                )
            else:
                values = list(record.values())
                rows.append(
                    DebtorRow(
                        row_id=str(idx),
                        full_name=_nth(values, 0),
                        address=_nth(values, 1, ""),
                        company_name=_nth(values, 2, ""),
                        email=_nth(values, 3),
                        phone_number=_nth(values, 4),
                        company_issuing_the_invoice=_nth(values, 5, ""),
                    )
                )
        return rows


def _nth(values: list[str], index: int, default: str | None = None) -> str | None:
    if index < len(values):
        value = values[index].strip()
        return value or default
    return default
