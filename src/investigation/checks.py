"""Internal vendor identity checks over the existing CSV schemas."""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


MISSING_VALUES = {"", "nan", "none", "null", "n/a", "na", "unknown", "unverified", "pending"}


def _read_csv(path: Path) -> tuple[list[dict[str, str]], set[str]]:
    if not path.is_file():
        return [], set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader), set(reader.fieldnames or [])


def _valid(value: Any) -> bool:
    return value is not None and str(value).strip().lower() not in MISSING_VALUES


def _normalize_phone(value: Any) -> str:
    if not _valid(value):
        return ""
    normalized = re.sub(r"\D", "", str(value))
    return normalized if len(normalized) >= 7 else ""


def _normalize_email(value: Any) -> str:
    if not _valid(value):
        return ""
    normalized = str(value).strip().casefold()
    return normalized if "@" in normalized and not normalized.endswith("@") else ""


def _normalize_identifier(value: Any) -> str:
    if not _valid(value):
        return ""
    normalized = re.sub(r"[^A-Z0-9]", "", str(value).strip().upper())
    placeholders = {"UNKNOWN", "UNVERIFIED", "PENDING", "NA", "NAN",
                   "REGUNKNOWN", "REGUNVERIFIED", "REGPENDING"}
    return normalized if normalized and normalized not in placeholders else ""


def _masked_account(value: str) -> str:
    normalized = _normalize_identifier(value)
    return f"****{normalized[-4:]}" if normalized else "****"


def _finding(
    check_type: str,
    finding: str,
    matched_entity: dict[str, str] | None,
    status: str,
    *,
    coverage_status: str = "complete",
) -> dict[str, Any]:
    return {
        "evidence_id": None,
        "investigation_id": None,
        "check_type": check_type,
        "finding": finding,
        "matched_entity": matched_entity,
        "verification_status": status,
        "coverage_status": coverage_status,
        "source_type": "internal_records",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _vendor_and_rows(vendor_id: str, data_dir: str | Path) -> tuple[dict[str, str], list[dict[str, str]], set[str]]:
    vendors, vendor_columns = _read_csv(Path(data_dir) / "vendors.csv")
    if "vendor_id" not in vendor_columns:
        raise FileNotFoundError(f"vendors.csv is missing its vendor_id column in {data_dir}")
    vendor = next((row for row in vendors if row.get("vendor_id") == vendor_id), None)
    if vendor is None:
        raise ValueError(f"Unknown vendor_id: {vendor_id}")
    return vendor, vendors, vendor_columns


def _match_check(
    vendor_id: str,
    data_dir: str | Path,
    *,
    field: str,
    check_type: str,
    normalizer: Callable[[Any], str],
    compare_employees: bool = False,
    sensitive: bool = False,
) -> list[dict[str, Any]]:
    vendor, vendors, vendor_columns = _vendor_and_rows(vendor_id, data_dir)
    if field not in vendor_columns:
        return [_finding(check_type, f"Check unavailable: vendor data has no {field} field.", None,
                         "unavailable_missing_field", coverage_status="incomplete")]
    target = normalizer(vendor.get(field))
    if not target:
        return [_finding(check_type, f"Check not run: vendor {field} is empty or unusable.", None,
                         "not_run_missing_value")]

    matches: list[dict[str, str]] = []
    for other in vendors:
        other_id = other.get("vendor_id", "")
        if other_id == vendor_id or not other_id:
            continue
        if normalizer(other.get(field)) == target:
            item = {"entity_type": "vendor", "entity_id": other_id}
            if sensitive:
                item["matched_value"] = _masked_account(str(other.get(field, "")))
            matches.append(item)

    coverage_status = "complete"
    if compare_employees:
        employees, employee_columns = _read_csv(Path(data_dir) / "employees.csv")
        if field not in employee_columns:
            coverage_status = "partial"
        else:
            for employee in employees:
                employee_id = employee.get("employee_id", "")
                if employee_id and normalizer(employee.get(field)) == target:
                    matches.append({"entity_type": "employee", "entity_id": employee_id})

    if matches:
        return [
            _finding(
                check_type,
                f"Vendor {field} matches an internal {match['entity_type']} record; this is a lead for review, not proof of fraud."
                + (f" Matched value: {match['matched_value']}." if sensitive else ""),
                match,
                "match_found",
                coverage_status=coverage_status,
            )
            for match in matches
        ]
    status = "no_match" if coverage_status == "complete" else "incomplete_missing_source"
    finding = f"No internal match found for vendor {field}."
    if coverage_status != "complete":
        finding = f"No vendor-record match found for {field}; employee records were unavailable or lacked this field."
    return [_finding(check_type, finding, None, status, coverage_status=coverage_status)]


def check_phone_matches(vendor_id: str, data_dir: str | Path) -> list[dict[str, Any]]:
    """Compare normalized vendor phone against employee and other vendor phones."""
    return _match_check(vendor_id, data_dir, field="phone", check_type="phone_match",
                        normalizer=_normalize_phone, compare_employees=True)


def check_email_matches(vendor_id: str, data_dir: str | Path) -> list[dict[str, Any]]:
    """Compare normalized vendor email against employee and other vendor emails."""
    return _match_check(vendor_id, data_dir, field="email", check_type="email_match",
                        normalizer=_normalize_email, compare_employees=True)


def check_bank_account_matches(vendor_id: str, data_dir: str | Path) -> list[dict[str, Any]]:
    """Find duplicate normalized bank account details across vendors; expose only a mask."""
    return _match_check(vendor_id, data_dir, field="bank_account", check_type="bank_account_match",
                        normalizer=_normalize_identifier, sensitive=True)


def check_registration_number_matches(vendor_id: str, data_dir: str | Path) -> list[dict[str, Any]]:
    """Find duplicate normalized registration identifiers across vendors."""
    return _match_check(vendor_id, data_dir, field="registration_number",
                        check_type="registration_number_match", normalizer=_normalize_identifier)


def run_internal_vendor_checks(vendor_id: str, data_dir: str | Path) -> list[dict[str, Any]]:
    """Run the four independent internal checks and return structured findings."""
    return [
        *check_phone_matches(vendor_id, data_dir),
        *check_email_matches(vendor_id, data_dir),
        *check_bank_account_matches(vendor_id, data_dir),
        *check_registration_number_matches(vendor_id, data_dir),
    ]
