"""Unit tests for invoice joins and investigation orchestration."""

from __future__ import annotations

import csv
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.repositories.invoices import InvoiceRepository  # noqa: E402
from app.services.invoices import InvoiceService  # noqa: E402


class InvoiceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()
        self.db = self.data / "investigations.sqlite3"
        self.write_csv("dashboard_data.csv", ["invoice_id", "po_id", "amount", "item_category", "description", "date", "payment_status", "submitted_by_employee_id", "rule_duplicate_invoice", "rule_shell_vendor", "gnn_risk_score", "gnn_prediction", "similarity", "rag_status", "best_match_service", "overall_status"], [
            ["INV-1", "PO-1", "1250.50", "IT", "Laptop", "2026-02-01", "Unpaid", "EMP1", "True", "False", "0.85", "1", "0.71", "mismatch", "Laptop", "Flagged"],
            ["INV-2", "PO-2", "450", "Office", "Paper", "2026-02-02", "Paid", "EMP2", "False", "False", "0.12", "0", "0.95", "ok", "Paper", "Clear"],
        ])
        self.write_csv("invoices.csv", ["invoice_id", "po_id", "amount", "date", "description"], [["INV-1", "PO-1", "1250.50", "2026-02-01", "Laptop"], ["INV-2", "PO-2", "450", "2026-02-02", "Paper"]])
        self.write_csv("purchase_orders.csv", ["po_id", "vendor_id", "amount", "item_category", "date", "created_by_employee_id", "approved_by_employee_id", "payment_terms"], [["PO-1", "V-1", "1200", "IT", "2026-01-10", "E1", "E2", "Net 30"], ["PO-2", "V-2", "400", "Office", "2026-01-11", "E2", "E3", "Net 30"]])
        self.write_csv("vendors.csv", ["vendor_id", "vendor_name", "email", "phone", "address", "bank_account", "registration_number", "vendor_category", "onboarding_date", "has_contract", "created_by_employee_id"], [["V-1", "Northwind Supply", "north@example.com", "999", "Main road", "1234567890", "REG-1", "IT", "2025-01-01", "Yes", "E1"], ["V-2", "Paper Co", "paper@example.com", "888", "Other road", "456789", "REG-2", "Office", "2025-01-02", "No", "E2"]])
        self.write_csv("contracts.csv", ["contract_id", "vendor_id", "contract_text", "agreed_rate", "start_date", "end_date"], [["C-1", "V-1", "Laptop supply at agreed rate.", "1200", "2026-01-01", "2026-12-31"]])
        self.write_csv("rag_similarity_scores.csv", ["invoice_id", "vendor_id", "contract_text", "similarity", "best_match_service", "best_match_score", "rag_status", "margin", "gap", "n_contracts", "service_source", "evidence"], [["INV-1", "V-1", "Laptop supply at agreed rate.", "0.71", "Laptop", "0.71", "mismatch", "0.1", "0.2", "1", "parsed", "Actual stored excerpt"]])
        self.write_csv("audit_log.csv", ["time", "invoice_id", "vendor_id", "decision", "note"], [["2026-02-05T10:30:00", "INV-1", "V-1", "Hold for more information", "Need supporting invoice"]])
        self.repo = InvoiceRepository(self.data, self.db)
        self.service = InvoiceService(self.repo, data_dir=str(self.data), investigation_db=str(self.db))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_csv(self, name: str, fields: list[str], rows: list[list[str]]) -> None:
        with (self.data / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            writer.writerows(rows)

    def test_invoice_search_sort_filter_and_pagination(self) -> None:
        filtered = self.service.list_invoices(query="northwind", status="flagged", signal="Duplicate invoice", limit=1)
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["invoice_id"], "INV-1")
        self.assertEqual(filtered["items"][0]["human_decision"], "Hold for more information")
        self.assertEqual(self.service.list_invoices(vendor_filter="V-2")["items"][0]["invoice_id"], "INV-2")

    def test_invoice_detail_joins_vendor_po_contract_detector_rag_and_audit(self) -> None:
        detail = self.service.detail("INV-1")
        self.assertEqual(detail["vendor_id"], "V-1")
        self.assertEqual(detail["vendor"]["vendor_name"], "Northwind Supply")
        self.assertEqual(detail["vendor"]["bank_account"], "****7890")
        self.assertEqual(detail["purchase_orders"][0]["po_id"], "PO-1")
        self.assertEqual(detail["contracts"][0]["contract_id"], "C-1")
        self.assertEqual(detail["detection"]["rules"][0]["rule"], "rule_duplicate_invoice")
        self.assertIn("same purchase order", detail["detection"]["rules"][0]["explanation"])
        self.assertEqual(detail["detection"]["rules"][0]["source"], "src/utils/rules_pandas.py")
        self.assertEqual(detail["detection"]["gnn"]["prediction"], True)
        self.assertEqual(detail["detection"]["rag"]["evidence"], "Actual stored excerpt")
        self.assertEqual(detail["human_decisions"][0]["time"], "2026-02-05T10:30:00")
        self.assertIsNone(self.service.detail("missing"))

    def test_missing_audit_log_is_unavailable_not_no_decision_recorded(self) -> None:
        (self.data / "audit_log.csv").unlink()
        listed = self.service.list_invoices(limit=10)
        self.assertTrue(all(row["human_decision_status"] == "unavailable" for row in listed["items"]))
        detail = self.service.detail("INV-1")
        self.assertFalse(detail["sources"]["audit"]["available"])
        self.assertEqual(detail["human_decisions"], [])

    def test_investigations_and_persisted_provenance_are_read_without_writes(self) -> None:
        with sqlite3.connect(self.db) as connection:
            connection.executescript("""CREATE TABLE investigations (
                investigation_id TEXT PRIMARY KEY, vendor_id TEXT, invoice_id TEXT, status TEXT,
                created_at TEXT, completed_at TEXT
            ); CREATE TABLE evidence (
                evidence_id TEXT PRIMARY KEY, investigation_id TEXT, check_type TEXT, finding TEXT,
                matched_entity TEXT, verification_status TEXT, source_type TEXT, created_at TEXT,
                source_url TEXT, retrieved_at TEXT
            );""")
            connection.execute("INSERT INTO investigations VALUES ('CASE-1','V-1','INV-1','completed','2026-02-03',NULL)")
            connection.execute("INSERT INTO evidence VALUES ('E-1','CASE-1','registration','Registry result',NULL,'official_registry_verified','government_registry','2026-02-03','https://registry.example/item','2026-02-03T10:00:00Z')")
        result = self.service.investigations("INV-1")
        evidence = result["investigations"][0]["evidence"][0]
        self.assertEqual(evidence["source_url"], "https://registry.example/item")
        self.assertEqual(evidence["retrieved_at"], "2026-02-03T10:00:00Z")
        self.assertEqual(evidence["verification_status"], "official_registry_verified")

    def test_start_uses_existing_service_only_after_explicit_call_and_is_idempotent_for_open_case(self) -> None:
        expected = {"investigation_id": "NEW-1", "investigation": {"investigation_id": "NEW-1", "status": "open"}}
        with patch("src.investigation.service.start_investigation", return_value=expected) as starter:
            result = self.service.start_investigation("INV-1")
        starter.assert_called_once_with("V-1", str(self.data), str(self.db), invoice_id="INV-1")
        self.assertTrue(result["created"])

        with sqlite3.connect(self.db) as connection:
            connection.execute("""CREATE TABLE investigations (
                investigation_id TEXT PRIMARY KEY, vendor_id TEXT, invoice_id TEXT, status TEXT,
                created_at TEXT, completed_at TEXT
            )""")
            connection.execute("INSERT INTO investigations VALUES ('OPEN-1','V-1','INV-1','open','2026-02-03',NULL)")
        with patch("src.investigation.service.start_investigation") as starter:
            repeated = self.service.start_investigation("INV-1")
        starter.assert_not_called()
        self.assertFalse(repeated["created"])
        self.assertEqual(repeated["investigation"]["investigation_id"], "OPEN-1")

    def test_open_vendor_level_case_prevents_automatic_duplicate_for_an_invoice(self) -> None:
        with sqlite3.connect(self.db) as connection:
            connection.execute("""CREATE TABLE investigations (
                investigation_id TEXT PRIMARY KEY, vendor_id TEXT, invoice_id TEXT, status TEXT,
                created_at TEXT, completed_at TEXT
            )""")
            connection.execute("INSERT INTO investigations VALUES ('VENDOR-CASE','V-1',NULL,'open','2026-02-03',NULL)")
        with patch("src.investigation.service.start_investigation") as starter:
            result = self.service.start_investigation("INV-1")
        starter.assert_not_called()
        self.assertFalse(result["created"])
        self.assertEqual(result["investigation"]["investigation_id"], "VENDOR-CASE")


