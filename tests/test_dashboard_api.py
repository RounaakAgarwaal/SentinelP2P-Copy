"""Isolated tests for the read-only dashboard aggregation layer."""

from __future__ import annotations

import csv
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.repositories.dashboard import DashboardRepository  # noqa: E402
from app.services.dashboard import DashboardService  # noqa: E402


class DashboardServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name) / "data"
        self.data_dir.mkdir()
        self.db_path = self.data_dir / "investigations.sqlite3"
        self._write_csv("dashboard_data.csv", [
            "invoice_id", "po_id", "amount", "date", "overall_status", "rule_shell_vendor",
            "rule_split_po", "gnn_risk_score", "gnn_prediction", "rag_status",
        ], [
            ["INV-1", "PO-1", "250.5", "2026-01-01", "Flagged", "1", "0", "0.91", "1", "mismatch"],
            ["INV-2", "PO-2", "100", "2026-01-02", "Clear", "0", "0", "0.22", "0", "ok"],
            ["INV-3", "PO-1", "80", "2026-01-03", "Flagged", "0", "1", "0.71", "0", "no_contract_on_file"],
        ])
        self._write_csv("vendors.csv", ["vendor_id", "vendor_name"], [["V-1", "Example Vendor"], ["V-2", "Second Vendor"]])
        self._write_csv("purchase_orders.csv", ["po_id", "vendor_id"], [["PO-1", "V-1"], ["PO-2", "V-2"]])
        self._write_csv("audit_log.csv", ["time", "invoice_id", "vendor_id", "decision", "note"], [["2026-01-04", "INV-1", "V-1", "Hold", "Review"]])
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("""CREATE TABLE investigations (
                investigation_id TEXT, vendor_id TEXT, invoice_id TEXT, status TEXT,
                created_at TEXT, completed_at TEXT
            )""")
            connection.execute("INSERT INTO investigations VALUES (?, ?, ?, ?, ?, ?)",
                               ("CASE-1", "V-1", "INV-1", "completed", "2026-01-05", "2026-01-05"))
        self.service = DashboardService(DashboardRepository(self.data_dir, self.db_path))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_csv(self, filename: str, headers: list[str], rows: list[list[str]]) -> None:
        with (self.data_dir / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)

    def test_summary_uses_actual_fields_and_never_infers_pending_reviews(self) -> None:
        response = self.service.summary()
        metrics = response["metrics"]
        self.assertEqual(metrics["total_invoices"]["value"], 3)
        self.assertEqual(metrics["flagged_invoices"]["value"], 2)
        self.assertEqual(metrics["total_vendors"]["value"], 2)
        self.assertFalse(metrics["pending_audit_reviews"]["available"])
        self.assertIsNone(metrics["pending_audit_reviews"]["value"])
        self.assertEqual(metrics["audited_invoices"]["value"], 1)

    def test_risk_distribution_is_empirical_gnn_quartiles(self) -> None:
        result = self.service.risk_distribution()
        self.assertEqual(result["kind"], "gnn_score_quartiles")
        self.assertEqual(sum(item["invoice_count"] for item in result["bins"]), 3)
        self.assertIn("not model-defined", result["note"])

    def test_detection_channels_remain_separate(self) -> None:
        result = self.service.detection_overview()
        self.assertEqual(result["rules"]["invoice_count"], 2)
        self.assertEqual(result["gnn"]["invoice_count"], 1)
        self.assertEqual(result["rag"]["invoice_count"], 1)
        self.assertEqual(result["rag_status_counts"]["no_contract_on_file"], 1)

    def test_recent_invoices_expose_signals_and_saved_human_decision_separately(self) -> None:
        result = self.service.recent_invoices(limit=1)
        self.assertEqual(len(result["items"]), 1)
        invoice = result["items"][0]
        self.assertEqual(invoice["invoice_id"], "INV-3")
        self.assertEqual(invoice["vendor_name"], "Example Vendor")
        self.assertEqual(invoice["review_status"], "no_decision_recorded")
        self.assertIsNone(invoice["human_decision"])
        self.assertIn("not confirmed fraud", result["note"])

    def test_vendor_ranking_uses_observed_max_score_not_a_threshold(self) -> None:
        result = self.service.high_risk_vendors()
        self.assertEqual(result["items"][0]["vendor_id"], "V-1")
        self.assertEqual(result["items"][0]["related_invoice_count"], 2)
        self.assertEqual(result["items"][0]["flagged_invoice_count"], 2)
        self.assertEqual(result["items"][0]["investigation_status"], "completed")
        self.assertIn("not a risk classification", result["note"])

    def test_missing_sources_are_reported_unavailable(self) -> None:
        empty = DashboardService(DashboardRepository(self.data_dir / "absent", self.data_dir / "missing.sqlite3"))
        summary = empty.summary()
        self.assertFalse(summary["metrics"]["total_invoices"]["available"])
        self.assertFalse(summary["metrics"]["pending_audit_reviews"]["available"])
        self.assertFalse(empty.recent_invoices()["available"])
        self.assertFalse(empty.high_risk_vendors()["available"])
        activity = empty.recent_investigations()
        self.assertFalse(activity["investigations_available"])
        self.assertFalse(activity["decisions_available"])


@unittest.skipUnless(importlib.util.find_spec("fastapi") and importlib.util.find_spec("pydantic"),
                     "FastAPI/Pydantic are not installed in this Python environment")
class DashboardSchemaTests(unittest.TestCase):
    def test_response_schemas_accept_service_shape_and_unavailable_values(self) -> None:
        from app.schemas.dashboard import DashboardSummaryResponse, RecentInvoicesResponse

        data_dir = ROOT / "data"
        repo = DashboardRepository(data_dir, data_dir / "missing-test-db.sqlite3")
        service = DashboardService(repo)
        summary = DashboardSummaryResponse.parse_obj(service.summary())
        invoices = RecentInvoicesResponse.parse_obj(service.recent_invoices())
        self.assertIsNone(summary.metrics.pending_audit_reviews.value)
        self.assertTrue(invoices.available)


if __name__ == "__main__":
    unittest.main()
