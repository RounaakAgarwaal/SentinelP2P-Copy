"""Read-only dashboard aggregations over the existing CSV and SQLite artifacts."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

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


def _availability(table: CsvTable) -> dict[str, Any]:
    return {
        "available": table.available,
        "reason": table.reason,
        "missing_columns": list(table.missing_columns),
        "row_count": len(table.rows) if table.available else None,
        "modified_at": table.modified_at,
    }


def _bool(value: str | None) -> bool | None:
    if value is None or value.strip().lower() in {"", "nan", "none", "null"}:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return None


def _number(value: str | None) -> float | None:
    if value is None or value.strip().lower() in {"", "nan", "none", "null"}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date_key(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return value


def _metric(value: int | float | None, available: bool, definition: str, *, unit: str = "count", reason: str | None = None) -> dict[str, Any]:
    return {
        "value": value if available else None,
        "available": available,
        "unit": unit if available else None,
        "definition": definition,
        "reason": reason if not available else None,
    }


def _read_sources(repository: DashboardRepository) -> dict[str, Any]:
    dashboard = repository.dashboard_table()
    vendors = repository.vendors_table()
    purchase_orders = repository.purchase_orders_table()
    audit = repository.audit_log_table()
    investigations = repository.investigations(limit=1000)
    return {
        "dashboard": dashboard,
        "vendors": vendors,
        "purchase_orders": purchase_orders,
        "audit": audit,
        "investigations": investigations,
    }


def _latest_decisions(audit: CsvTable) -> dict[str, dict[str, str | None]]:
    if not audit.available:
        return {}
    latest: dict[str, dict[str, str | None]] = {}
    for row in sorted(audit.rows, key=lambda item: _date_key(item.get("time"))):
        invoice_id = (row.get("invoice_id") or "").strip()
        if invoice_id:
            latest[invoice_id] = row
    return latest


def _vendor_name_index(vendors: CsvTable) -> dict[str, str]:
    if not vendors.available:
        return {}
    return {
        (row.get("vendor_id") or "").strip(): (row.get("vendor_name") or "").strip()
        for row in vendors.rows
        if (row.get("vendor_id") or "").strip() and (row.get("vendor_name") or "").strip()
    }


def _invoice_vendor_index(purchase_orders: CsvTable) -> dict[str, str]:
    if not purchase_orders.available:
        return {}
    mapping: dict[str, str] = {}
    conflicts: set[str] = set()
    for row in purchase_orders.rows:
        po_id = (row.get("po_id") or "").strip()
        vendor_id = (row.get("vendor_id") or "").strip()
        if not po_id or not vendor_id:
            continue
        if po_id in mapping and mapping[po_id] != vendor_id:
            conflicts.add(po_id)
        else:
            mapping[po_id] = vendor_id
    for po_id in conflicts:
        mapping.pop(po_id, None)
    return mapping


def _score_quartiles(scores: list[float]) -> list[dict[str, Any]]:
    ordered = sorted(scores)
    bins = []
    count = len(ordered)
    for index in range(4):
        start = index * count // 4
        end = (index + 1) * count // 4
        values = ordered[start:end]
        if not values:
            continue
        bins.append({
            "label": f"Quartile {index + 1}",
            "min_score": values[0],
            "max_score": values[-1],
            "invoice_count": len(values),
        })
    return bins


class DashboardService:
    def __init__(self, repository: DashboardRepository) -> None:
        self.repository = repository

    def summary(self) -> dict[str, Any]:
        sources = _read_sources(self.repository)
        dashboard: CsvTable = sources["dashboard"]
        vendors: CsvTable = sources["vendors"]
        audit: CsvTable = sources["audit"]
        rows = dashboard.rows if dashboard.available else []
        count_available = dashboard.available
        total = len(rows) if count_available else None

        statuses = [row.get("overall_status") for row in rows]
        statuses_valid = dashboard.available and "overall_status" in dashboard.columns and all(
            status in {"Flagged", "Clear"} for status in statuses
        )
        flagged_count = sum(status == "Flagged" for status in statuses) if statuses_valid else None
        flagged_share = flagged_count / total if statuses_valid and total else None

        vendor_ids = [(row.get("vendor_id") or "").strip() for row in vendors.rows] if vendors.available else []
        vendors_valid = vendors.available and all(vendor_ids)
        vendor_count = len(set(vendor_ids)) if vendors_valid else None

        audited_ids = {
            (row.get("invoice_id") or "").strip()
            for row in audit.rows
            if (row.get("invoice_id") or "").strip() and (row.get("decision") or "").strip()
        } if audit.available else set()

        fresh_tables = [table for table in (dashboard, vendors, sources["purchase_orders"], audit) if table.available]
        return {
            "metrics": {
                "total_invoices": _metric(total, count_available, "Number of rows in data/dashboard_data.csv."),
                "flagged_invoices": _metric(
                    flagged_count,
                    statuses_valid,
                    "Count of prepared dashboard rows whose overall_status is exactly 'Flagged'; this is a review signal, not confirmed fraud.",
                    reason="The prepared overall_status column is missing or contains unknown values.",
                ),
                "flagged_invoice_share": _metric(
                    flagged_share,
                    flagged_share is not None,
                    "Flagged invoices divided by total dashboard rows. It is a flagged-review share, not a fraud rate.",
                    unit="ratio",
                    reason="A valid overall_status value is unavailable for every invoice.",
                ),
                "total_vendors": _metric(
                    vendor_count,
                    vendors_valid,
                    "Count of distinct non-empty vendor_id values in data/vendors.csv.",
                    reason="Vendor records are missing or some vendor IDs are blank.",
                ),
                "pending_audit_reviews": _metric(
                    None,
                    False,
                    "Not available: audit_log.csv stores saved decisions but has no explicit pending-review status or queue.",
                    reason="Pending reviews cannot be derived from the available audit log without inferring from model flags.",
                ),
                "audited_invoices": _metric(
                    len(audited_ids) if audit.available else None,
                    audit.available,
                    "Distinct invoice IDs with at least one non-empty decision in data/audit_log.csv.",
                    reason="The audit log is missing or does not contain the required decision fields.",
                ),
            },
            "source_files_updated_at": self.repository.freshness(fresh_tables),
            "sources": {
                "dashboard_data": _availability(dashboard),
                "vendors": _availability(vendors),
                "audit_log": _availability(audit),
            },
            "notes": [
                "A flagged invoice is an automated review signal, not a confirmed fraud finding.",
                "GNN predictions and investigation status are not human auditor decisions.",
            ],
        }

    def risk_distribution(self) -> dict[str, Any]:
        dashboard = self.repository.dashboard_table()
        if not dashboard.available:
            return {
                "available": False, "kind": "unavailable", "bins": [],
                "note": "Prepared dashboard data is unavailable.", "source": _availability(dashboard),
            }
        if "gnn_risk_score" in dashboard.columns:
            scores = [
                score for row in dashboard.rows
                if (score := _number(row.get("gnn_risk_score"))) is not None
            ]
            if scores:
                return {
                    "available": True,
                    "kind": "gnn_score_quartiles",
                    "bins": _score_quartiles(scores),
                    "note": "Quartiles group observed GNN scores by rank for visualization only. They are not model-defined risk classes or decision thresholds.",
                    "source": _availability(dashboard),
                }
        if "overall_status" in dashboard.columns:
            counts = Counter(row.get("overall_status") for row in dashboard.rows if row.get("overall_status") in {"Flagged", "Clear"})
            if counts:
                return {
                    "available": True,
                    "kind": "review_flag_counts",
                    "bins": [
                        {"label": label, "min_score": None, "max_score": None, "invoice_count": counts[label]}
                        for label in ("Clear", "Flagged") if counts[label]
                    ],
                    "note": "This fallback shows prepared Flagged/Clear review status counts, not fraud classifications.",
                    "source": _availability(dashboard),
                }
        return {
            "available": False, "kind": "unavailable", "bins": [],
            "note": "No supported GNN scores or prepared review statuses are available.",
            "source": _availability(dashboard),
        }

    def detection_overview(self) -> dict[str, Any]:
        dashboard = self.repository.dashboard_table()
        if not dashboard.available:
            unavailable = {"available": False, "reason": "dashboard_data_unavailable", "invoice_count": None, "detail": None}
            return {
                "invoice_count": None, "rules": unavailable, "rule_counts": [],
                "gnn": unavailable, "rag": unavailable, "rag_status_counts": {},
                "notes": ["Dashboard detection artifacts could not be loaded."],
            }
        rows = dashboard.rows
        rule_columns = [column for column in dashboard.columns if column.startswith("rule_")]
        rule_statuses = [[_bool(row.get(column)) for row in rows] for column in rule_columns]
        rules_complete = bool(rule_columns) and all(value is not None for values in rule_statuses for value in values)
        rule_counts = [
            {"rule": column, "flagged_invoices": sum(value is True for value in values)}
            for column, values in zip(rule_columns, rule_statuses)
        ]
        any_rule_values = [_bool(row.get("any_rule_flagged")) for row in rows] if "any_rule_flagged" in dashboard.columns else [
            (any(value is True for value in row_values) if all(value is not None for value in row_values) else None)
            for row_values in zip(*rule_statuses)
        ] if rule_columns else []
        rule_any_complete = bool(any_rule_values) and all(value is not None for value in any_rule_values)

        prediction_values = [_bool(row.get("gnn_prediction")) for row in rows] if "gnn_prediction" in dashboard.columns else []
        gnn_scores = [_number(row.get("gnn_risk_score")) for row in rows] if "gnn_risk_score" in dashboard.columns else []
        prediction_complete = bool(prediction_values) and all(value is not None for value in prediction_values)
        scored_count = sum(score is not None for score in gnn_scores)
        gnn_available = bool(prediction_values or scored_count)

        rag_values = [row.get("rag_status") for row in rows] if "rag_status" in dashboard.columns else []
        rag_known = [str(value).strip() for value in rag_values if value and str(value).strip().lower() not in {"nan", "none", "null"}]
        rag_counts = dict(sorted(Counter(rag_known).items()))

        return {
            "invoice_count": len(rows),
            "rules": {
                "available": bool(rule_columns),
                "reason": None if rule_columns else "rule_columns_missing",
                "invoice_count": sum(value is True for value in any_rule_values) if rule_any_complete else None,
                "detail": f"{sum(value is not None for values in rule_statuses for value in values)} of {len(rows) * len(rule_columns)} rule cells are present." if rule_columns else None,
            },
            "rule_counts": rule_counts if rules_complete else [],
            "gnn": {
                "available": gnn_available,
                "reason": None if gnn_available else "gnn_outputs_missing",
                "invoice_count": sum(value is True for value in prediction_values) if prediction_values else None,
                "detail": f"{scored_count} of {len(rows)} invoices have a numeric GNN risk score; predictions are model outputs, not human decisions." if "gnn_risk_score" in dashboard.columns else None,
            },
            "rag": {
                "available": bool(rag_values),
                "reason": None if rag_values else "rag_status_missing",
                "invoice_count": rag_counts.get("mismatch", 0) if rag_values else None,
                "detail": "Contract/invoice semantic similarity statuses; this is not conversational AI.",
            },
            "rag_status_counts": rag_counts,
            "notes": [
                "Rule, GNN, and RAG outputs are reported separately.",
                "Missing detector values are not counted as negative results.",
            ],
        }

    def recent_invoices(self, *, limit: int = 10) -> dict[str, Any]:
        sources = _read_sources(self.repository)
        dashboard: CsvTable = sources["dashboard"]
        if not dashboard.available or "overall_status" not in dashboard.columns:
            return {
                "available": False, "items": [],
                "reason": "dashboard_data_missing_or_overall_status_unavailable",
                "sources": {
                    "dashboard_data": _availability(dashboard),
                    "purchase_orders": _availability(sources["purchase_orders"]),
                    "vendors": _availability(sources["vendors"]),
                    "audit_log": _availability(sources["audit"]),
                },
                "note": "Recent flagged invoices require the prepared overall_status source field.",
            }
        po_to_vendor = _invoice_vendor_index(sources["purchase_orders"])
        vendor_names = _vendor_name_index(sources["vendors"])
        decisions = _latest_decisions(sources["audit"])
        flagged = [row for row in dashboard.rows if row.get("overall_status") == "Flagged"]
        flagged.sort(key=lambda row: _date_key(row.get("date")), reverse=True)
        items = []
        for row in flagged[:max(1, min(limit, 100))]:
            invoice_id = (row.get("invoice_id") or "").strip()
            vendor_id = po_to_vendor.get((row.get("po_id") or "").strip())
            rule_columns = [column for column in dashboard.columns if column.startswith("rule_")]
            sources_found = [
                RULE_LABELS.get(column, column.removeprefix("rule_").replace("_", " "))
                for column in rule_columns if _bool(row.get(column)) is True
            ]
            if _bool(row.get("gnn_prediction")) is True:
                sources_found.append("GNN prediction")
            if row.get("rag_status") == "mismatch":
                sources_found.append("Contract RAG mismatch")
            decision = decisions.get(invoice_id) if sources["audit"].available else None
            items.append({
                "invoice_id": invoice_id,
                "vendor_id": vendor_id,
                "vendor_name": vendor_names.get(vendor_id or ""),
                "amount": _number(row.get("amount")),
                "invoice_date": row.get("date"),
                "risk_score": _number(row.get("gnn_risk_score")),
                "detection_sources": sources_found,
                "review_status": "unavailable" if not sources["audit"].available else "decision_recorded" if decision else "no_decision_recorded",
                "human_decision": decision.get("decision") if decision else None,
            })
        return {
            "available": True,
            "items": items,
            "reason": None,
            "sources": {
                "dashboard_data": _availability(dashboard),
                "purchase_orders": _availability(sources["purchase_orders"]),
                "vendors": _availability(sources["vendors"]),
                "audit_log": _availability(sources["audit"]),
            },
            "note": "Flagged rows are review signals, not confirmed fraud. 'No decision recorded' means the audit log has no saved decision for that invoice; it does not assert queue status.",
        }

    def high_risk_vendors(self, *, limit: int = 8) -> dict[str, Any]:
        sources = _read_sources(self.repository)
        dashboard: CsvTable = sources["dashboard"]
        purchase_orders: CsvTable = sources["purchase_orders"]
        vendors: CsvTable = sources["vendors"]
        investigations: InvestigationData = sources["investigations"]
        if not dashboard.available or not purchase_orders.available:
            return {
                "available": False, "items": [], "reason": "dashboard_or_purchase_order_data_unavailable",
                "sources": {
                    "dashboard_data": _availability(dashboard),
                    "purchase_orders": _availability(purchase_orders),
                    "vendors": _availability(vendors),
                    "investigations": {"available": investigations.available, "reason": investigations.reason, "missing_columns": [], "row_count": len(investigations.rows) if investigations.available else None, "modified_at": None},
                },
                "note": "Vendor aggregation requires invoice dashboard rows and the PO-to-vendor relationship.",
            }
        po_to_vendor = _invoice_vendor_index(purchase_orders)
        names = _vendor_name_index(vendors)
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in dashboard.rows:
            vendor_id = po_to_vendor.get((row.get("po_id") or "").strip())
            if vendor_id:
                groups[vendor_id].append(row)
        latest_investigation: dict[str, dict[str, Any]] = {}
        if investigations.available:
            for row in sorted(investigations.rows, key=lambda item: _date_key(item.get("created_at")), reverse=True):
                latest_investigation.setdefault(str(row.get("vendor_id") or ""), row)

        items = []
        has_supported_indicator = False
        for vendor_id, rows in groups.items():
            scores = [_number(row.get("gnn_risk_score")) for row in rows]
            known_scores = [score for score in scores if score is not None]
            flagged_count = sum(row.get("overall_status") == "Flagged" for row in rows)
            max_score = max(known_scores) if known_scores else None
            if max_score is None and flagged_count == 0:
                continue
            has_supported_indicator = True
            investigation = latest_investigation.get(vendor_id) if investigations.available else None
            items.append({
                "vendor_id": vendor_id,
                "vendor_name": names.get(vendor_id),
                "related_invoice_count": len(rows),
                "flagged_invoice_count": flagged_count,
                "max_gnn_score": max_score,
                "risk_indicator": "Highest observed related-invoice GNN score; ranking only, no threshold applied." if max_score is not None else "Count of related invoices flagged by the prepared dashboard status.",
                "investigation_status": str(investigation["status"]) if investigation and investigation.get("status") else None,
                "investigation_recorded": bool(investigation) if investigations.available else None,
            })
        items.sort(key=lambda item: (item["max_gnn_score"] is not None, item["max_gnn_score"] or -1, item["flagged_invoice_count"]), reverse=True)
        available = has_supported_indicator
        return {
            "available": available,
            "items": items[:max(1, min(limit, 100))] if available else [],
            "reason": None if available else "no_supported_vendor_risk_indicator_available",
            "sources": {
                "dashboard_data": _availability(dashboard),
                "purchase_orders": _availability(purchase_orders),
                "vendors": _availability(vendors),
                "investigations": {"available": investigations.available, "reason": investigations.reason, "missing_columns": [], "row_count": len(investigations.rows) if investigations.available else None, "modified_at": None},
            },
            "note": "Vendors are ranked by their maximum observed related-invoice GNN score, with flagged counts shown separately. A ranking is not a risk classification or fraud finding.",
        }

    def recent_investigations(self, *, limit: int = 10) -> dict[str, Any]:
        investigations: InvestigationData = self.repository.investigations(limit=max(1, min(limit, 100)))
        vendors = self.repository.vendors_table()
        audit = self.repository.audit_log_table()
        names = _vendor_name_index(vendors)
        investigation_items = [
            {
                "investigation_id": row["investigation_id"],
                "vendor_id": row["vendor_id"],
                "vendor_name": names.get(str(row["vendor_id"])),
                "invoice_id": row["invoice_id"],
                "status": row["status"],
                "created_at": row["created_at"],
                "completed_at": row["completed_at"],
            }
            for row in investigations.rows
        ]
        decisions = []
        if audit.available:
            decisions = [
                {"time": row.get("time") or "", "invoice_id": row.get("invoice_id") or "",
                 "vendor_id": row.get("vendor_id") or "", "decision": row.get("decision") or ""}
                for row in sorted(audit.rows, key=lambda item: _date_key(item.get("time")), reverse=True)
                if (row.get("invoice_id") or "").strip() and (row.get("decision") or "").strip()
            ][:max(1, min(limit, 100))]
        return {
            "investigations_available": investigations.available,
            "investigations": investigation_items,
            "investigations_reason": investigations.reason,
            "decisions_available": audit.available,
            "human_decisions": decisions,
            "decisions_reason": audit.reason,
            "note": "Investigation status and human auditor decisions come from separate records and are not interchangeable.",
        }
