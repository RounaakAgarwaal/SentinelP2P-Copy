"""Small orchestration boundary for starting an investigation independently."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .inputs import build_investigation_input
from .storage import create_evidence, create_investigation


def start_investigation(
    vendor_id: str,
    data_dir: str | Path,
    db_path: str | Path,
    *,
    invoice_id: str | None = None,
    vendor_csv: str | Path | None = None,
) -> dict[str, Any]:
    """Build an investigation payload and persist the case plus internal-check evidence."""
    payload = build_investigation_input(vendor_id, data_dir, invoice_id=invoice_id, vendor_csv=vendor_csv)
    investigation = create_investigation(db_path, vendor_id, invoice_id=invoice_id)
    evidence_records = []
    for finding in payload["internal_verification_findings"]:
        stored = create_evidence(
            db_path,
            investigation_id=investigation["investigation_id"],
            check_type=finding["check_type"],
            finding=finding["finding"],
            matched_entity=finding["matched_entity"],
            verification_status=finding["verification_status"],
            source_type=finding["source_type"],
            created_at=finding["created_at"],
        )
        evidence_records.append(stored)

    payload["investigation"] = investigation
    payload["investigation_id"] = investigation["investigation_id"]
    payload["persisted_evidence"] = evidence_records
    return payload
