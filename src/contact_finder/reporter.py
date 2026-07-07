"""Output writers for CSV, JSONL, and run report."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contact_finder.models import EnrichedRow, ProvenanceEntry, RunReport


def write_csv(path: Path, rows: list[EnrichedRow]) -> None:
    if not rows:
        path.write_text("")
        return

    fieldnames = [
        "row_id",
        "full_name",
        "address",
        "company_name",
        "email",
        "phone_number",
        "company_issuing_the_invoice",
        "contact_name",
        "contact_role",
        "contact_email_or_phone",
        "confidence_score",
        "evidence",
        "source",
        "needs_human_review",
    ]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.model_dump(include=set(fieldnames)))


def write_jsonl(path: Path, entries: list[ProvenanceEntry]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(entry.model_dump_json() + "\n")


def write_run_report(path: Path, report: RunReport) -> None:
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
