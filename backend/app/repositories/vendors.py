"""Vendor profiles and joins across the existing SentinelP2P artifacts."""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.repositories.dashboard import CsvTable
from app.repositories.invoices import InvoiceRepository, RULE_LABELS, _bool, _number, _text


class VendorRepository:
    def __init__(self, data_dir: str | Path, investigation_db: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.investigation_db = Path(investigation_db)
        self.invoices = InvoiceRepository(data_dir, investigation_db)

    def _tables(self) -> dict[str, CsvTable]:
        return self.invoices._tables()

    @staticmethod
    def _index(table: CsvTable, key: str) -> dict[str, dict[str, str | None]]:
        return InvoiceRepository._index(table, key)

    @staticmethod
    def _availability(tables: dict[str, CsvTable]) -> dict[str, Any]:
        return InvoiceRepository._availability(tables)

    def _vendor_invoice_rows(self, tables: dict[str, CsvTable]) -> tuple[dict[str, list[dict[str, Any]]], bool]:
        invoices = tables["invoices"]
        purchase_orders = tables["purchase_orders"]
        if not invoices.available or not purchase_orders.available:
            return {}, False
        po_to_vendor, _ = InvoiceRepository._po_vendor_index(purchase_orders)
        dashboard_rows = self._index(tables["dashboard"], "invoice_id")
        audit_by_invoice: dict[str, list[dict[str, str | None]]] = defaultdict(list)
        if tables["audit"].available:
            for record in tables["audit"].rows:
                invoice_id = _text(record.get("invoice_id"))
                if invoice_id and _text(record.get("decision")):
                    audit_by_invoice[invoice_id].append(record)
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for invoice in invoices.rows:
            invoice_id = _text(invoice.get("invoice_id"))
            po_id = _text(invoice.get("po_id"))
            vendor_id = po_to_vendor.get(po_id or "")
            if not invoice_id or not vendor_id:
                continue
            prepared = dashboard_rows.get(invoice_id, {})
            signals = InvoiceRepository._signal_names(prepared, tables["dashboard"].columns) if tables["dashboard"].available else []
            decisions = audit_by_invoice.get(invoice_id, [])
            decisions.sort(key=lambda row: str(row.get("time") or ""))
            groups[vendor_id].append({
                "invoice": dict(invoice),
                "po_id": po_id,
                "amount": _number(invoice.get("amount")) if "amount" in invoices.columns else _number(prepared.get("amount")),
                "date": _text(invoice.get("date")) if "date" in invoices.columns else _text(prepared.get("date")),
                "item_category": _text(invoice.get("item_category")) if "item_category" in invoices.columns else _text(prepared.get("item_category")),
                "payment_status": _text(invoice.get("payment_status")) if "payment_status" in invoices.columns else _text(prepared.get("payment_status")),
                "overall_status": _text(prepared.get("overall_status")),
                "signals": signals,
                "risk_score": _number(prepared.get("gnn_risk_score")),
                "gnn_prediction": _bool(prepared.get("gnn_prediction")),
                "rag_status": _text(prepared.get("rag_status")),
                "human_decision": decisions[-1].get("decision") if decisions else None,
                "human_decision_time": decisions[-1].get("time") if decisions else None,
                "human_decision_status": "unavailable" if not tables["audit"].available else "decision_recorded" if decisions else "no_decision_recorded",
            })
        return groups, True

    def list_vendors(
        self, *, query: str = "", status: str = "all", category: str = "", signal: str = "",
        sort_by: str = "vendor_name", sort_dir: str = "asc", limit: int = 25, offset: int = 0,
    ) -> dict[str, Any]:
        tables = self._tables()
        vendor_table = tables["vendors"]
        if not vendor_table.available:
            return {"available": False, "items": [], "total": None, "limit": limit, "offset": offset,
                    "available_categories": [], "available_signals": [], "sources": self._availability(tables),
                    "invoice_metrics_available": False, "reason": "vendor_data_unavailable"}

        invoice_groups, invoice_metrics_available = self._vendor_invoice_rows(tables)
        category_options = sorted({value for row in vendor_table.rows if (value := _text(row.get("vendor_category")))})
        signal_options = sorted({signal_name for rows in invoice_groups.values() for row in rows for signal_name in row["signals"]})
        needle = query.strip().casefold()
        assembled = []
        amount_complete = "amount" in tables["invoices"].columns or (tables["dashboard"].available and "amount" in tables["dashboard"].columns)
        risk_available = tables["dashboard"].available
        for vendor in vendor_table.rows:
            vendor_id = _text(vendor.get("vendor_id"))
            if not vendor_id:
                continue
            vendor_name = _text(vendor.get("vendor_name"))
            rows = invoice_groups.get(vendor_id, [])
            flagged_count = sum(row["overall_status"] == "Flagged" for row in rows) if risk_available else None
            amounts = [row["amount"] for row in rows]
            transaction_value = sum(value for value in amounts if value is not None) if invoice_metrics_available and amount_complete and all(value is not None for value in amounts) else None
            signal_counts = Counter(name for row in rows for name in row["signals"])
            indicators = [{"label": name, "invoice_count": count} for name, count in sorted(signal_counts.items())]
            record = {
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "email": _text(vendor.get("email")),
                "phone": _text(vendor.get("phone")),
                "registration_number": _text(vendor.get("registration_number")),
                "bank_account": InvoiceRepository._vendor_view(vendor).get("bank_account"),
                "vendor_category": _text(vendor.get("vendor_category")),
                "invoice_count": len(rows) if invoice_metrics_available else None,
                "total_transaction_value": transaction_value,
                "flagged_invoice_count": flagged_count,
                "risk_indicators": indicators if risk_available else None,
                "risk_indicators_available": risk_available,
            }
            if status == "flagged" and not (flagged_count and flagged_count > 0):
                continue
            if status == "clear" and (flagged_count is None or flagged_count > 0):
                continue
            if status == "no_invoices" and (record["invoice_count"] is None or record["invoice_count"] > 0):
                continue
            if category and record["vendor_category"] != category:
                continue
            if signal and not any(item["label"] == signal for item in indicators):
                continue
            searchable = " ".join(str(record.get(field) or "") for field in ("vendor_id", "vendor_name", "email", "phone", "registration_number", "vendor_category")).casefold()
            if needle and needle not in searchable:
                continue
            assembled.append(record)

        sorters = {
            "vendor_id": lambda item: item["vendor_id"].casefold(),
            "vendor_name": lambda item: (item["vendor_name"] or "").casefold(),
            "invoice_count": lambda item: item["invoice_count"] if item["invoice_count"] is not None else -1,
            "total_transaction_value": lambda item: item["total_transaction_value"] if item["total_transaction_value"] is not None else -1,
            "flagged_invoice_count": lambda item: item["flagged_invoice_count"] if item["flagged_invoice_count"] is not None else -1,
            "vendor_category": lambda item: (item["vendor_category"] or "").casefold(),
        }
        assembled.sort(key=sorters.get(sort_by, sorters["vendor_name"]), reverse=sort_dir == "desc")
        return {
            "available": True, "items": assembled[offset:offset + limit], "total": len(assembled),
            "limit": limit, "offset": offset, "available_categories": category_options,
            "available_signals": signal_options, "sources": self._availability(tables),
            "invoice_metrics_available": invoice_metrics_available,
            "reason": None,
        }

    def vendor_detail(self, vendor_id: str) -> dict[str, Any] | None:
        tables = self._tables()
        vendors = self._index(tables["vendors"], "vendor_id")
        vendor = vendors.get(vendor_id)
        if vendor is None:
            return None
        invoice_groups, invoice_metrics_available = self._vendor_invoice_rows(tables)
        invoice_rows = invoice_groups.get(vendor_id, [])
        po_rows = [dict(row) for row in tables["purchase_orders"].rows if tables["purchase_orders"].available and _text(row.get("vendor_id")) == vendor_id]
        contracts = [dict(row) for row in tables["contracts"].rows if tables["contracts"].available and _text(row.get("vendor_id")) == vendor_id]
        audit_records = []
        if tables["audit"].available:
            audit_records = [
                {"time": _text(row.get("time")), "invoice_id": _text(row.get("invoice_id")), "vendor_id": _text(row.get("vendor_id")), "decision": _text(row.get("decision")), "note": _text(row.get("note"))}
                for row in tables["audit"].rows
                if _text(row.get("vendor_id")) == vendor_id and _text(row.get("decision"))
            ]
            audit_records.sort(key=lambda row: row["time"] or "", reverse=True)

        group = invoice_groups.get(vendor_id, [])
        transaction_value = sum(row["amount"] for row in group if row["amount"] is not None) if invoice_metrics_available and all(row["amount"] is not None for row in group) and ("amount" in tables["invoices"].columns or "amount" in tables["dashboard"].columns) else None
        return {
            "vendor_id": vendor_id,
            "vendor": InvoiceRepository._vendor_view(vendor),
            "invoice_count": len(invoice_rows) if invoice_metrics_available else None,
            "total_transaction_value": transaction_value,
            "flagged_invoice_count": sum(row["overall_status"] == "Flagged" for row in invoice_rows) if tables["dashboard"].available else None,
            "risk_indicators": sorted({name for row in invoice_rows for name in row["signals"]}) if tables["dashboard"].available else None,
            "risk_indicators_available": tables["dashboard"].available,
            "invoices": invoice_rows,
            "purchase_orders": po_rows,
            "contracts": contracts,
            "internal_verification_findings": None,
            "investigations": self.investigations_for_vendor(vendor_id),
            "human_decisions": audit_records,
            "sources": self._availability(tables),
        }

    def investigations_for_vendor(self, vendor_id: str) -> dict[str, Any]:
        if not self.investigation_db.is_file():
            return {"available": False, "investigations": [], "reason": "database_missing"}
        uri = f"file:{quote(str(self.investigation_db.resolve()))}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=2.0) as connection:
                connection.row_factory = sqlite3.Row
                investigation_columns = {row[1] for row in connection.execute("PRAGMA table_info(investigations)")}
                if not {"investigation_id", "vendor_id", "invoice_id", "status", "created_at", "completed_at"}.issubset(investigation_columns):
                    return {"available": False, "investigations": [], "reason": "investigation_schema_incomplete"}
                rows = connection.execute("SELECT * FROM investigations WHERE vendor_id = ? ORDER BY created_at DESC", (vendor_id,)).fetchall()
                table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                evidence_columns = {row[1] for row in connection.execute("PRAGMA table_info(evidence)")} if "evidence" in table_names else set()
                has_evidence_schema = {"evidence_id", "investigation_id", "check_type", "finding", "verification_status", "source_type", "created_at"}.issubset(evidence_columns)
                result = []
                for row in rows:
                    case = dict(row)
                    evidence_rows = []
                    if has_evidence_schema:
                        for evidence_row in connection.execute("SELECT * FROM evidence WHERE investigation_id = ? ORDER BY created_at, evidence_id", (case["investigation_id"],)):
                            evidence = dict(evidence_row)
                            evidence.setdefault("source_url", None)
                            evidence.setdefault("retrieved_at", None)
                            raw = evidence.get("matched_entity")
                            if raw:
                                try:
                                    import json
                                    evidence["matched_entity"] = json.loads(raw)
                                except (TypeError, ValueError):
                                    evidence["matched_entity"] = None
                            evidence_rows.append(evidence)
                    case["evidence"] = evidence_rows
                    result.append(case)
            return {"available": True, "investigations": result, "reason": None}
        except sqlite3.Error:
            return {"available": False, "investigations": [], "reason": "database_unavailable"}

    def existing_open_investigation(self, vendor_id: str) -> dict[str, Any] | None:
        result = self.investigations_for_vendor(vendor_id)
        if not result["available"]:
            return None
        return next((case for case in result["investigations"] if str(case.get("status", "")).lower() in {"open", "in_progress", "pending"}), None)
