"""Read-only structured and document/evidence retrieval for Sentinel AI."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.repositories.invoices import InvoiceRepository
from app.repositories.network import NetworkRepository
from app.repositories.vendors import VendorRepository


def _source(source_id: str, source_type: str, record_type: str,
            fields: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_type": source_type,
        "record_type": record_type,
        "fields": fields,
        "provenance": provenance,
    }


class StructuredRetrievalRepository:
    """Query existing CSV-backed repositories without reloading CSVs here."""

    def __init__(self, data_dir: str | Path, investigation_db: str | Path) -> None:
        self.invoices = InvoiceRepository(data_dir, investigation_db)
        self.vendors = VendorRepository(data_dir, investigation_db)
        self.network = NetworkRepository(data_dir)

    def resolve_entity(self, entity_type: str, entity_id: str) -> dict[str, Any]:
        """Resolve an identifier by exact ID against the existing source repositories."""
        if entity_type == "invoice":
            tables = self.invoices._tables()
            available_tables = [tables[name] for name in ("dashboard", "invoices") if tables[name].available]
            matches = [str(row.get("invoice_id")).strip()
                       for table in available_tables for row in table.rows
                       if str(row.get("invoice_id") or "").strip().casefold() == entity_id.casefold()]
            resolved_id = matches[0] if matches else None
            found = bool(resolved_id and self.invoices.invoice_detail(resolved_id))
            availability = bool(available_tables)
            reason = None if availability else "invoice_data_unavailable"
        elif entity_type == "vendor":
            tables = self.vendors._tables()
            vendor_table = tables["vendors"]
            matches = [str(row.get("vendor_id")).strip() for row in vendor_table.rows
                       if vendor_table.available and str(row.get("vendor_id") or "").strip().casefold() == entity_id.casefold()]
            resolved_id = matches[0] if matches else None
            found = bool(resolved_id and self.vendors.vendor_detail(resolved_id))
            availability = vendor_table.available
            reason = None if availability else "vendor_data_unavailable"
        elif entity_type in {"purchase_order", "contract"}:
            graph = self.network.graph()
            exact = next((node for node in graph.get("nodes", [])
                          if node.get("entity_type") == entity_type
                          and str(node.get("entity_id", "")).casefold() == entity_id.casefold()), None)
            found = exact is not None
            source_key = entity_type
            availability = graph.get("sources", {}).get(source_key, {}).get("available", False)
            reason = graph.get("sources", {}).get(source_key, {}).get("reason")
        else:
            return {"found": False, "available": False, "reason": "unsupported_entity_type"}
        return {
            "found": bool(found),
            "available": bool(availability),
            "reason": reason if not availability else (None if found else "record_not_found"),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "resolved_id": (resolved_id if entity_type in {"invoice", "vendor"} else
                            exact.get("entity_id") if exact else None) if found else None,
        }

    @staticmethod
    def _from_invoice(detail: dict[str, Any]) -> list[dict[str, Any]]:
        invoice_id = detail["invoice_id"]
        vendor_id = detail.get("vendor_id")
        provenance = {"source_files": ["invoices.csv"], "invoice_id": invoice_id}
        items = [_source(f"invoice:{invoice_id}", "internal_record", "invoice",
                         {"invoice": detail["invoice"], "vendor_id": vendor_id,
                          "purchase_orders": detail.get("purchase_orders", [])}, provenance)]
        if detail.get("vendor"):
            items.append(_source(f"vendor:{vendor_id}", "internal_record", "vendor",
                                 detail["vendor"], {"source_files": ["vendors.csv"], "vendor_id": vendor_id}))
        for po in detail.get("purchase_orders", []):
            po_id = po.get("po_id")
            items.append(_source(f"purchase_order:{po_id}", "internal_record", "purchase_order", po,
                                 {"source_files": ["purchase_orders.csv"], "po_id": po_id,
                                  "invoice_id": invoice_id}))
        for contract in detail.get("contracts", []):
            contract_id = contract.get("contract_id")
            items.append(_source(f"contract:{contract_id}", "internal_document", "contract", contract,
                                 {"source_files": ["contracts.csv"], "contract_id": contract_id,
                                  "vendor_id": vendor_id}))
        for rule in detail.get("detection", {}).get("rules", []):
            rule_id = rule.get("rule")
            items.append(_source(f"detector:rule:{invoice_id}:{rule_id}", "detector_signal", "rule_signal",
                                 rule, {"source_files": ["dashboard_data.csv"], "invoice_id": invoice_id,
                                        "detector": "rules"}))
        gnn = detail.get("detection", {}).get("gnn", {})
        if gnn and (gnn.get("risk_score") is not None or gnn.get("prediction") is not None):
            items.append(_source(f"detector:gnn:{invoice_id}", "detector_signal", "gnn_result", gnn,
                                 {"source_files": ["dashboard_data.csv"], "invoice_id": invoice_id,
                                  "detector": "gnn"}))
        rag = detail.get("detection", {}).get("rag")
        if rag:
            items.append(_source(f"detector:contract_rag:{invoice_id}", "detector_signal", "contract_rag_result",
                                 rag, {"source_files": ["rag_similarity_scores.csv"], "invoice_id": invoice_id,
                                       "detector": "contract_rag"}))
        for index, decision in enumerate(detail.get("human_decisions", [])):
            key = decision.get("time") or str(index)
            items.append(_source(f"audit:{invoice_id}:{key}", "human_audit_decision", "audit_decision",
                                 decision, {"source_files": ["audit_log.csv"], "invoice_id": invoice_id}))
        return items

    @staticmethod
    def _from_vendor(detail: dict[str, Any]) -> list[dict[str, Any]]:
        vendor = detail.get("vendor") or {}
        vendor_id = detail["vendor_id"]
        items = [_source(f"vendor:{vendor_id}", "internal_record", "vendor", vendor,
                         {"source_files": ["vendors.csv"], "vendor_id": vendor_id})]
        for item in detail.get("invoices", []):
            invoice = item.get("invoice") or {}
            invoice_id = invoice.get("invoice_id")
            if not invoice_id:
                continue
            fields = {key: item.get(key) for key in (
                "invoice", "po_id", "amount", "date", "item_category", "payment_status",
                "signals", "risk_score", "gnn_prediction", "rag_status",
            )}
            items.append(_source(f"invoice:{invoice_id}", "internal_record", "invoice", fields,
                                 {"source_files": ["invoices.csv", "purchase_orders.csv"],
                                  "invoice_id": invoice_id, "vendor_id": vendor_id}))
        for po in detail.get("purchase_orders", []):
            po_id = po.get("po_id")
            items.append(_source(f"purchase_order:{po_id}", "internal_record", "purchase_order", po,
                                 {"source_files": ["purchase_orders.csv"], "po_id": po_id,
                                  "vendor_id": vendor_id}))
        for contract in detail.get("contracts", []):
            contract_id = contract.get("contract_id")
            items.append(_source(f"contract:{contract_id}", "internal_document", "contract", contract,
                                 {"source_files": ["contracts.csv"], "contract_id": contract_id,
                                  "vendor_id": vendor_id}))
        for decision in detail.get("human_decisions", []):
            invoice_id = decision.get("invoice_id") or "vendor"
            key = decision.get("time") or "undated"
            items.append(_source(f"audit:{invoice_id}:{key}", "human_audit_decision", "audit_decision",
                                 decision, {"source_files": ["audit_log.csv"], "vendor_id": vendor_id,
                                            "invoice_id": decision.get("invoice_id")}))
        return items

    def _from_network_connections(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        detail = self.network.node_detail(entity_type, entity_id)
        if not detail:
            return []
        items = []
        for connection in detail.get("connections", []):
            node = connection.get("node", {})
            kind, identifier = node.get("entity_type"), node.get("entity_id")
            if not kind or not identifier:
                continue
            relationship = connection.get("relationship", {})
            source_files = {
                "employee": "employees.csv", "vendor": "vendors.csv",
                "purchase_order": "purchase_orders.csv", "invoice": "invoices.csv",
                "contract": "contracts.csv",
            }.get(kind)
            items.append(_source(
                f"{kind}:{identifier}", "internal_document" if kind == "contract" else "internal_record",
                kind, node.get("properties", {}),
                {"source_files": [source_files] if source_files else [], "entity_id": identifier,
                 "related_to": f"{entity_type}:{entity_id}", "relationship": relationship},
            ))
        return items

    def retrieve(self, query: str, *, invoice_id: str | None = None,
                 vendor_id: str | None = None, entity_type: str | None = None,
                 entity_id: str | None = None, intent: str | None = None,
                 limit: int = 20) -> dict[str, Any]:
        """Find invoice/vendor records and related entities using existing repo APIs."""
        query = query.strip()
        invoice_id = invoice_id or (query if self.invoices.invoice_detail(query) is not None else None)
        vendor_id = vendor_id or (query if self.vendors.vendor_detail(query) is not None else None)
        items: list[dict[str, Any]] = []
        availability: dict[str, Any] = {}
        seen: set[str] = set()

        def append(records: list[dict[str, Any]]) -> None:
            for record in records:
                if record["source_id"] not in seen:
                    seen.add(record["source_id"])
                    items.append(record)

        if invoice_id:
            detail = self.invoices.invoice_detail(invoice_id)
            invoice_status = self.invoices.list_invoices(query=invoice_id, limit=1)
            availability["invoice_records"] = {"available": invoice_status["available"],
                                                 "reason": invoice_status.get("reason") if not invoice_status["available"] else (None if detail is not None else "record_not_found")}
            if detail:
                append(self._from_invoice(detail))
                append(self._from_network_connections("invoice", invoice_id))
        if vendor_id:
            detail = self.vendors.vendor_detail(vendor_id)
            vendor_status = self.vendors.list_vendors(query=vendor_id, limit=1)
            availability["vendor_records"] = {"available": vendor_status["available"],
                                                "reason": vendor_status.get("reason") if not vendor_status["available"] else (None if detail is not None else "record_not_found")}
            if detail:
                append(self._from_vendor(detail))
                append(self._from_network_connections("vendor", vendor_id))

        if entity_type in {"purchase_order", "contract"} and entity_id:
            detail = self.network.node_detail(entity_type, entity_id)
            if detail:
                node = detail["node"]
                source_file = "purchase_orders.csv" if entity_type == "purchase_order" else "contracts.csv"
                append([_source(f"{entity_type}:{entity_id}",
                                "internal_document" if entity_type == "contract" else "internal_record",
                                entity_type, node.get("properties", {}),
                                {"source_files": [source_file], "entity_id": entity_id})])
                for connection in detail.get("connections", []):
                    connected = connection.get("node", {})
                    kind, identifier = connected.get("entity_type"), connected.get("entity_id")
                    if kind and identifier:
                        file_for_kind = {"employee": "employees.csv", "vendor": "vendors.csv",
                                         "invoice": "invoices.csv", "purchase_order": "purchase_orders.csv",
                                         "contract": "contracts.csv"}.get(kind)
                        append([_source(f"{kind}:{identifier}",
                                        "internal_document" if kind == "contract" else "internal_record",
                                        kind, connected.get("properties", {}),
                                        {"source_files": [file_for_kind] if file_for_kind else [],
                                         "entity_id": identifier,
                                         "related_to": f"{entity_type}:{entity_id}",
                                         "relationship": connection.get("relationship", {})})])
            availability["entity_relationships"] = {
                "available": bool(detail), "reason": None if detail else "record_not_found"}

        if not invoice_id and not vendor_id and not entity_id and query:
            bounded_limit = min(max(limit, 1), 12)
            if intent not in {"vendor", "purchase_order", "contract", "relationship"}:
                invoice_result = self.invoices.list_invoices(query=query, limit=bounded_limit)
                availability["invoice_records"] = {"available": invoice_result["available"],
                                                     "reason": invoice_result.get("reason")}
                for item in invoice_result.get("items", []):
                    detail = self.invoices.invoice_detail(item["invoice_id"])
                    if detail:
                        append(self._from_invoice(detail))
            if intent not in {"invoice", "purchase_order", "contract", "relationship"}:
                vendor_result = self.vendors.list_vendors(query=query, limit=bounded_limit)
                availability["vendor_records"] = {"available": vendor_result["available"],
                                                    "reason": vendor_result.get("reason")}
                for item in vendor_result.get("items", []):
                    detail = self.vendors.vendor_detail(item["vendor_id"])
                    if detail:
                        append(self._from_vendor(detail))

        # NetworkRepository is the existing read-only source for employee records
        # and explicit entity relationships. Only add graph records on a match.
        if query and not invoice_id and not vendor_id and not entity_id and intent not in {"invoice", "vendor"}:
            graph = self.network.graph(query=query)
            availability["entity_relationships"] = {
                "available": any(source.get("available") for source in graph.get("sources", {}).values()),
                "reason": None if graph.get("nodes") else "no_matching_records",
                "sources": graph.get("sources", {}),
            }
            for node in graph.get("nodes", []):
                kind, identifier = node.get("entity_type"), node.get("entity_id")
                if kind in {"employee", "purchase_order", "invoice", "contract"} and identifier:
                    source_files = {
                        "employee": "employees.csv", "purchase_order": "purchase_orders.csv",
                        "invoice": "invoices.csv", "contract": "contracts.csv",
                    }
                    append([_source(f"{kind}:{identifier}", "internal_record", kind, node.get("properties", {}),
                                   {"source_files": [source_files[kind]], "entity_id": identifier,
                                    "relationships": [edge for edge in graph.get("edges", [])
                                                      if edge.get("source") == node.get("id") or edge.get("target") == node.get("id")]})])
        status = "matched" if items else "unavailable" if any(
            not source.get("available", False) for source in availability.values()
        ) else "no_match"
        return {"records": items[:max(1, limit)], "availability": availability, "status": status}


class InvestigationEvidenceRepository:
    """Search persisted investigation evidence using SQLite read-only mode."""

    REQUIRED_INVESTIGATION_COLUMNS = {"investigation_id", "vendor_id", "invoice_id", "status", "created_at", "completed_at"}
    REQUIRED_EVIDENCE_COLUMNS = {"evidence_id", "investigation_id", "check_type", "finding",
                                 "verification_status", "source_type", "created_at"}

    def __init__(self, investigation_db: str | Path) -> None:
        self.path = Path(investigation_db)

    def retrieve(self, query: str, *, invoice_id: str | None = None,
                 vendor_id: str | None = None, limit: int = 20) -> dict[str, Any]:
        if not self.path.is_file():
            return {"records": [], "available": False, "reason": "database_missing", "status": "unavailable"}
        uri = f"file:{quote(str(self.path.resolve()) )}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=2.0) as connection:
                connection.row_factory = sqlite3.Row
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "investigations" not in tables:
                    return {"records": [], "available": False, "reason": "investigation_table_missing", "status": "unavailable"}
                investigation_columns = {row[1] for row in connection.execute("PRAGMA table_info(investigations)")}
                if not self.REQUIRED_INVESTIGATION_COLUMNS.issubset(investigation_columns):
                    return {"records": [], "available": False, "reason": "investigation_schema_incomplete", "status": "unavailable"}
                if "evidence" not in tables:
                    return {"records": [], "available": False, "reason": "evidence_table_missing", "status": "unavailable"}
                evidence_columns = {row[1] for row in connection.execute("PRAGMA table_info(evidence)")}
                if not self.REQUIRED_EVIDENCE_COLUMNS.issubset(evidence_columns):
                    return {"records": [], "available": False, "reason": "evidence_schema_incomplete", "status": "unavailable"}
                clauses: list[str] = []
                params: list[Any] = []
                if vendor_id:
                    clauses.append("i.vendor_id = ?")
                    params.append(vendor_id)
                if invoice_id:
                    clauses.append("i.invoice_id = ?")
                    params.append(invoice_id)
                if query.strip() and not (invoice_id or vendor_id):
                    clauses.append("(lower(e.finding) LIKE ? OR lower(e.check_type) LIKE ?)")
                    term = f"%{query.strip().casefold()}%"
                    params.extend((term, term))
                where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                rows = connection.execute(
                    f"""SELECT i.investigation_id, i.vendor_id, i.invoice_id, i.status AS investigation_status,
                               i.created_at AS investigation_created_at, e.evidence_id, e.check_type, e.finding,
                               e.matched_entity, e.verification_status, e.source_type, e.created_at,
                               e.source_url, e.retrieved_at
                        FROM investigations i JOIN evidence e USING (investigation_id)
                        {where} ORDER BY e.created_at DESC, e.evidence_id LIMIT ?""",
                    [*params, min(max(limit, 1), 100)],
                ).fetchall()
                records = []
                for row in rows:
                    record = dict(row)
                    evidence_id = record.pop("evidence_id")
                    matched = record.get("matched_entity")
                    if matched:
                        import json
                        try:
                            record["matched_entity"] = json.loads(matched)
                        except (TypeError, ValueError):
                            record["matched_entity"] = None
                    record_type = "external_investigation_evidence" if record.get("source_type") in {"web_search", "government_registry", "official_company_website", "stock_exchange_filing", "third_party_directory"} else "investigation_evidence"
                    records.append(_source(
                        f"evidence:{evidence_id}", record_type, "investigation_evidence", record,
                        {"database": self.path.name, "table": "evidence", "evidence_id": evidence_id,
                         "investigation_id": record.get("investigation_id"),
                         "source_url": record.get("source_url"), "retrieved_at": record.get("retrieved_at")},
                    ))
            return {"records": records, "available": True, "reason": None,
                    "status": "matched" if records else "no_match"}
        except sqlite3.Error:
            return {"records": [], "available": False, "reason": "database_unavailable", "status": "unavailable"}
