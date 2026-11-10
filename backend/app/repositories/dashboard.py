"""Read-only adapters for existing SentinelP2P dashboard artifacts."""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote


@dataclass(frozen=True)
class CsvTable:
    available: bool
    rows: list[dict[str, str | None]]
    columns: tuple[str, ...]
    reason: str | None = None
    missing_columns: tuple[str, ...] = ()
    modified_at: str | None = None


@dataclass(frozen=True)
class InvestigationData:
    available: bool
    rows: list[dict[str, Any]]
    reason: str | None = None


@lru_cache(maxsize=32)
def _read_csv_cached(path_string: str, modified_ns: int, file_size: int) -> tuple[tuple[str, ...], tuple[dict[str, str | None], ...]]:
    del modified_ns, file_size  # included in the cache key to invalidate on file replacement
    with Path(path_string).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        rows = tuple({key: value for key, value in row.items() if key is not None} for row in reader)
    return columns, rows


class DashboardRepository:
    """Reads committed CSV artifacts and the existing SQLite database without writes."""

    def __init__(self, data_dir: str | Path, investigation_db: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.investigation_db = Path(investigation_db)

    def csv_table(self, filename: str, *, required_columns: set[str] | None = None) -> CsvTable:
        path = self.data_dir / filename
        if not path.is_file():
            return CsvTable(False, [], (), reason="file_missing")
        try:
            stat = path.stat()
            columns, cached_rows = _read_csv_cached(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
            missing = tuple(sorted((required_columns or set()) - set(columns)))
            modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")
            if missing:
                return CsvTable(False, [], columns, reason="missing_required_columns", missing_columns=missing, modified_at=modified_at)
            # Hand out fresh row dicts so service aggregation cannot mutate cached source data.
            return CsvTable(True, [dict(row) for row in cached_rows], columns, modified_at=modified_at)
        except (OSError, csv.Error, UnicodeError):
            return CsvTable(False, [], (), reason="file_unreadable")

    def dashboard_table(self) -> CsvTable:
        return self.csv_table("dashboard_data.csv", required_columns={"invoice_id"})

    def vendors_table(self) -> CsvTable:
        return self.csv_table("vendors.csv", required_columns={"vendor_id", "vendor_name"})

    def purchase_orders_table(self) -> CsvTable:
        return self.csv_table("purchase_orders.csv", required_columns={"po_id", "vendor_id"})

    def audit_log_table(self) -> CsvTable:
        return self.csv_table("audit_log.csv", required_columns={"time", "invoice_id", "vendor_id", "decision"})

    def investigations(self, *, limit: int = 100) -> InvestigationData:
        if not self.investigation_db.is_file():
            return InvestigationData(False, [], "database_missing")
        uri = f"file:{quote(str(self.investigation_db.resolve()))}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=2.0) as connection:
                connection.row_factory = sqlite3.Row
                table = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='investigations'"
                ).fetchone()
                if table is None:
                    return InvestigationData(False, [], "investigation_table_missing")
                columns = {row[1] for row in connection.execute("PRAGMA table_info(investigations)")}
                required = {"investigation_id", "vendor_id", "invoice_id", "status", "created_at", "completed_at"}
                if required - columns:
                    return InvestigationData(False, [], "investigation_schema_incomplete")
                rows = connection.execute(
                    """SELECT investigation_id, vendor_id, invoice_id, status, created_at, completed_at
                       FROM investigations ORDER BY created_at DESC LIMIT ?""",
                    (max(1, min(limit, 1000)),),
                ).fetchall()
            return InvestigationData(True, [dict(row) for row in rows])
        except sqlite3.Error:
            return InvestigationData(False, [], "database_unavailable")

    def freshness(self, tables: list[CsvTable]) -> str | None:
        timestamps = [table.modified_at for table in tables if table.modified_at]
        if not timestamps:
            return None
        return max(timestamps)
