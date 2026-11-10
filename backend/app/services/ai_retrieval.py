"""Unified read-only retrieval orchestration for Sentinel AI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.repositories.ai_retrieval import InvestigationEvidenceRepository, StructuredRetrievalRepository


class AIRetrievalService:
    """Combine structured records and persisted evidence without generating answers."""

    def __init__(self, data_dir: str | Path, investigation_db: str | Path) -> None:
        self.structured = StructuredRetrievalRepository(data_dir, investigation_db)
        self.evidence = InvestigationEvidenceRepository(investigation_db)

    def resolve_entity(self, entity_type: str, entity_id: str) -> dict[str, Any]:
        return self.structured.resolve_entity(entity_type, entity_id)

    def retrieve(self, query: str, *, invoice_id: str | None = None,
                 vendor_id: str | None = None, entity_type: str | None = None,
                 entity_id: str | None = None, intent: str | None = None,
                 limit: int = 12) -> dict[str, Any]:
        structured = self.structured.retrieve(
            query, invoice_id=invoice_id, vendor_id=vendor_id,
            entity_type=entity_type, entity_id=entity_id, intent=intent, limit=limit,
        )
        if not invoice_id:
            invoice_record = next((record for record in structured["records"]
                                   if record["record_type"] == "invoice" and record["source_id"] == f"invoice:{query.strip()}"), None)
            invoice_id = invoice_record["fields"].get("invoice", {}).get("invoice_id") if invoice_record else None
        if not vendor_id:
            vendor_record = next((record for record in structured["records"]
                                  if record["record_type"] == "vendor" and record["source_id"] == f"vendor:{query.strip()}"), None)
            vendor_id = vendor_record["fields"].get("vendor_id") if vendor_record else None
        evidence = self.evidence.retrieve(
            query, invoice_id=invoice_id, vendor_id=vendor_id, limit=limit,
        )
        return {
            "query": query,
            "structured": structured,
            "documents": {
                "records": evidence["records"],
                "availability": {"investigation_evidence": {
                    "available": evidence["available"], "reason": evidence["reason"]}},
                "status": evidence["status"],
            },
            "status": "matched" if structured["records"] or evidence["records"] else (
                "unavailable" if structured["status"] == "unavailable" or not evidence["available"]
                else "no_match"
            ),
            "safety": {
                "fraud_conclusion": None,
                "payment_decision": None,
                "note": "Retrieved records are evidence and signals for human review, not a fraud or payment decision.",
            },
        }
