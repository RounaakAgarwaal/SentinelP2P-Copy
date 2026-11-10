"""Offline tests for Sentinel AI's read-only retrieval foundation."""

from __future__ import annotations

import csv
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.ai_retrieval import AIRetrievalService  # noqa: E402
from app.services.ai_chat import AIChatService  # noqa: E402


class AIRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()
        self.db = self.data / "investigations.sqlite3"
        self.write_csv("vendors.csv", ["vendor_id", "vendor_name", "email", "phone", "address", "bank_account", "registration_number", "vendor_category", "onboarding_date", "has_contract", "created_by_employee_id"], [
            ["V-1", "Northwind Supply", "vendor@example.com", "5551234567", "1 Main St", "123456789000", "REG-1", "IT", "2025-01-01", "Yes", "E-1"],
        ])
        self.write_csv("employees.csv", ["employee_id", "name", "email", "phone", "department", "role", "join_date"], [
            ["E-1", "Avery Auditor", "avery@example.com", "5550000000", "Finance", "Auditor", "2024-01-01"],
        ])
        self.write_csv("invoices.csv", ["invoice_id", "po_id", "amount", "item_category", "description", "date", "payment_status", "submitted_by_employee_id"], [
            ["INV-1", "PO-1", "1250.50", "IT", "Laptop equipment", "2026-01-02", "Unpaid", "E-1"],
        ])
        self.write_csv("purchase_orders.csv", ["po_id", "vendor_id", "amount", "item_category", "date", "created_by_employee_id", "approved_by_employee_id", "payment_terms"], [
            ["PO-1", "V-1", "1500", "IT", "2025-12-20", "E-1", "E-1", "Net 30"],
        ])
        self.write_csv("contracts.csv", ["contract_id", "vendor_id", "contract_text", "agreed_rate", "start_date", "end_date"], [
            ["C-1", "V-1", "Supply of laptop equipment under annual terms", "1500", "2025-01-01", "2026-12-31"],
        ])
        self.write_csv("dashboard_data.csv", ["invoice_id", "po_id", "amount", "date", "overall_status", "rule_duplicate_invoice", "gnn_risk_score", "gnn_prediction", "rag_status"], [
            ["INV-1", "PO-1", "1250.50", "2026-01-02", "Flagged", "True", "0.82", "True", "mismatch"],
        ])
        self.write_csv("rag_similarity_scores.csv", ["invoice_id", "vendor_id", "contract_text", "similarity", "best_match_service", "best_match_score", "rag_status", "margin", "gap", "n_contracts", "service_source", "evidence"], [
            ["INV-1", "V-1", "Supply of laptop equipment under annual terms", "0.61", "network equipment", "0.88", "mismatch", "0.1", "0.27", "1", "parsed", "Stored invoice-contract comparison excerpt"],
        ])
        self.write_csv("audit_log.csv", ["time", "invoice_id", "vendor_id", "decision", "note"], [
            ["2026-01-03T12:00:00", "INV-1", "V-1", "Hold for more information", "Request delivery receipt"],
        ])
        self.create_evidence_db()
        self.service = AIRetrievalService(self.data, self.db)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_csv(self, filename: str, fields: list[str], rows: list[list[str]]) -> None:
        with (self.data / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            writer.writerows(rows)

    def create_evidence_db(self) -> None:
        with sqlite3.connect(self.db) as connection:
            connection.executescript("""
                CREATE TABLE investigations (
                    investigation_id TEXT PRIMARY KEY, vendor_id TEXT, invoice_id TEXT,
                    status TEXT, created_at TEXT, completed_at TEXT
                );
                CREATE TABLE evidence (
                    evidence_id TEXT PRIMARY KEY, investigation_id TEXT, check_type TEXT,
                    finding TEXT, matched_entity TEXT, verification_status TEXT,
                    source_type TEXT, created_at TEXT, source_url TEXT, retrieved_at TEXT
                );
            """)
            connection.execute("INSERT INTO investigations VALUES ('CASE-1','V-1','INV-1','completed','2026-01-04',NULL)")
            connection.execute("INSERT INTO evidence VALUES ('EVID-1','CASE-1','company_registration_research','Registry listing matches supplied CIN','{}','possible_match','web_search','2026-01-04','https://registry.example/company','2026-01-04T10:00:00Z')")

    def test_invoice_lookup_includes_vendor_po_and_provenance(self) -> None:
        result = self.service.retrieve("INV-1")
        records = {record["source_id"]: record for record in result["structured"]["records"]}
        self.assertIn("invoice:INV-1", records)
        self.assertIn("vendor:V-1", records)
        self.assertIn("purchase_order:PO-1", records)
        self.assertIn("employee:E-1", records)
        self.assertEqual(records["employee:E-1"]["provenance"]["relationship"]["relationship_type"], "submitted")
        self.assertEqual(records["invoice:INV-1"]["provenance"]["source_files"], ["invoices.csv"])

    def test_vendor_lookup_returns_history_and_contract_document(self) -> None:
        result = self.service.retrieve("V-1")
        records = result["structured"]["records"]
        self.assertIn("invoice:INV-1", {record["source_id"] for record in records})
        contract = next(record for record in records if record["source_id"] == "contract:C-1")
        self.assertEqual(contract["source_type"], "internal_document")
        self.assertIn("laptop equipment", contract["fields"]["contract_text"])

    def test_detector_signals_and_human_decision_are_distinct_records(self) -> None:
        records = self.service.retrieve("INV-1")["structured"]["records"]
        rule = next(record for record in records if record["record_type"] == "rule_signal")
        gnn = next(record for record in records if record["record_type"] == "gnn_result")
        audit = next(record for record in records if record["record_type"] == "audit_decision")
        self.assertEqual(rule["source_type"], "detector_signal")
        self.assertEqual(gnn["source_type"], "detector_signal")
        self.assertEqual(audit["source_type"], "human_audit_decision")

    def test_contract_text_can_be_found_by_content(self) -> None:
        result = self.service.retrieve("laptop equipment")
        self.assertIn("contract:C-1", {record["source_id"] for record in result["structured"]["records"]})

    def test_investigation_evidence_retains_url_status_and_read_only_provenance(self) -> None:
        result = self.service.retrieve("INV-1")
        evidence = result["documents"]["records"][0]
        self.assertEqual(evidence["source_id"], "evidence:EVID-1")
        self.assertEqual(evidence["fields"]["verification_status"], "possible_match")
        self.assertEqual(evidence["provenance"]["source_url"], "https://registry.example/company")
        self.assertEqual(evidence["provenance"]["retrieved_at"], "2026-01-04T10:00:00Z")
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM evidence").fetchone()[0], 1)

    def test_no_match_is_distinct_from_unavailable_sources(self) -> None:
        result = self.service.retrieve("missing entity")
        self.assertEqual(result["status"], "no_match")
        self.assertEqual(result["documents"]["status"], "no_match")
        missing_service = AIRetrievalService(self.data / "missing", self.data / "missing.sqlite3")
        unavailable = missing_service.retrieve("anything")
        self.assertEqual(unavailable["documents"]["status"], "unavailable")
        self.assertEqual(unavailable["status"], "unavailable")

    def test_missing_csv_columns_are_reported_without_fabricated_records(self) -> None:
        self.write_csv("vendors.csv", ["vendor_id"], [["V-1"]])
        result = self.service.retrieve("V-1")
        self.assertNotIn("vendor:V-1", {record["source_id"] for record in result["structured"]["records"]})
        self.assertFalse(result["structured"]["availability"]["vendor_records"]["available"])
        self.assertEqual(result["structured"]["availability"]["vendor_records"]["reason"], "vendor_data_unavailable")
        vendor_only = self.service.retrieve("", vendor_id="V-1")
        self.assertEqual(vendor_only["structured"]["status"], "unavailable")

    def test_source_ids_are_stable_across_retrievals(self) -> None:
        first = self.service.retrieve("INV-1")
        second = self.service.retrieve("INV-1")
        first_ids = [item["source_id"] for item in first["structured"]["records"]]
        second_ids = [item["source_id"] for item in second["structured"]["records"]]
        self.assertEqual(first_ids, second_ids)

    def test_exact_identifier_resolution_checks_actual_records(self) -> None:
        self.assertEqual(self.service.resolve_entity("invoice", "inv-1")["resolved_id"], "INV-1")
        self.assertEqual(self.service.resolve_entity("vendor", "V-1")["resolved_id"], "V-1")
        self.assertEqual(self.service.resolve_entity("purchase_order", "PO-1")["resolved_id"], "PO-1")
        self.assertEqual(self.service.resolve_entity("contract", "C-1")["resolved_id"], "C-1")
        missing = self.service.resolve_entity("invoice", "INV-999")
        self.assertTrue(missing["available"])
        self.assertFalse(missing["found"])
        self.assertEqual(missing["reason"], "record_not_found")

    def test_exact_purchase_order_retrieval_is_scoped_to_its_connections(self) -> None:
        result = self.service.retrieve(
            "Who is connected to PO-1?", entity_type="purchase_order",
            entity_id="PO-1", intent="purchase_order", limit=8,
        )
        records = {item["source_id"]: item for item in result["structured"]["records"]}
        self.assertIn("purchase_order:PO-1", records)
        self.assertIn("vendor:V-1", records)
        self.assertIn("invoice:INV-1", records)
        self.assertLessEqual(len(result["structured"]["records"]), 8)

    def test_intent_scoped_vendor_query_omits_unrelated_invoice_family_search(self) -> None:
        result = self.service.structured.retrieve("Northwind Supply", intent="vendor", limit=8)
        self.assertIn("vendor:V-1", {item["source_id"] for item in result["records"]})
        self.assertLessEqual(len(result["records"]), 8)

    def test_chat_routes_existing_invoice_vendor_and_po_ids_to_relevant_records(self) -> None:
        chat = AIChatService(self.service, entity_resolver=self.service.resolve_entity)
        invoice = chat.respond({"message": "Why was invoice INV-1 flagged?"})
        self.assertEqual(invoice["retrieval_status"], "matched")
        self.assertIn("invoice:INV-1", {source["source_id"] for source in invoice["sources"]})
        self.assertTrue(all(citation["source_id"] in {source["source_id"] for source in invoice["sources"]}
                            for citation in invoice["citations"]))

        vendor = chat.respond({"message": "Show vendor V-1"})
        vendor_ids = {source["source_id"] for source in vendor["sources"]}
        self.assertIn("vendor:V-1", vendor_ids)
        self.assertIn("invoice:INV-1", vendor_ids)

        purchase_order = chat.respond({"message": "Show purchase order PO-1"})
        po_ids = {source["source_id"] for source in purchase_order["sources"]}
        self.assertIn("purchase_order:PO-1", po_ids)
        self.assertIn("vendor:V-1", po_ids)


if __name__ == "__main__":
    unittest.main()
