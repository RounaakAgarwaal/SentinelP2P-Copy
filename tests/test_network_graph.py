"""Graph construction tests use isolated CSV fixtures; no project data is changed."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.repositories.network import NetworkRepository  # noqa: E402


class NetworkGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.write("employees.csv", ["employee_id", "name", "email", "phone"], [
            ["E1", "Alex Employee", "alex@example.test", "1112223333"],
            ["E2", "Sam Employee", "sam@example.test", "2223334444"],
        ])
        self.write("vendors.csv", ["vendor_id", "vendor_name", "email", "phone", "address", "bank_account", "registration_number", "created_by_employee_id"], [
            ["V1", "Northwind", "north@example.test", "555-123-4567", "1 Main", "123456789000", "REG-1", "E1"],
            ["V2", "Contoso", "contoso@example.test", "5551234567", "2 Main", "123456789000", "REG-2", "E2"],
            ["V3", "No Links", "", "", "", "", "", "missing-employee"],
        ])
        self.write("purchase_orders.csv", ["po_id", "vendor_id", "amount", "date", "created_by_employee_id", "approved_by_employee_id"], [
            ["PO1", "V1", "90", "2026-01-01", "E1", "E2"],
            ["PO2", "missing-vendor", "12", "2026-01-02", "E1", ""],
        ])
        self.write("invoices.csv", ["invoice_id", "po_id", "amount", "submitted_by_employee_id"], [
            ["I1", "PO1", "40", "E2"],
            ["I2", "PO1", "50", "E2"],
            ["I3", "missing-po", "30", "missing-employee"],
        ])
        self.write("contracts.csv", ["contract_id", "vendor_id", "agreed_rate"], [["C1", "V1", "50"]])
        self.repository = NetworkRepository(self.data)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, filename: str, columns: list[str], rows: list[list[str]]) -> None:
        with (self.data / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            writer.writerows(rows)

    def test_only_explicit_id_relationships_are_created(self) -> None:
        graph = self.repository.graph()
        actual = {(edge["source"], edge["relationship_type"], edge["target"]) for edge in graph["edges"]}
        expected = {
            ("employee:E1", "created", "vendor:V1"),
            ("employee:E2", "created", "vendor:V2"),
            ("employee:E1", "raised", "purchase_order:PO1"),
            ("employee:E2", "approved", "purchase_order:PO1"),
            ("employee:E1", "raised", "purchase_order:PO2"),
            ("vendor:V1", "received", "purchase_order:PO1"),
            ("purchase_order:PO1", "has_invoice", "invoice:I1"),
            ("purchase_order:PO1", "has_invoice", "invoice:I2"),
            ("employee:E2", "submitted", "invoice:I1"),
            ("employee:E2", "submitted", "invoice:I2"),
            ("vendor:V1", "has_contract", "contract:C1"),
            ("vendor:V1", "shared_phone", "vendor:V2"),
            ("vendor:V1", "shared_bank_account", "vendor:V2"),
        }
        self.assertEqual(actual, expected)

    def test_unresolved_references_and_blank_values_do_not_create_edges(self) -> None:
        graph = self.repository.graph()
        identifiers = {node["id"] for node in graph["nodes"]}
        self.assertIn("vendor:V3", identifiers)
        self.assertFalse(any("missing" in edge["source"] or "missing" in edge["target"] for edge in graph["edges"]))
        self.assertFalse(any(edge["source"] == "vendor:V3" or edge["target"] == "vendor:V3" for edge in graph["edges"]))

    def test_duplicate_primary_ids_make_ambiguous_relationships_unavailable(self) -> None:
        self.write("invoices.csv", ["invoice_id", "po_id", "amount", "submitted_by_employee_id"], [
            ["I1", "PO1", "40", "E2"], ["I1", "PO1", "99", "E1"],
        ])
        graph = self.repository.graph()
        self.assertFalse(any(edge["target"] == "invoice:I1" for edge in graph["edges"]))
        self.assertTrue(any(edge["relationship_type"] == "received" for edge in graph["edges"]))

    def test_duplicate_source_rows_do_not_duplicate_edges(self) -> None:
        self.write("purchase_orders.csv", ["po_id", "vendor_id", "amount", "date", "created_by_employee_id", "approved_by_employee_id"], [
            ["PO1", "V1", "90", "2026-01-01", "E1", "E2"],
            ["PO1", "V1", "90", "2026-01-01", "E1", "E2"],
        ])
        graph = self.repository.graph()
        edge_ids = [edge["id"] for edge in graph["edges"]]
        self.assertEqual(len(edge_ids), len(set(edge_ids)))
        self.assertFalse(any("purchase_order:PO1" in edge_id for edge_id in edge_ids))

    def test_bank_values_are_masked_on_nodes_and_shared_relationships(self) -> None:
        graph = self.repository.graph()
        vendor = next(node for node in graph["nodes"] if node["id"] == "vendor:V1")
        self.assertEqual(vendor["properties"]["bank_account"], "••••9000")
        link = next(edge for edge in graph["edges"] if edge["relationship_type"] == "shared_bank_account")
        self.assertEqual(link["details"]["matched_field"], "bank_account")
        self.assertEqual(link["details"]["matched_value"], "••••9000")
        self.assertNotIn("123456789000", str(graph))

    def test_email_matching_preserves_significant_punctuation(self) -> None:
        self.write("vendors.csv", ["vendor_id", "vendor_name", "email", "phone", "address", "bank_account", "registration_number", "created_by_employee_id"], [
            ["V1", "Northwind", "a.b@example.test", "", "", "", "", ""],
            ["V2", "Contoso", "ab@example.test", "", "", "", "", ""],
        ])
        graph = self.repository.graph()
        self.assertFalse(any(edge["relationship_type"] == "shared_email" for edge in graph["edges"]))
        self.write("vendors.csv", ["vendor_id", "vendor_name", "email", "phone", "address", "bank_account", "registration_number", "created_by_employee_id"], [
            ["V1", "Northwind", "a.b@example.test", "", "", "", "", ""],
            ["V2", "Contoso", "A.B@EXAMPLE.TEST", "", "", "", "", ""],
        ])
        graph = self.repository.graph()
        self.assertEqual(sum(edge["relationship_type"] == "shared_email" for edge in graph["edges"]), 1)

    def test_search_and_type_relationship_filters_return_related_graph(self) -> None:
        graph = self.repository.graph(query="northwind")
        node_ids = {node["id"] for node in graph["nodes"]}
        self.assertIn("vendor:V1", node_ids)
        self.assertIn("purchase_order:PO1", node_ids)
        self.assertTrue(all(edge["source"] in node_ids and edge["target"] in node_ids for edge in graph["edges"]))
        filtered = self.repository.graph(entity_types=["vendor"], relationship_types=["shared_phone"])
        self.assertTrue(all(node["entity_type"] == "vendor" for node in filtered["nodes"]))
        self.assertTrue(all(edge["relationship_type"] == "shared_phone" for edge in filtered["edges"]))
        filtered_ids = {node["id"] for node in filtered["nodes"]}
        self.assertTrue(all(edge["source"] in filtered_ids and edge["target"] in filtered_ids for edge in filtered["edges"]))
        empty = self.repository.graph(query="no such record")
        self.assertEqual(empty["nodes"], [])
        self.assertEqual(empty["edges"], [])

    def test_overview_slice_keeps_neighbor_nodes_and_their_edges(self) -> None:
        graph = self.repository.graph(overview=True)
        node_ids = {node["id"] for node in graph["nodes"]}
        self.assertTrue(graph["edges"])
        self.assertLessEqual(len(graph["nodes"]), 70)
        self.assertIn("invoice", {node["entity_type"] for node in graph["nodes"]})
        self.assertTrue(all(edge["source"] in node_ids and edge["target"] in node_ids for edge in graph["edges"]))

    def test_detail_includes_only_direct_connections_and_relationship_metadata(self) -> None:
        detail = self.repository.node_detail("vendor", "V1")
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertGreater(detail["connection_count"], 0)
        self.assertTrue(all("relationship_type" in item["relationship"] for item in detail["connections"]))
        self.assertIsNone(self.repository.node_detail("vendor", "unknown"))

    def test_missing_dataset_is_reported_as_unavailable(self) -> None:
        (self.data / "contracts.csv").unlink()
        graph = self.repository.graph()
        self.assertFalse(graph["sources"]["contract"]["available"])
        self.assertEqual(graph["sources"]["contract"]["reason"], "file_missing")
        self.assertFalse(any(node["entity_type"] == "contract" for node in graph["nodes"]))


if __name__ == "__main__":
    unittest.main()
