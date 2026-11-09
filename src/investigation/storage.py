"""SQLite persistence for investigations and their evidence records."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _connect(db_path: str | Path):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(db_path: str | Path) -> None:
    """Create the investigation schema if it does not already exist."""
    with _connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS investigations (
                investigation_id TEXT PRIMARY KEY,
                vendor_id TEXT NOT NULL,
                invoice_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_investigations_vendor
                ON investigations(vendor_id, created_at);

            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                investigation_id TEXT NOT NULL,
                check_type TEXT NOT NULL,
                finding TEXT NOT NULL,
                matched_entity TEXT,
                verification_status TEXT NOT NULL,
                source_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                source_url TEXT,
                retrieved_at TEXT,
                FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_investigation
                ON evidence(investigation_id, created_at);
            """
        )
        # Day 1 databases already have an evidence table without provenance columns.
        # Add nullable fields in place so existing rows and investigations remain intact.
        evidence_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(evidence)").fetchall()
        }
        if "source_url" not in evidence_columns:
            connection.execute("ALTER TABLE evidence ADD COLUMN source_url TEXT")
        if "retrieved_at" not in evidence_columns:
            connection.execute("ALTER TABLE evidence ADD COLUMN retrieved_at TEXT")


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def create_investigation(
    db_path: str | Path,
    vendor_id: str,
    invoice_id: str | None = None,
    status: str = "open",
) -> dict[str, Any]:
    if not vendor_id or not vendor_id.strip():
        raise ValueError("vendor_id must be a non-empty string")
    initialize_database(db_path)
    record = {
        "investigation_id": str(uuid.uuid4()),
        "vendor_id": vendor_id.strip(),
        "invoice_id": invoice_id.strip() if invoice_id and invoice_id.strip() else None,
        "status": status,
        "created_at": _now(),
        "completed_at": None,
    }
    with _connect(db_path) as connection:
        connection.execute(
            """INSERT INTO investigations
               (investigation_id, vendor_id, invoice_id, status, created_at, completed_at)
               VALUES (:investigation_id, :vendor_id, :invoice_id, :status, :created_at, :completed_at)""",
            record,
        )
    return record


def get_investigation(db_path: str | Path, investigation_id: str) -> dict[str, Any] | None:
    initialize_database(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM investigations WHERE investigation_id = ?", (investigation_id,)
        ).fetchone()
    return _row_dict(row)


def list_investigations(db_path: str | Path, vendor_id: str | None = None) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with _connect(db_path) as connection:
        if vendor_id is None:
            rows = connection.execute("SELECT * FROM investigations ORDER BY created_at").fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM investigations WHERE vendor_id = ? ORDER BY created_at", (vendor_id,)
            ).fetchall()
    return [dict(row) for row in rows]


def update_investigation(
    db_path: str | Path,
    investigation_id: str,
    *,
    status: str | None = None,
    invoice_id: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any] | None:
    """Update supplied fields; completed/failed/cancelled statuses get a completion time."""
    initialize_database(db_path)
    updates: dict[str, Any] = {}
    if status is not None:
        updates["status"] = status
        if status.lower() in {"completed", "failed", "cancelled"}:
            updates["completed_at"] = completed_at or _now()
        else:
            updates["completed_at"] = completed_at
    elif completed_at is not None:
        updates["completed_at"] = completed_at
    if invoice_id is not None:
        updates["invoice_id"] = invoice_id.strip() or None
    if not updates:
        return get_investigation(db_path, investigation_id)

    assignments = ", ".join(f"{column} = ?" for column in updates)
    with _connect(db_path) as connection:
        cursor = connection.execute(
            f"UPDATE investigations SET {assignments} WHERE investigation_id = ?",
            [*updates.values(), investigation_id],
        )
        if cursor.rowcount == 0:
            return None
    return get_investigation(db_path, investigation_id)


def delete_investigation(db_path: str | Path, investigation_id: str) -> bool:
    initialize_database(db_path)
    with _connect(db_path) as connection:
        cursor = connection.execute(
            "DELETE FROM investigations WHERE investigation_id = ?", (investigation_id,)
        )
    return cursor.rowcount > 0


def create_evidence(
    db_path: str | Path,
    *,
    investigation_id: str,
    check_type: str,
    finding: str,
    matched_entity: dict[str, Any] | None,
    verification_status: str,
    source_type: str,
    created_at: str | None = None,
    source_url: str | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    import json

    initialize_database(db_path)
    record = {
        "evidence_id": str(uuid.uuid4()),
        "investigation_id": investigation_id,
        "check_type": check_type,
        "finding": finding,
        "matched_entity": json.dumps(matched_entity, sort_keys=True) if matched_entity is not None else None,
        "verification_status": verification_status,
        "source_type": source_type,
        "created_at": created_at or _now(),
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    with _connect(db_path) as connection:
        connection.execute(
            """INSERT INTO evidence
               (evidence_id, investigation_id, check_type, finding, matched_entity,
                verification_status, source_type, created_at, source_url, retrieved_at)
               VALUES (:evidence_id, :investigation_id, :check_type, :finding, :matched_entity,
                       :verification_status, :source_type, :created_at, :source_url, :retrieved_at)""",
            record,
        )
    record["matched_entity"] = json.loads(record["matched_entity"]) if record["matched_entity"] else None
    return record


def get_evidence(db_path: str | Path, evidence_id: str) -> dict[str, Any] | None:
    import json

    initialize_database(db_path)
    with _connect(db_path) as connection:
        row = connection.execute("SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)).fetchone()
    record = _row_dict(row)
    if record and record["matched_entity"]:
        record["matched_entity"] = json.loads(record["matched_entity"])
    return record


def list_evidence(db_path: str | Path, investigation_id: str) -> list[dict[str, Any]]:
    import json

    initialize_database(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM evidence WHERE investigation_id = ? ORDER BY created_at, evidence_id",
            (investigation_id,),
        ).fetchall()
    records = [dict(row) for row in rows]
    for record in records:
        if record["matched_entity"]:
            record["matched_entity"] = json.loads(record["matched_entity"])
    return records


def delete_evidence(db_path: str | Path, evidence_id: str) -> bool:
    initialize_database(db_path)
    with _connect(db_path) as connection:
        cursor = connection.execute("DELETE FROM evidence WHERE evidence_id = ?", (evidence_id,))
    return cursor.rowcount > 0
