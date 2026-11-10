"""Invoice workspace orchestration and explicit investigation start action."""

from __future__ import annotations

from typing import Any

from app.repositories.invoices import InvoiceRepository


class InvoiceService:
    def __init__(self, repository: InvoiceRepository, *, data_dir: str, investigation_db: str) -> None:
        self.repository = repository
        self.data_dir = data_dir
        self.investigation_db = investigation_db

    def list_invoices(self, **filters: Any) -> dict[str, Any]:
        return self.repository.list_invoices(**filters)

    def detail(self, invoice_id: str) -> dict[str, Any] | None:
        return self.repository.invoice_detail(invoice_id)

    def investigations(self, invoice_id: str) -> dict[str, Any] | None:
        detail = self.detail(invoice_id)
        if detail is None:
            return None
        vendor_id = detail.get("vendor_id")
        if not vendor_id:
            return {"available": False, "investigations": [], "reason": "invoice_vendor_relationship_unavailable"}
        return self.repository.investigations_for_invoice(vendor_id, invoice_id)

    def start_investigation(self, invoice_id: str) -> dict[str, Any] | None:
        detail = self.detail(invoice_id)
        if detail is None:
            return None
        vendor_id = detail.get("vendor_id")
        if not vendor_id:
            raise ValueError("Invoice vendor relationship is unavailable or ambiguous")

        existing = self.repository.existing_open_investigation(vendor_id, invoice_id)
        if existing:
            return {"created": False, "investigation": existing, "message": "An open investigation already exists for this invoice."}

        # Use the project's established service so vendor checks and persistence
        # remain owned by the investigation package rather than copied here.
        from src.investigation.service import start_investigation

        result = start_investigation(
            vendor_id,
            self.data_dir,
            self.investigation_db,
            invoice_id=invoice_id,
        )
        investigation = result.get("investigation")
        case_id = result.get("investigation_id")
        if case_id:
            cases = self.repository.investigations_for_invoice(vendor_id, invoice_id)
            persisted = next((row for row in cases.get("investigations", []) if row.get("investigation_id") == case_id), None)
            if persisted:
                investigation = persisted
        return {
            "created": True,
            "investigation": investigation,
            "message": "Investigation created with existing internal checks. External research is shown when available in persisted evidence.",
        }
