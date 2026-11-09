"""Command-line entry point for creating a local vendor investigation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .service import start_investigation


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Start an internal SentinelP2P vendor investigation")
    parser.add_argument("--vendor-id", required=True)
    parser.add_argument("--invoice-id", default=None)
    parser.add_argument("--data-dir", default=str(repo_root / "data"))
    parser.add_argument("--db", default=str(repo_root / "data" / "investigations.sqlite3"))
    args = parser.parse_args()
    result = start_investigation(args.vendor_id, args.data_dir, args.db, invoice_id=args.invoice_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
