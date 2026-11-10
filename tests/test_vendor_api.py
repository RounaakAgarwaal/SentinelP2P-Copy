"""Isolated coverage for vendor aggregation, detail and investigation actions."""

from __future__ import annotations

import csv
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.repositories.vendors import VendorRepository  # noqa: E402
from app.services.vendors import VendorService  # noqa: E402


class VendorServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()
        self.db = self.data / "investigations.sqlite3"
        self.write_csv("vendors.csv", ["vendor_id", "vendor_name", "email", "phone", "address", "bank_account", "registration_number", "vendor_category", "onboarding_date", "has_contract", "created_by_employee_id"], [
            ["V-1", "Northwind Vendor", "vendor@example.com", "5551234567", "1 Main Street", "123456789000", "REG-1", "IT", "2025-01-01", "Yes", "E1"],
            ["V-2", "Office Partner", "office@example.com", "5550000000", "2 Main Street", "99999999", "REG-2", "Office", "2025-03-01", "No", "E2"],
            ["V-3", "No Invoice Vendor", "", "", "3 Main Street", "123456789000", "REG-3", "IT", "2025-04-01", "No", "E2"],
        ])
        self.write_csv("employees.csv", ["employee_id", "email", "phone"], [["E-1", "employee@example.com", "5551234567"], ["E-2", "office@example.com", "5550000000"]])
        self.write_csv("invoices.csv", ["invoice_id", "po_id", "amount", "item_category", "description", "date", "payment_status", "submitted_by_employee_id"], [
            ["INV-1", "PO-1", "100.50", "IT", "Device", "2026-01-01", "Unpaid", "E-1"],
            ["INV-2", "PO-1", "250", "IT", "Service", "2026-01-02", "Paid", "E-2"],
        ])
        self.write_csv("purchase_orders.csv", ["po_id", "vendor_id", "amount", "item_category", "date", "created_by_employee_id", "approved_by_employee_id", "payment_terms"], [
            ["PO-1", "V-1", "300", "IT", "2025-12-20", "E-1", "E-2", "Net 30"],
        ])
        self.write_csv("dashboard_data.csv", ["invoice_id", "po_id", "amount", "date", "overall_status", "rule_duplicate_invoice", "rule_shell_vendor", "gnn_risk_score", "gnn_prediction", "rag_status"], [
            ["INV-1", "PO-1", "100.50", "2026-01-01", "Flagged", "True", "True", "0.85", "1", "mismatch"],
            ["INV-2", "PO-1", "250", "2026-01-02", "Clear", "False", "False", "0.15", "0", "ok"],
        ])
        self.write_csv("contracts.csv", ["contract_id", "vendor_id", "contract_text", "agreed_rate", "start_date", "end_date"], [["C-1", "V-1", "Device supply agreement", "300", "2025-01-01", "2026-12-31"]])
        self.write_csv("rag_similarity_scores.csv", ["invoice_id", "vendor_id", "similarity", "best_match_service", "rag_status", "evidence"], [["INV-1", "V-1", "0.62", "Device", "mismatch", "Stored RAG excerpt"]])
        self.write_csv("audit_log.csv", ["time", "invoice_id", "vendor_id", "decision", "note"], [["2026-01-03T12:00:00", "INV-1", "V-1", "Hold for more information", "Request receipt"]])
        self.repository = VendorRepository(self.data, self.db)
        self.service = VendorService(self.repository, data_dir=str(self.data), investigation_db=str(self.db))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_csv(self, name: str, fields: list[str], rows: list[list[str]]) -> None:
        with (self.data / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            writer.writerows(rows)

    def test_vendor_listing_search_filters_sort_and_pagination(self) -> None:
        result = self.service.list_vendors(query="northwind", status="flagged", category="IT", signal="GNN prediction", limit=1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["vendor_id"], "V-1")
        self.assertEqual(result["items"][0]["invoice_count"], 2)
        self.assertEqual(result["items"][0]["total_transaction_value"], 350.5)
        self.assertEqual(result["items"][0]["bank_account"], "****9000")
        no_invoice_ids = {row["vendor_id"] for row in self.service.list_vendors(status="no_invoices")["items"]}
        self.assertEqual(no_invoice_ids, {"V-2", "V-3"})
        page = self.service.list_vendors(sort_by="vendor_id", sort_dir="asc", limit=1, offset=1)
        self.assertEqual(page["items"][0]["vendor_id"], "V-2")

    def test_vendor_detail_has_context_matches_and_human_decision(self) -> None:
        detail = self.service.detail("V-1")
        self.assertEqual(detail["vendor"]["registration_number"], "REG-1")
        self.assertEqual(detail["vendor"]["bank_account"], "****9000")
        self.assertNotIn("123456789000", str(detail))
        self.assertEqual(len(detail["invoices"]), 2)
        self.assertEqual(detail["purchase_orders"][0]["po_id"], "PO-1")
        self.assertEqual(detail["contracts"][0]["contract_id"], "C-1")
        states = {item["check_type"]: item["verification_status"] for item in detail["internal_verification_findings"]}
        self.assertEqual(states["phone_match"], "match_found")
        self.assertEqual(states["email_match"], "no_match")
        self.assertEqual(states["bank_account_match"], "match_found")
        self.assertEqual(states["registration_number_match"], "no_match")
        self.assertEqual(detail["human_decisions"][0]["decision"], "Hold for more information")
        self.assertIsNone(self.service.detail("unknown"))

    def test_vendor_without_invoices_can_start_an_investigation(self) -> None:
        with patch("src.investigation.service.start_investigation", return_value={
            "investigation_id": "NEW-V3", "investigation": {"investigation_id": "NEW-V3", "vendor_id": "V-3", "status": "open"},
        }) as starter:
            result = self.service.start_investigation("V-3")
        starter.assert_called_once_with("V-3", str(self.data), str(self.db))
        self.assertTrue(result["created"])

    def test_open_vendor_investigation_prevents_duplicate(self) -> None:
        with sqlite3.connect(self.db) as connection:
            connection.execute("""CREATE TABLE investigations (
                investigation_id TEXT PRIMARY KEY, vendor_id TEXT, invoice_id TEXT, status TEXT,
                created_at TEXT, completed_at TEXT
            )""")
            connection.execute("INSERT INTO investigations VALUES ('OPEN-1','V-1',NULL,'open','2026-01-01',NULL)")
        with patch("src.investigation.service.start_investigation") as starter:
            result = self.service.start_investigation("V-1")
        starter.assert_not_called()
        self.assertFalse(result["created"])
        self.assertEqual(result["investigation"]["investigation_id"], "OPEN-1")

    def test_missing_internal_employee_records_do_not_become_no_match(self) -> None:
        (self.data / "employees.csv").unlink()
        detail = self.service.detail("V-1")
        phone = next(item for item in detail["internal_verification_findings"] if item["check_type"] == "phone_match")
        self.assertEqual(phone["verification_status"], "incomplete_missing_source")
        self.assertEqual(phone["coverage_status"], "partial")


@unittest.skipUnless(importlib.util.find_spec("fastapi") and importlib.util.find_spec("pydantic"),
                     "FastAPI/Pydantic are not installed in this Python environment")
class VendorResponseSchemaTests(unittest.TestCase):
    def test_vendor_response_shapes_validate(self) -> None:
        from app.schemas.vendors import VendorDetailResponse, VendorListResponse

        fixture = VendorServiceTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        listing = VendorListResponse.parse_obj(fixture.service.list_vendors(limit=5))
        detail = VendorDetailResponse.parse_obj(fixture.service.detail("V-1"))
        self.assertEqual(len(listing.items), 3)
        self.assertEqual(detail.vendor_id, "V-1")


if __name__ == "__main__":
    unittest.main()
