"""Vendor intelligence orchestration on top of existing vendor checks/storage."""

from __future__ import annotations

from threading import Lock
from typing import Any

from app.repositories.vendors import VendorRepository

_start_lock = Lock()


class VendorService:
    def __init__(self, repository: VendorRepository, *, data_dir: str, investigation_db: str) -> None:
        self.repository = repository
        self.data_dir = data_dir
        self.investigation_db = investigation_db

    def list_vendors(self, **filters: Any) -> dict[str, Any]:
        return self.repository.list_vendors(**filters)

    def detail(self, vendor_id: str) -> dict[str, Any] | None:
        result = self.repository.vendor_detail(vendor_id)
        if result is None:
            return None
        from src.investigation.checks import run_internal_vendor_checks

        try:
            result["internal_verification_findings"] = run_internal_vendor_checks(vendor_id, self.data_dir)
        except (FileNotFoundError, OSError, ValueError):
            result["internal_verification_findings"] = [
                {
                    "check_type": check_type,
                    "finding": "Internal check unavailable because required vendor data could not be read.",
                    "matched_entity": None,
                    "verification_status": "unavailable",
                    "coverage_status": "unavailable",
                    "source_type": "internal_records",
                    "created_at": None,
                }
                for check_type in ("phone_match", "email_match", "bank_account_match", "registration_number_match")
            ]
        return result

    def start_investigation(self, vendor_id: str) -> dict[str, Any] | None:
        if self.repository.vendor_detail(vendor_id) is None:
            return None
        with _start_lock:
            existing = self.repository.existing_open_investigation(vendor_id)
            if existing:
                return {
                    "created": False,
                    "investigation": existing,
                    "message": "An open investigation already exists for this vendor.",
                }
            from src.investigation.service import start_investigation

            created = start_investigation(vendor_id, self.data_dir, self.investigation_db)
            case = created.get("investigation")
            cases = self.repository.investigations_for_vendor(vendor_id)
            if cases.get("available"):
                case_id = created.get("investigation_id")
                persisted = next((item for item in cases["investigations"] if item.get("investigation_id") == case_id), None)
                if persisted:
                    case = persisted
            return {
                "created": True,
                "investigation": case,
                "message": "Investigation created using the existing internal verification service.",
            }