@unittest.skipUnless(importlib.util.find_spec("fastapi") and importlib.util.find_spec("pydantic"),
                     "FastAPI/Pydantic are not installed in this Python environment")
class InvoiceResponseSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = InvoiceServiceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        with sqlite3.connect(self.fixture.db) as connection:
            connection.execute("""CREATE TABLE investigations (
                investigation_id TEXT PRIMARY KEY,
                vendor_id TEXT NOT NULL,
                invoice_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )""")

    def test_invoice_endpoint_response_shapes_validate(self) -> None:
        from app.schemas.invoices import (
            InvoiceDetailResponse,
            InvoiceInvestigationsResponse,
            InvoiceListResponse,
            StartInvoiceInvestigationResponse,
        )

        listing = InvoiceListResponse.parse_obj(self.fixture.service.list_invoices(limit=10))
        detail = InvoiceDetailResponse.parse_obj(self.fixture.service.detail("INV-1"))
        investigations = InvoiceInvestigationsResponse.parse_obj(self.fixture.service.investigations("INV-1"))
        started = StartInvoiceInvestigationResponse.parse_obj({
            "created": True,
            "investigation": {"investigation_id": "CASE-1", "status": "open"},
            "message": "created",
        })
        self.assertEqual(len(listing.items), 2)
        self.assertEqual(detail.invoice_id, "INV-1")
        self.assertTrue(investigations.available)
        self.assertTrue(started.created)


if __name__ == "__main__":
    unittest.main()
