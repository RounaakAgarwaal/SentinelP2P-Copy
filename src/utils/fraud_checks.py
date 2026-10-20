"""
SentinelP2P - Phase 1 rule-based fraud detection (8 Cypher rules).

    python src/utils/fraud_checks.py                 # run on Neo4j, print findings, write data/rule_flags.csv
    python src/utils/fraud_checks.py --out my.csv

Every rule returns INVOICE ids, so the output is one row per invoice with 8 boolean
rule_* columns (the same shape the dashboard / GNN / agent code consume). Vendor-
and PO-level rules flag every invoice that belongs to the suspicious vendor / PO.

Thresholds (keep in sync with generate_dataset.py / rules_pandas.py):
    APPROVAL_LIMIT = 15000   RATE_TOLERANCE = 1.3   NEW_VENDOR_DAYS = 7
"""
import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parents[2]
PARAMS = {"limit": 15000, "tolerance": 1.3, "new_days": 7}

RULES = {
    "rule_shell_vendor": (
        "Shell vendor: vendor phone equals the phone of the employee who created it",
        """
        MATCH (e:Employee)-[:CREATED]->(v:Vendor)
        WHERE e.phone = v.phone
        MATCH (v)-[:RECEIVED]->(:PurchaseOrder)-[:HAS_INVOICE]->(i:Invoice)
        RETURN DISTINCT i.invoice_id AS invoice_id"""),
    "rule_split_po": (
        "Split POs: same vendor, same day, each under the approval limit but together over it",
        """
        MATCH (v:Vendor)-[:RECEIVED]->(p1:PurchaseOrder), (v)-[:RECEIVED]->(p2:PurchaseOrder)
        WHERE p1.po_id < p2.po_id AND p1.date = p2.date
          AND p1.amount <= $limit AND p2.amount <= $limit AND p1.amount + p2.amount > $limit
        UNWIND [p1, p2] AS po
        MATCH (po)-[:HAS_INVOICE]->(i:Invoice)
        RETURN DISTINCT i.invoice_id AS invoice_id"""),
    "rule_duplicate_invoice": (
        "Duplicate invoice: a later invoice on the same PO with exactly the same amount",
        """
        MATCH (po:PurchaseOrder)-[:HAS_INVOICE]->(a:Invoice), (po)-[:HAS_INVOICE]->(b:Invoice)
        WHERE a.invoice_id <> b.invoice_id AND a.amount = b.amount
          AND (a.date < b.date OR (a.date = b.date AND a.invoice_id < b.invoice_id))
        RETURN DISTINCT b.invoice_id AS invoice_id"""),
    "rule_same_creator_approver": (
        "Segregation of duties: same employee raised and approved the PO",
        """
        MATCH (e:Employee)-[:RAISED]->(po:PurchaseOrder), (e)-[:APPROVED]->(po)
        MATCH (po)-[:HAS_INVOICE]->(i:Invoice)
        RETURN DISTINCT i.invoice_id AS invoice_id"""),
    "rule_new_vendor_high_value": (
        "New vendor + high-value PO within 7 days of onboarding",
        """
        MATCH (v:Vendor)-[:RECEIVED]->(po:PurchaseOrder)
        WHERE date(po.date) >= date(v.onboarding_date)
          AND date(po.date) <= date(v.onboarding_date) + duration({days: $new_days})
          AND po.amount > $limit
        MATCH (po)-[:HAS_INVOICE]->(i:Invoice)
        RETURN DISTINCT i.invoice_id AS invoice_id"""),
    "rule_contract_rate_mismatch": (
        "Invoice amount exceeds the contract rate by more than 30%",
        """
        MATCH (v:Vendor)-[:HAS_CONTRACT]->(c:Contract)
        MATCH (v)-[:RECEIVED]->(:PurchaseOrder)-[:HAS_INVOICE]->(i:Invoice)
        WHERE i.amount > c.agreed_rate * $tolerance
        RETURN DISTINCT i.invoice_id AS invoice_id"""),
    "rule_vendor_employee_email": (
        "Conflict of interest: vendor email equals an employee email",
        """
        MATCH (v:Vendor), (e:Employee)
        WHERE toLower(v.email) = toLower(e.email)
        MATCH (v)-[:RECEIVED]->(:PurchaseOrder)-[:HAS_INVOICE]->(i:Invoice)
        RETURN DISTINCT i.invoice_id AS invoice_id"""),
    "rule_category_mismatch": (
        "Invoice category differs from the PO category",
        """
        MATCH (po:PurchaseOrder)-[:HAS_INVOICE]->(i:Invoice)
        WHERE po.item_category <> i.item_category
        RETURN DISTINCT i.invoice_id AS invoice_id"""),
}


def run_all_checks(out_path):
    load_dotenv(REPO_ROOT / ".env")
    uri, user, pw = os.getenv("NEO4J_URI"), os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")
    if not (uri and user and pw):
        sys.exit("Set NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD in <repo>/.env")
    driver = GraphDatabase.driver(uri, auth=(user, pw))

    with driver.session() as s:
        invoice_ids = [r["id"] for r in s.run("MATCH (i:Invoice) RETURN i.invoice_id AS id ORDER BY id")]
        flags = pd.DataFrame({"invoice_id": invoice_ids})
        for name, (title, query) in RULES.items():
            hits = {r["invoice_id"] for r in s.execute_read(lambda tx, q=query: list(tx.run(q, **PARAMS)))}
            flags[name] = flags["invoice_id"].isin(hits)
            print(f"{name:30s} {len(hits):4d} invoices   {title}")
    driver.close()

    flags.to_csv(out_path, index=False)
    flagged = flags[list(RULES)].any(axis=1).sum()
    print(f"\n{flagged} of {len(flags)} invoices flagged by at least one rule -> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "rule_flags.csv"))
    run_all_checks(ap.parse_args().out)
