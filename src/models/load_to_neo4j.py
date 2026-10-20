"""
SentinelP2P - load the Phase 1 CSVs into Neo4j.

    python src/models/load_to_neo4j.py                 # reads <repo>/data
    python src/models/load_to_neo4j.py --data data_seed7

Needs a .env file in the repo root:
    NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io   (or bolt://localhost:7687)
    NEO4J_USER=neo4j
    NEO4J_PASSWORD=...

Graph schema (unchanged, so build_graph.py / RAG / agent code keep working):
    (Employee)-[:CREATED]->(Vendor)        (Employee)-[:RAISED]->(PurchaseOrder)
    (Employee)-[:APPROVED]->(PurchaseOrder) (Vendor)-[:RECEIVED]->(PurchaseOrder)
    (PurchaseOrder)-[:HAS_INVOICE]->(Invoice) (Employee)-[:SUBMITTED]->(Invoice)
    (Vendor)-[:HAS_CONTRACT]->(Contract)

Improvements over v1: uniqueness constraints (fast MATCH + no duplicate nodes),
batched writes, --data option, and a verification step that compares what is in
Neo4j with the CSV row counts (v1 silently dropped rows whose MATCH failed).
ground_truth*.csv is deliberately NOT loaded.
"""
import argparse
import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parents[2]
BATCH = 500

CONSTRAINTS = [
    "CREATE CONSTRAINT employee_id IF NOT EXISTS FOR (n:Employee) REQUIRE n.employee_id IS UNIQUE",
    "CREATE CONSTRAINT vendor_id IF NOT EXISTS FOR (n:Vendor) REQUIRE n.vendor_id IS UNIQUE",
    "CREATE CONSTRAINT po_id IF NOT EXISTS FOR (n:PurchaseOrder) REQUIRE n.po_id IS UNIQUE",
    "CREATE CONSTRAINT invoice_id IF NOT EXISTS FOR (n:Invoice) REQUIRE n.invoice_id IS UNIQUE",
    "CREATE CONSTRAINT contract_id IF NOT EXISTS FOR (n:Contract) REQUIRE n.contract_id IS UNIQUE",
]
INDEXES = [
    "CREATE INDEX employee_email IF NOT EXISTS FOR (n:Employee) ON (n.email)",
    "CREATE INDEX vendor_email IF NOT EXISTS FOR (n:Vendor) ON (n.email)",
]

Q_EMPLOYEES = """
UNWIND $rows AS row
CREATE (:Employee {employee_id: row.employee_id, name: row.name, email: row.email, phone: row.phone,
                   department: row.department, role: row.role, join_date: row.join_date})"""

Q_VENDORS = """
UNWIND $rows AS row
CREATE (v:Vendor {vendor_id: row.vendor_id, vendor_name: row.vendor_name, email: row.email, phone: row.phone,
                  address: row.address, bank_account: row.bank_account, registration_number: row.registration_number,
                  vendor_category: row.vendor_category, onboarding_date: row.onboarding_date, has_contract: row.has_contract})
WITH v, row
MATCH (e:Employee {employee_id: row.created_by_employee_id})
CREATE (e)-[:CREATED]->(v)"""

Q_POS = """
UNWIND $rows AS row
CREATE (po:PurchaseOrder {po_id: row.po_id, amount: toFloat(row.amount), item_category: row.item_category,
                          date: row.date, payment_terms: row.payment_terms})
WITH po, row
MATCH (creator:Employee {employee_id: row.created_by_employee_id})
MATCH (approver:Employee {employee_id: row.approved_by_employee_id})
MATCH (v:Vendor {vendor_id: row.vendor_id})
CREATE (creator)-[:RAISED]->(po)
CREATE (approver)-[:APPROVED]->(po)
CREATE (v)-[:RECEIVED]->(po)"""

