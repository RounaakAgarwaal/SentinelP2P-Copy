"""Command-line entry point for creating a local vendor investigation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .workflow import run_vendor_investigation


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run a SentinelP2P vendor investigation workflow")
    parser.add_argument("--vendor-id", required=True)
    parser.add_argument("--invoice-id", default=None)
    parser.add_argument("--data-dir", default=str(repo_root / "data"))
    parser.add_argument("--vendor-csv", default=None, help="Use a separate vendor CSV instead of Faker datasets")
    parser.add_argument("--db", default=str(repo_root / "data" / "investigations.sqlite3"))
    args = parser.parse_args()
    result = run_vendor_investigation(
        args.vendor_id,
        invoice_id=args.invoice_id,
        data_dir=args.data_dir,
        db_path=args.db,
        vendor_csv=args.vendor_csv,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
