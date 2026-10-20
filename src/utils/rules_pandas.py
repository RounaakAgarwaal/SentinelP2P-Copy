"""
SentinelP2P - the 8 Phase 1 fraud rules implemented in pandas.

Same logic as fraud_checks.py (Cypher). Use it to
  * run Phase 1 without Neo4j, and
  * cross-check the Cypher results:  python evaluate_rules.py --compare data/rule_flags.csv data/rule_flags_pandas.csv

Output: invoice-level flag table (invoice_id + 8 boolean rule_* columns).
"""
import argparse
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
APPROVAL_LIMIT = 15000
RATE_TOLERANCE = 1.3
NEW_VENDOR_DAYS = 7

RULE_COLUMNS = [
    "rule_shell_vendor", "rule_split_po", "rule_duplicate_invoice", "rule_same_creator_approver",
    "rule_new_vendor_high_value", "rule_contract_rate_mismatch", "rule_vendor_employee_email",
    "rule_category_mismatch",
]


def compute_flags(data_dir):
    d = Path(data_dir)
    emp = pd.read_csv(d / "employees.csv")
    ven = pd.read_csv(d / "vendors.csv")
    po = pd.read_csv(d / "purchase_orders.csv")
    inv = pd.read_csv(d / "invoices.csv")
    con = pd.read_csv(d / "contracts.csv")

    inv_po = inv.merge(po.rename(columns={"amount": "po_amount", "item_category": "po_category", "date": "po_date"}),
                       on="po_id", how="left")
    flags = pd.DataFrame({"invoice_id": inv["invoice_id"]})

    def flag(name, invoice_ids):
        flags[name] = flags["invoice_id"].isin(set(invoice_ids))

    # 1 shell vendor: vendor phone == phone of the employee who created the vendor
    m = ven.merge(emp[["employee_id", "phone"]], left_on="created_by_employee_id", right_on="employee_id", suffixes=("", "_emp"))
    shell_vendors = set(m.loc[m["phone"] == m["phone_emp"], "vendor_id"])
    flag("rule_shell_vendor", inv_po.loc[inv_po["vendor_id"].isin(shell_vendors), "invoice_id"])

    # 2 split POs: same vendor, same date, each <= limit, together > limit
    s = po.merge(po, on=["vendor_id", "date"], suffixes=("_1", "_2"))
    s = s[(s["po_id_1"] < s["po_id_2"]) & (s["amount_1"] <= APPROVAL_LIMIT) & (s["amount_2"] <= APPROVAL_LIMIT)
          & (s["amount_1"] + s["amount_2"] > APPROVAL_LIMIT)]
    split_pos = set(s["po_id_1"]) | set(s["po_id_2"])
    flag("rule_split_po", inv.loc[inv["po_id"].isin(split_pos), "invoice_id"])

    # 3 duplicate invoice: a later invoice on the same PO with the same amount (the later one is flagged)
    x = inv.merge(inv, on="po_id", suffixes=("_a", "_b"))
    x = x[(x["amount_a"] == x["amount_b"]) & ((x["date_a"] < x["date_b"]) |
          ((x["date_a"] == x["date_b"]) & (x["invoice_id_a"] < x["invoice_id_b"])))]
    flag("rule_duplicate_invoice", x["invoice_id_b"])

    # 4 same employee created and approved the PO
    same = set(po.loc[po["created_by_employee_id"] == po["approved_by_employee_id"], "po_id"])
    flag("rule_same_creator_approver", inv.loc[inv["po_id"].isin(same), "invoice_id"])

    # 5 new vendor + high value PO within 7 days of onboarding
    n = po.merge(ven[["vendor_id", "onboarding_date"]], on="vendor_id")
    gap = (pd.to_datetime(n["date"]) - pd.to_datetime(n["onboarding_date"])).dt.days
    new_hv = set(n.loc[(gap >= 0) & (gap <= NEW_VENDOR_DAYS) & (n["amount"] > APPROVAL_LIMIT), "po_id"])
    flag("rule_new_vendor_high_value", inv.loc[inv["po_id"].isin(new_hv), "invoice_id"])

    # 6 invoice amount > 1.3 x contract rate
    r = inv_po.merge(con[["vendor_id", "agreed_rate"]], on="vendor_id")
    flag("rule_contract_rate_mismatch", r.loc[r["amount"] > r["agreed_rate"] * RATE_TOLERANCE, "invoice_id"])

    # 7 vendor email == any employee email
    emails = set(emp["email"].str.lower())
    email_vendors = set(ven.loc[ven["email"].str.lower().isin(emails), "vendor_id"])
    flag("rule_vendor_employee_email", inv_po.loc[inv_po["vendor_id"].isin(email_vendors), "invoice_id"])

    # 8 invoice category differs from PO category
    flag("rule_category_mismatch", inv_po.loc[inv_po["item_category"] != inv_po["po_category"], "invoice_id"])

    return flags[["invoice_id"] + RULE_COLUMNS]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(REPO_ROOT / "data"))
    ap.add_argument("--out", default=None, help="default: <data>/rule_flags_pandas.csv")
    a = ap.parse_args()
    out = Path(a.out) if a.out else Path(a.data) / "rule_flags_pandas.csv"
    f = compute_flags(a.data)
    f.to_csv(out, index=False)
    print(f"Wrote {out}")
    print(f[RULE_COLUMNS].sum().to_string())
