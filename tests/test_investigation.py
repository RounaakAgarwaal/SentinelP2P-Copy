from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.investigation.checks import (
    check_bank_account_matches,
    check_email_matches,
    check_phone_matches,
    check_registration_number_matches,
    run_internal_vendor_checks,
)
from src.investigation.inputs import build_investigation_input
from src.investigation.service import start_investigation
from src.investigation.storage import (
    create_evidence,
    create_investigation,
    delete_evidence,
    delete_investigation,
    get_evidence,
    get_investigation,
    list_evidence,
    list_investigations,
    update_investigation,
)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class InvestigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.db = self.root / "investigations.sqlite3"
        self.write_fixture(duplicates=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_fixture(self, *, duplicates: bool, missing_values: bool = False) -> None:
        vendor1 = {
            "vendor_id": "VEN001", "vendor_name": "Alpha Supplies", "email": "Vendor@Example.com",
            "phone": "+1 (555) 111-2222", "address": "1 Sample Road", "bank_account": "1234 5678-9012",
            "registration_number": "REG-00123", "vendor_category": "Office Supplies",
            "onboarding_date": "2024-01-01", "has_contract": "No", "created_by_employee_id": "EMP001",
        }
        vendor2 = {
            "vendor_id": "VEN002", "vendor_name": "Beta Supplies",
            "email": "vendor@example.com" if duplicates else "beta@example.com",
            "phone": "15551112222" if duplicates else "+1 555 333 4444",
            "address": "2 Sample Road", "bank_account": "123456789012" if duplicates else "999988887777",
            "registration_number": "reg 00123" if duplicates else "REG-99999",
            "vendor_category": "Office Supplies", "onboarding_date": "2024-02-01",
            "has_contract": "No", "created_by_employee_id": "EMP002",
        }
        employees = [
            {"employee_id": "EMP001", "name": "A Person", "email": "employee@example.com",
             "phone": "+1 555 111 2222" if duplicates else "5550000000", "department": "Procurement",
             "role": "Officer", "join_date": "2022-01-01"},
            {"employee_id": "EMP002", "name": "B Person", "email": "other@example.com",
             "phone": "5554445555", "department": "Finance", "role": "Officer", "join_date": "2022-01-01"},
        ]
        if missing_values:
            for vendor in (vendor1, vendor2):
                vendor["phone"] = ""
                vendor["email"] = "N/A"
                vendor["bank_account"] = ""
                vendor["registration_number"] = "PENDING"
            for employee in employees:
                employee["phone"] = ""
                employee["email"] = ""
        write_csv(self.data / "vendors.csv", [vendor1, vendor2])
        write_csv(self.data / "employees.csv", employees)
        write_csv(self.data / "purchase_orders.csv", [
            {"po_id": "PO001", "vendor_id": "VEN001", "amount": "100", "item_category": "Office Supplies",
             "date": "2024-04-01", "created_by_employee_id": "EMP001", "approved_by_employee_id": "EMP002",
             "payment_terms": "Net 30"},
            {"po_id": "PO002", "vendor_id": "VEN002", "amount": "200", "item_category": "Office Supplies",
             "date": "2024-04-02", "created_by_employee_id": "EMP002", "approved_by_employee_id": "EMP001",
             "payment_terms": "Net 30"},
        ])
        write_csv(self.data / "invoices.csv", [
            {"invoice_id": "INV001", "po_id": "PO001", "amount": "100", "item_category": "Office Supplies",
             "description": "stationery", "date": "2024-04-03", "payment_status": "Paid",
             "submitted_by_employee_id": "EMP001"},
        ])
        write_csv(self.data / "rule_flags_pandas.csv", [{
            "invoice_id": "INV001", "rule_shell_vendor": "False", "rule_split_po": "False",
        }])
        write_csv(self.data / "gnn_scores.csv", [{
            "invoice_id": "INV001", "gnn_risk_score": "0.73", "gnn_prediction": "1",
        }])
        write_csv(self.data / "rag_similarity_scores.csv", [{
            "invoice_id": "INV001", "vendor_id": "VEN001", "rag_status": "mismatch",
            "evidence": "Scope does not match", "best_match_service": "logistics", "similarity": "0.4",
        }])

    def test_duplicate_phone_matches_employee_and_other_vendor(self) -> None:
        findings = check_phone_matches("VEN001", self.data)
        matched = {item["matched_entity"]["entity_id"] for item in findings if item["matched_entity"]}
        self.assertEqual(matched, {"EMP001", "VEN002"})
        self.assertTrue(all(item["verification_status"] == "match_found" for item in findings))

    def test_duplicate_email_matches_employee_and_other_vendor(self) -> None:
        findings = check_email_matches("VEN001", self.data)
        matched = {item["matched_entity"]["entity_id"] for item in findings if item["matched_entity"]}
        self.assertEqual(matched, {"VEN002"})

    def test_duplicate_bank_account_is_normalized_and_masked(self) -> None:
        findings = check_bank_account_matches("VEN001", self.data)
        match = next(item for item in findings if item["matched_entity"])
        self.assertEqual(match["matched_entity"]["entity_id"], "VEN002")
        self.assertEqual(match["matched_entity"]["matched_value"], "****9012")
        self.assertNotIn("123456789012", json.dumps(findings))

    def test_duplicate_registration_number_is_normalized(self) -> None:
        findings = check_registration_number_matches("VEN001", self.data)
        match = next(item for item in findings if item["matched_entity"])
        self.assertEqual(match["matched_entity"]["entity_id"], "VEN002")

    def test_no_matching_records_returns_explicit_no_match(self) -> None:
        self.write_fixture(duplicates=False)
        findings = run_internal_vendor_checks("VEN001", self.data)
        self.assertEqual(len(findings), 4)
        self.assertTrue(all(item["verification_status"] == "no_match" for item in findings))
        self.assertTrue(all(item["matched_entity"] is None for item in findings))

    def test_missing_values_are_not_compared(self) -> None:
        self.write_fixture(duplicates=True, missing_values=True)
        findings = run_internal_vendor_checks("VEN001", self.data)
        self.assertTrue(all(item["verification_status"] == "not_run_missing_value" for item in findings))

    def test_invalid_vendor_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown vendor_id"):
            run_internal_vendor_checks("VEN999", self.data)
        with self.assertRaisesRegex(ValueError, "Unknown vendor_id"):
            build_investigation_input("VEN999", self.data)

    def test_investigation_and_evidence_crud_persist_across_connections(self) -> None:
        investigation = create_investigation(self.db, "VEN001", invoice_id="INV001")
        self.assertEqual(get_investigation(self.db, investigation["investigation_id"]), investigation)
        evidence = create_evidence(
            self.db,
            investigation_id=investigation["investigation_id"],
            check_type="phone_match",
            finding="Vendor phone matches employee record.",
            matched_entity={"entity_type": "employee", "entity_id": "EMP001"},
            verification_status="match_found",
            source_type="internal_records",
        )
        self.assertEqual(get_evidence(self.db, evidence["evidence_id"]), evidence)
        self.assertEqual(list_evidence(self.db, investigation["investigation_id"]), [evidence])
        self.assertEqual(len(list_investigations(self.db, "VEN001")), 1)
        updated = update_investigation(self.db, investigation["investigation_id"], status="completed")
        self.assertEqual(updated["status"], "completed")
        self.assertIsNotNone(updated["completed_at"])
        self.assertTrue(delete_evidence(self.db, evidence["evidence_id"]))
        self.assertTrue(delete_investigation(self.db, investigation["investigation_id"]))
        self.assertEqual(list_evidence(self.db, investigation["investigation_id"]), [])

    def test_input_contains_existing_detector_outputs_and_masks_account(self) -> None:
        payload = build_investigation_input("VEN001", self.data)
        self.assertEqual(payload["vendor_details"]["bank_account"], "****9012")
        self.assertEqual(len(payload["related_invoices"]), 1)
        item = payload["related_invoices"][0]
        self.assertEqual(item["invoice"]["invoice_id"], "INV001")
        self.assertEqual(item["rule_flags"]["rule_shell_vendor"], False)
        self.assertEqual(item["gnn"], {"risk_score": "0.73", "prediction": True})
        self.assertEqual(item["contract_rag"]["rag_status"], "mismatch")
        self.assertNotIn("123456789012", json.dumps(payload))

    def test_missing_optional_detector_files_are_reported(self) -> None:
        (self.data / "rule_flags_pandas.csv").unlink()
        (self.data / "gnn_scores.csv").unlink()
        (self.data / "rag_similarity_scores.csv").unlink()
        payload = build_investigation_input("VEN001", self.data)
        item = payload["related_invoices"][0]
        self.assertIsNone(item["rule_flags"])
        self.assertIsNone(item["gnn"])
        self.assertIsNone(item["contract_rag"])
        self.assertFalse(payload["data_availability"]["gnn_scores"]["available"])
        self.assertTrue(payload["warnings"])

    def test_start_investigation_persists_internal_findings(self) -> None:
        payload = start_investigation("VEN001", self.data, self.db, invoice_id="INV001")
        self.assertEqual(payload["investigation"]["invoice_id"], "INV001")
        stored = list_evidence(self.db, payload["investigation_id"])
        self.assertEqual(len(stored), 5)  # phone appears on both an employee and a second vendor
        self.assertTrue(all(item["source_type"] == "internal_records" for item in stored))


if __name__ == "__main__":
    unittest.main()
