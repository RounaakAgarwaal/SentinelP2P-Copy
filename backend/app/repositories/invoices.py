"""Read-only access to invoice, vendor, PO, contract, detector and audit artifacts."""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.repositories.dashboard import CsvTable, DashboardRepository


RULE_LABELS = {
    "rule_shell_vendor": "Shell vendor",
    "rule_split_po": "Split purchase orders",
    "rule_duplicate_invoice": "Duplicate invoice",
    "rule_same_creator_approver": "Same PO creator and approver",
    "rule_new_vendor_high_value": "New vendor, high-value PO",
    "rule_contract_rate_mismatch": "Contract rate mismatch",
    "rule_vendor_employee_email": "Vendor and employee email match",
    "rule_category_mismatch": "Invoice and PO category mismatch",
}

RULE_EXPLANATIONS = {
    "rule_shell_vendor": "The vendor phone matches the phone of the employee recorded as its creator.",
    "rule_split_po": "Two purchase orders for the same vendor on the same date are each at or below the configured approval limit (15,000) and together exceed it.",
    "rule_duplicate_invoice": "A later invoice on the same purchase order has the same amount as an earlier invoice.",
    "rule_same_creator_approver": "The same employee is recorded as both creator and approver of the purchase order.",
    "rule_new_vendor_high_value": "The purchase order exceeds the configured approval limit (15,000) and falls within seven days after vendor onboarding.",
    "rule_contract_rate_mismatch": "The invoice amount exceeds 1.3 times the vendor's agreed contract rate.",
    "rule_vendor_employee_email": "The vendor email matches an employee email, ignoring letter case.",
    "rule_category_mismatch": "The invoice item category differs from the purchase order item category.",
}


def _bool(value: Any) -> bool | None:
    if value is None or str(value).strip().lower() in {"", "nan", "none", "null"}:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _number(value: Any) -> float | None:
    if value is None or str(value).strip().lower() in {"", "nan", "none", "null"}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _text(value: Any) -> str | None:
    if value is None or str(value).strip().lower() in {"", "nan", "none", "null"}:
        return None
    return str(value).strip()