Q_INVOICES = """
UNWIND $rows AS row
CREATE (inv:Invoice {invoice_id: row.invoice_id, amount: toFloat(row.amount), item_category: row.item_category,
                     description: row.description, date: row.date, payment_status: row.payment_status})
WITH inv, row
MATCH (po:PurchaseOrder {po_id: row.po_id})
MATCH (s:Employee {employee_id: row.submitted_by_employee_id})
CREATE (po)-[:HAS_INVOICE]->(inv)
CREATE (s)-[:SUBMITTED]->(inv)"""

Q_CONTRACTS = """
UNWIND $rows AS row
CREATE (c:Contract {contract_id: row.contract_id, contract_text: row.contract_text,
                    agreed_rate: toFloat(row.agreed_rate), start_date: row.start_date, end_date: row.end_date})
WITH c, row
MATCH (v:Vendor {vendor_id: row.vendor_id})
CREATE (v)-[:HAS_CONTRACT]->(c)"""


def read_csv(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def batches(rows):
    for i in range(0, len(rows), BATCH):
        yield rows[i:i + BATCH]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(REPO_ROOT / "data"))
    ap.add_argument("--keep", action="store_true", help="do not wipe the existing graph first")
    a = ap.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    uri, user, pw = os.getenv("NEO4J_URI"), os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")
    if not (uri and user and pw):
        sys.exit("Set NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD in <repo>/.env")

    d = Path(a.data)
    data = {n: read_csv(d / f"{n}.csv") for n in ("employees", "vendors", "purchase_orders", "invoices", "contracts")}
    driver = GraphDatabase.driver(uri, auth=(user, pw))
    driver.verify_connectivity()

    with driver.session() as s:
        if not a.keep:
            s.run("MATCH (n) DETACH DELETE n").consume()
            print("Cleared existing graph")
        for q in CONSTRAINTS + INDEXES:
            s.run(q).consume()

        for label, query, rows in (("Employees", Q_EMPLOYEES, data["employees"]),
                                   ("Vendors", Q_VENDORS, data["vendors"]),
                                   ("PurchaseOrders", Q_POS, data["purchase_orders"]),
                                   ("Invoices", Q_INVOICES, data["invoices"]),
                                   ("Contracts", Q_CONTRACTS, data["contracts"])):
            for chunk in batches(rows):
                s.execute_write(lambda tx, q=query, r=chunk: tx.run(q, rows=r).consume())
            print(f"Loaded {len(rows):5d} {label}")

        # ---------- verification: Neo4j must agree with the CSVs
        n = {r["l"]: r["c"] for r in s.run("MATCH (n) RETURN labels(n)[0] AS l, count(*) AS c")}
        r = {x["t"]: x["c"] for x in s.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c")}
        expected_nodes = {"Employee": len(data["employees"]), "Vendor": len(data["vendors"]),
                          "PurchaseOrder": len(data["purchase_orders"]), "Invoice": len(data["invoices"]),
                          "Contract": len(data["contracts"])}
        expected_rels = {"CREATED": len(data["vendors"]), "RAISED": len(data["purchase_orders"]),
                         "APPROVED": len(data["purchase_orders"]), "RECEIVED": len(data["purchase_orders"]),
                         "HAS_INVOICE": len(data["invoices"]), "SUBMITTED": len(data["invoices"]),
                         "HAS_CONTRACT": len(data["contracts"])}
        bad = [f"node {k}: neo4j={n.get(k, 0)} csv={v}" for k, v in expected_nodes.items() if n.get(k, 0) != v]
        bad += [f"rel {k}: neo4j={r.get(k, 0)} csv={v}" for k, v in expected_rels.items() if r.get(k, 0) != v]
    driver.close()

    print("\nNodes:", n)
    print("Relationships:", r)
    if bad:
        sys.exit("VERIFICATION FAILED (rows were dropped - a foreign key in the CSVs does not resolve):\n  " + "\n  ".join(bad))
    print("\nVerification passed: every CSV row is in the graph with all its relationships.")


if __name__ == "__main__":
    main()
