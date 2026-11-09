"""Build a LangGraph-ready input dictionary from the existing project CSVs."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .checks import run_internal_vendor_checks

KNOWN_RULE_COLUMNS = {
    "rule_shell_vendor", "rule_split_po", "rule_duplicate_invoice", "rule_same_creator_approver",
    "rule_new_vendor_high_value", "rule_contract_rate_mismatch", "rule_vendor_employee_email",
    "rule_category_mismatch",
}


def _load_table(data_dir: Path, name: str, required_columns: set[str]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    path = data_dir / f"{name}.csv"
    if not path.is_file():
        return [], {"available": False, "path": str(path), "reason": "file_missing", "missing_columns": sorted(required_columns)}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = set(reader.fieldnames or [])
    missing = sorted(required_columns - columns)
    return rows, {
        "available": not missing,
        "path": str(path),
        "row_count": len(rows),
        "missing_columns": missing,
        "reason": "missing_required_columns" if missing else None,
    }


def _index(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {row[key]: row for row in rows if row.get(key)}


def _bool(value: Any) -> bool | None:
    if value is None or str(value).strip().lower() in {"", "nan", "none", "null"}:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return None


def _mask_account(value: str) -> str:
    value = "".join(character for character in str(value) if character.isalnum())
    return f"****{value[-4:]}" if value else "****"


def _sanitize_vendor(vendor: dict[str, str]) -> dict[str, str]:
    safe = dict(vendor)
    if "bank_account" in safe:
        safe["bank_account"] = _mask_account(safe["bank_account"])
    return safe


def _vendor_from_csv(vendor_id: str, vendor_csv: str | Path) -> tuple[dict[str, str], dict[str, Any]]:
    path = Path(vendor_csv)
    if not path.is_file():
        raise FileNotFoundError(f"Vendor CSV not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = set(reader.fieldnames or [])
    required = {"vendor_id", "legal_or_public_name"}
    missing = sorted(required - columns)
    if missing:
        raise ValueError(f"Vendor CSV is missing required columns: {', '.join(missing)}")

    selected = next((row for row in rows if (row.get("vendor_id") or "").strip() == vendor_id), None)
    if selected is None:
        raise ValueError(f"Unknown vendor_id in {path}: {vendor_id}")

    # Keep only the supplied vendor identity and research context. Exclude
    # ground-truth and expected-behavior fields from state and search queries.
    vendor = {
        "vendor_id": (selected.get("vendor_id") or "").strip(),
        "vendor_name": (selected.get("legal_or_public_name") or "").strip(),
    }
    for field in ("city", "state", "country", "official_website"):
        if field in columns:
            vendor[field] = (selected.get(field) or "").strip()
    if "known_cin" in columns:
        vendor["registration_number"] = (selected.get("known_cin") or "").strip()
    if "known_registered_office" in columns:
        vendor["address"] = (selected.get("known_registered_office") or "").strip()
    source_info = {
        "available": True,
        "path": str(path),
        "row_count": len(rows),
        "selected_vendor_id": vendor["vendor_id"],
        "required_columns": sorted(required),
    }
    return vendor, source_info


def _unavailable_internal_findings(vendor_id: str) -> list[dict[str, Any]]:
    check_types = (
        "phone_match", "email_match", "bank_account_match", "registration_number_match",
    )
    return [{
        "evidence_id": None,
        "investigation_id": None,
        "check_type": check_type,
        "finding": "Internal check not performed: no real internal vendor or employee records were supplied for this CSV source.",
        "matched_entity": None,
        "verification_status": "unavailable_no_internal_records",
        "coverage_status": "unavailable",
        "source_type": "internal_records",
        "created_at": None,
        "vendor_id": vendor_id,
    } for check_type in check_types]


def build_investigation_input(
    vendor_id: str,
    data_dir: str | Path,
    *,
    invoice_id: str | None = None,
    vendor_csv: str | Path | None = None,
) -> dict[str, Any]:
    """Return vendor, invoice, detector, and internal-check data without inventing missing results.

    Optional CSVs and optional columns are represented by ``None`` values and
    detailed ``data_availability`` entries. Unknown vendors raise ``ValueError``.
    Bank account values in vendor details are masked before they leave this module.
    """
    if not vendor_id or not vendor_id.strip():
        raise ValueError("vendor_id must be a non-empty string")
    vendor_id = vendor_id.strip()

    if vendor_csv is not None:
        if invoice_id is not None:
            raise ValueError("invoice_id cannot be used with a vendor CSV that has no invoice relationships")
        vendor, source_info = _vendor_from_csv(vendor_id, vendor_csv)
        unavailable_reason = "not_loaded_for_external_vendor_source"
        unavailable_info = {"available": False, "reason": unavailable_reason}
        availability = {
            "vendor_source": source_info,
            "vendors": unavailable_info,
            "internal_records": unavailable_info,
            "employees": unavailable_info,
            "invoices": unavailable_info,
            "purchase_orders": unavailable_info,
            "rule_flags": unavailable_info,
            "gnn_scores": unavailable_info,
            "rag_findings": unavailable_info,
        }
        return {
            "vendor_id": vendor_id,
            "invoice_id": None,
            "vendor_details": _sanitize_vendor(vendor),
            "related_invoices": [],
            "internal_verification_findings": _unavailable_internal_findings(vendor_id),
            "data_availability": availability,
            "warnings": [
                "No internal vendor, employee, invoice, PO, detector, GNN or RAG data was loaded for this real-vendor CSV source.",
                "Internal verification checks are unavailable; no_match results have not been inferred.",
            ],
        }

    root = Path(data_dir)

    vendors, vendor_info = _load_table(root, "vendors", {"vendor_id"})
    if not vendor_info["available"]:
        raise FileNotFoundError(f"vendors.csv is unavailable or missing vendor_id in {root}")
    vendor = next((item for item in vendors if item.get("vendor_id") == vendor_id), None)
    if vendor is None:
        raise ValueError(f"Unknown vendor_id: {vendor_id}")

    invoices, invoice_info = _load_table(root, "invoices", {"invoice_id", "po_id"})
    purchase_orders, po_info = _load_table(root, "purchase_orders", {"po_id", "vendor_id"})
    if invoice_info["available"] and po_info["available"]:
        vendor_po_ids = {row["po_id"] for row in purchase_orders if row.get("vendor_id") == vendor_id}
        related = [row for row in invoices if row.get("po_id") in vendor_po_ids]
        if invoice_id is not None:
            related = [row for row in related if row.get("invoice_id") == invoice_id]
            if not related:
                raise ValueError(f"Invoice {invoice_id} is not linked to vendor {vendor_id}")
    else:
        related = []
        if invoice_id is not None:
            raise ValueError("Cannot validate invoice_id because invoice or purchase-order data is unavailable")

    invoice_ids = {row.get("invoice_id") for row in related}
    availability: dict[str, Any] = {
        "vendors": vendor_info,
        "invoices": invoice_info,
        "purchase_orders": po_info,
    }

    rule_name = "rule_flags.csv" if (root / "rule_flags.csv").is_file() else "rule_flags_pandas.csv"
    rule_rows, rule_info = _load_table(root, rule_name.removesuffix(".csv"), {"invoice_id"})
    rule_index = _index(rule_rows, "invoice_id") if rule_info["available"] else {}
    rule_columns = sorted({column for row in rule_rows for column in row if column.startswith("rule_")})
    missing_rule_columns = sorted(KNOWN_RULE_COLUMNS - set(rule_columns))
    rule_missing_reason = "no_rule_columns" if not rule_columns else rule_info.get("reason")
    availability["rule_flags"] = {
        **rule_info,
        "available": rule_info["available"] and bool(rule_columns),
        "complete": rule_info["available"] and not missing_rule_columns,
        "reason": rule_missing_reason,
        "selected_file": rule_name,
        "rule_columns": rule_columns,
        "missing_optional_columns": missing_rule_columns,
    }

    score_rows, score_info = _load_table(root, "gnn_scores", {"invoice_id"})
    score_index = _index(score_rows, "invoice_id") if score_info["available"] else {}
    score_columns = {column for row in score_rows for column in row}
    score_missing = sorted({"gnn_risk_score", "gnn_prediction"} - score_columns)
    availability["gnn_scores"] = {
        **score_info,
        "complete": score_info["available"] and not score_missing,
        "missing_optional_columns": score_missing,
    }

    rag_rows, rag_info = _load_table(root, "rag_similarity_scores", {"invoice_id", "vendor_id"})
    rag_index = _index(rag_rows, "invoice_id") if rag_info["available"] else {}
    rag_columns = {column for row in rag_rows for column in row}
    rag_missing = sorted({"rag_status", "evidence"} - rag_columns)
    availability["rag_findings"] = {
        **rag_info,
        "complete": rag_info["available"] and not rag_missing,
        "missing_optional_columns": rag_missing,
    }

    enriched_invoices: list[dict[str, Any]] = []
    for row in related:
        current_id = row.get("invoice_id", "")
        current_rules = rule_index.get(current_id)
        current_score = score_index.get(current_id)
        current_rag = rag_index.get(current_id)
        rules = None
        if current_rules is not None and rule_columns:
            rules = {key: _bool(value) for key, value in current_rules.items() if key.startswith("rule_")}
        gnn = None
        if current_score is not None and ("gnn_risk_score" in score_columns or "gnn_prediction" in score_columns):
            gnn = {
                "risk_score": current_score.get("gnn_risk_score"),
                "prediction": _bool(current_score.get("gnn_prediction")),
            }
        rag = None
        if current_rag is not None and any(key in rag_columns for key in ("rag_status", "evidence")):
            rag = {
                key: current_rag.get(key)
                for key in ("rag_status", "evidence", "best_match_service", "similarity", "best_match_score", "gap", "margin")
                if key in current_rag
            }
        enriched_invoices.append({"invoice": row, "rule_flags": rules, "gnn": gnn, "contract_rag": rag})

    employees, employee_info = _load_table(root, "employees", {"employee_id", "phone", "email"})
    availability["employees"] = employee_info
    internal_findings = run_internal_vendor_checks(vendor_id, root)

    return {
        "vendor_id": vendor_id,
        "invoice_id": invoice_id,
        "vendor_details": _sanitize_vendor(vendor),
        "related_invoices": enriched_invoices,
        "internal_verification_findings": internal_findings,
        "data_availability": availability,
        "warnings": [
            f"{name}: {info.get('reason') or 'missing columns: ' + ', '.join(info['missing_optional_columns'])}"
            for name, info in availability.items()
            if info.get("reason") or info.get("missing_optional_columns")
        ],
    }