class InvoiceRepository:
    """Joins existing artifacts in memory and opens SQLite strictly read-only."""

    def __init__(self, data_dir: str | Path, investigation_db: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.investigation_db = Path(investigation_db)
        self.csv = DashboardRepository(self.data_dir, self.investigation_db)

    def _tables(self) -> dict[str, CsvTable]:
        return {
            "dashboard": self.csv.csv_table("dashboard_data.csv", required_columns={"invoice_id"}),
            "invoices": self.csv.csv_table("invoices.csv", required_columns={"invoice_id"}),
            "vendors": self.csv.vendors_table(),
            "employees": self.csv.csv_table("employees.csv", required_columns={"employee_id"}),
            "purchase_orders": self.csv.purchase_orders_table(),
            "contracts": self.csv.csv_table("contracts.csv", required_columns={"vendor_id"}),
            "rag": self.csv.csv_table("rag_similarity_scores.csv", required_columns={"invoice_id"}),
            "audit": self.csv.audit_log_table(),
        }

    @staticmethod
    def _index(table: CsvTable, key: str) -> dict[str, dict[str, str | None]]:
        if not table.available:
            return {}
        return {str(row.get(key) or "").strip(): row for row in table.rows if str(row.get(key) or "").strip()}

    @staticmethod
    def _po_vendor_index(table: CsvTable) -> tuple[dict[str, str], set[str]]:
        mapping: dict[str, str] = {}
        conflicts: set[str] = set()
        if table.available:
            for row in table.rows:
                po_id, vendor_id = _text(row.get("po_id")), _text(row.get("vendor_id"))
                if not po_id or not vendor_id:
                    continue
                if po_id in mapping and mapping[po_id] != vendor_id:
                    conflicts.add(po_id)
                else:
                    mapping[po_id] = vendor_id
        for po_id in conflicts:
            mapping.pop(po_id, None)
        return mapping, conflicts

    @staticmethod
    def _vendor_view(row: dict[str, str | None] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        safe = dict(row)
        account = _text(safe.get("bank_account"))
        if account:
            normalized = "".join(char for char in account if char.isalnum())
            safe["bank_account"] = f"****{normalized[-4:]}" if normalized else "****"
        return safe

    @staticmethod
    def _availability(tables: dict[str, CsvTable]) -> dict[str, Any]:
        return {
            name: {
                "available": table.available,
                "reason": table.reason,
                "missing_columns": list(table.missing_columns),
                "row_count": len(table.rows) if table.available else None,
            }
            for name, table in tables.items()
        }

    @staticmethod
    def _signal_names(row: dict[str, str | None], columns: tuple[str, ...]) -> list[str]:
        signals = [RULE_LABELS.get(column, column) for column in columns if column.startswith("rule_") and _bool(row.get(column)) is True]
        if _bool(row.get("gnn_prediction")) is True:
            signals.append("GNN prediction")
        if _text(row.get("rag_status")) == "mismatch":
            signals.append("Contract RAG mismatch")
        return signals

    def list_invoices(
        self, *, query: str = "", status: str = "all", vendor_filter: str = "", signal: str = "",
        sort_by: str = "date", sort_dir: str = "desc", limit: int = 25, offset: int = 0,
    ) -> dict[str, Any]:
        tables = self._tables()
        dashboard = tables["dashboard"]
        if not dashboard.available:
            return {"available": False, "items": [], "total": None, "limit": limit, "offset": offset,
                    "available_signals": [], "available_vendors": [], "sources": self._availability(tables),
                    "reason": "dashboard_data_unavailable"}
        vendors = self._index(tables["vendors"], "vendor_id")
        po_to_vendor, _ = self._po_vendor_index(tables["purchase_orders"])
        audit_by_invoice: dict[str, list[dict[str, str | None]]] = {}
        if tables["audit"].available:
            for audit_row in tables["audit"].rows:
                invoice_id = _text(audit_row.get("invoice_id"))
                if invoice_id and _text(audit_row.get("decision")):
                    audit_by_invoice.setdefault(invoice_id, []).append(audit_row)

        rule_columns = [column for column in dashboard.columns if column.startswith("rule_")]
        available_signals = [RULE_LABELS.get(column, column) for column in rule_columns]
        if "gnn_prediction" in dashboard.columns:
            available_signals.append("GNN prediction")
        if "rag_status" in dashboard.columns:
            available_signals.append("Contract RAG mismatch")
        assembled: list[dict[str, Any]] = []
        vendor_options: set[tuple[str, str | None]] = set()
        needle = query.strip().casefold()
        for row in dashboard.rows:
            invoice_id = _text(row.get("invoice_id")) or ""
            vendor_id = po_to_vendor.get(_text(row.get("po_id")) or "")
            vendor = vendors.get(vendor_id or "")
            vendor_name = _text(vendor.get("vendor_name")) if vendor else None
            if vendor_id:
                vendor_options.add((vendor_id, vendor_name))
            signals = self._signal_names(row, dashboard.columns)
            overall_status = _text(row.get("overall_status"))
            if status != "all" and overall_status != ("Flagged" if status == "flagged" else "Clear"):
                continue
            if vendor_filter and vendor_filter != vendor_id:
                continue
            if needle and needle not in invoice_id.casefold() and needle not in (vendor_name or "").casefold() and needle not in (vendor_id or "").casefold():
                continue
            if signal and signal not in signals:
                continue
            decisions = audit_by_invoice.get(invoice_id, [])
            decisions.sort(key=lambda item: str(item.get("time") or ""))
            assembled.append({
                "invoice_id": invoice_id,
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "amount": _number(row.get("amount")),
                "date": _text(row.get("date")),
                "overall_status": overall_status,
                "risk_score": _number(row.get("gnn_risk_score")),
                "gnn_prediction": _bool(row.get("gnn_prediction")),
                "signals": signals,
                "human_decision": decisions[-1].get("decision") if decisions else None,
                "human_decision_time": decisions[-1].get("time") if decisions else None,
                "human_decision_status": "unavailable" if not tables["audit"].available else "decision_recorded" if decisions else "no_decision_recorded",
            })

        sort_keys = {
            "invoice_id": lambda item: item["invoice_id"],
            "vendor_name": lambda item: (item["vendor_name"] or "").casefold(),
            "amount": lambda item: item["amount"] if item["amount"] is not None else float("-inf"),
            "date": lambda item: item["date"] or "",
            "risk_score": lambda item: item["risk_score"] if item["risk_score"] is not None else float("-inf"),
            "overall_status": lambda item: item["overall_status"] or "",
        }
        assembled.sort(key=sort_keys.get(sort_by, sort_keys["date"]), reverse=sort_dir == "desc")
        total = len(assembled)
        return {
            "available": True, "items": assembled[offset:offset + limit], "total": total,
            "limit": limit, "offset": offset, "available_signals": available_signals,
            "available_vendors": [{"vendor_id": key, "vendor_name": value} for key, value in sorted(vendor_options)],
            "sources": self._availability(tables), "reason": None,
        }

    def invoice_detail(self, invoice_id: str) -> dict[str, Any] | None:
        tables = self._tables()
        dashboard = self._index(tables["dashboard"], "invoice_id")
        base_invoices = self._index(tables["invoices"], "invoice_id")
        row = dashboard.get(invoice_id)
        if row is None:
            row = base_invoices.get(invoice_id)
        if row is None:
            return None
        dashboard_row = dashboard.get(invoice_id, {})
        base_row = base_invoices.get(invoice_id, {})
        invoice = dict(base_row or dashboard_row)
        po_id = _text(invoice.get("po_id"))
        po_rows = [item for item in tables["purchase_orders"].rows if _text(item.get("po_id")) == po_id] if tables["purchase_orders"].available else []
        vendor_ids = {_text(item.get("vendor_id")) for item in po_rows if _text(item.get("vendor_id"))}
        vendor_conflict = len(vendor_ids) > 1
        vendor_id = next(iter(vendor_ids)) if len(vendor_ids) == 1 else None
        vendor_index = self._index(tables["vendors"], "vendor_id")
        vendor = vendor_index.get(vendor_id or "")
        contracts = [dict(item) for item in tables["contracts"].rows if _text(item.get("vendor_id")) == vendor_id] if tables["contracts"].available and vendor_id else []
        rag_index = self._index(tables["rag"], "invoice_id")
        rag = rag_index.get(invoice_id)
        audit_decisions = [
            {"time": _text(item.get("time")), "decision": _text(item.get("decision")), "vendor_id": _text(item.get("vendor_id")), "note": _text(item.get("note"))}
            for item in tables["audit"].rows
            if tables["audit"].available and _text(item.get("invoice_id")) == invoice_id and _text(item.get("decision"))
        ] if tables["audit"].available else []
        audit_decisions.sort(key=lambda item: item["time"] or "", reverse=True)
        rules = []
        for column in tables["dashboard"].columns:
            if column.startswith("rule_") and _bool(dashboard_row.get(column)) is True:
                rules.append({
                    "rule": column,
                    "label": RULE_LABELS.get(column, column),
                    "explanation": RULE_EXPLANATIONS.get(column, "This rule flag is present in the prepared dashboard data."),
                    "source": "src/utils/rules_pandas.py",
                })
        if "overall_status" in dashboard_row:
            overall_status = _text(dashboard_row.get("overall_status"))
        else:
            overall_status = None
        rag_view = None
        if rag is not None:
            rag_view = {
                key: _text(rag.get(key)) if key in {"rag_status", "best_match_service", "service_source", "evidence", "contract_text"} else _number(rag.get(key))
                for key in ("similarity", "best_match_score", "rag_status", "best_match_service", "service_source", "evidence", "contract_text", "margin", "gap", "n_contracts")
                if key in tables["rag"].columns
            }
        return {
            "invoice_id": invoice_id,
            "invoice": invoice,
            "overall_status": overall_status,
            "vendor_id": vendor_id,
            "vendor_mapping_conflict": vendor_conflict,
            "vendor": self._vendor_view(vendor),
            "purchase_orders": [dict(item) for item in po_rows],
            "contracts": contracts,
            "detection": {
                "rules": rules,
                "gnn": {"risk_score": _number(dashboard_row.get("gnn_risk_score")), "prediction": _bool(dashboard_row.get("gnn_prediction"))},
                "rag": rag_view,
            },
            "human_decisions": audit_decisions,
            "sources": self._availability(tables),
        }

    def investigations_for_invoice(self, vendor_id: str, invoice_id: str) -> dict[str, Any]:
        if not self.investigation_db.is_file():
            return {"available": False, "investigations": [], "reason": "database_missing"}
        uri = f"file:{quote(str(self.investigation_db.resolve()))}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=2.0) as connection:
                connection.row_factory = sqlite3.Row
                existing = {row[1] for row in connection.execute("PRAGMA table_info(investigations)")}
                if not {"investigation_id", "vendor_id", "invoice_id", "status", "created_at", "completed_at"}.issubset(existing):
                    return {"available": False, "investigations": [], "reason": "investigation_schema_incomplete"}
                investigations = connection.execute(
                    """SELECT * FROM investigations WHERE vendor_id = ? AND (invoice_id = ? OR invoice_id IS NULL)
                       ORDER BY created_at DESC""", (vendor_id, invoice_id),
                ).fetchall()
                evidence_columns = {row[1] for row in connection.execute("PRAGMA table_info(evidence)")}
                if "evidence" not in {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                    evidence_columns = set()
                evidence_records: dict[str, list[dict[str, Any]]] = {}
                if evidence_columns and {"evidence_id", "investigation_id", "check_type", "finding", "verification_status", "source_type", "created_at"}.issubset(evidence_columns):
                    for investigation in investigations:
                        case_id = investigation["investigation_id"]
                        rows = connection.execute("SELECT * FROM evidence WHERE investigation_id = ? ORDER BY created_at, evidence_id", (case_id,)).fetchall()
                        decoded = []
                        for record in rows:
                            entry = dict(record)
                            matched = entry.get("matched_entity")
                            if matched:
                                try:
                                    import json
                                    entry["matched_entity"] = json.loads(matched)
                                except (TypeError, ValueError):
                                    entry["matched_entity"] = None
                            entry.setdefault("source_url", None)
                            entry.setdefault("retrieved_at", None)
                            decoded.append(entry)
                        evidence_records[case_id] = decoded
                result = []
                for case in investigations:
                    item = dict(case)
                    item["evidence"] = evidence_records.get(item["investigation_id"], [])
                    result.append(item)
            return {"available": True, "investigations": result, "reason": None}
        except sqlite3.Error:
            return {"available": False, "investigations": [], "reason": "database_unavailable"}

    def existing_open_investigation(self, vendor_id: str, invoice_id: str) -> dict[str, Any] | None:
        result = self.investigations_for_invoice(vendor_id, invoice_id)
        if not result["available"]:
            return None
        open_items = [item for item in result["investigations"] if str(item.get("status", "")).lower() in {"open", "in_progress", "pending"}]
        return next((item for item in open_items if item.get("invoice_id") == invoice_id), None) or next(
            (item for item in open_items if item.get("invoice_id") is None), None
        )
