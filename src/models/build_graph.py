import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch_geometric.transforms as T
from torch_geometric.data import HeteroData

REPO_ROOT = Path(__file__).resolve().parents[2]
REF_DATE = pd.Timestamp("2026-09-30")


def zscore(a):
    a = np.asarray(a, dtype=float)
    return (a - a.mean()) / (a.std() + 1e-9)


def onehot(series, prefix):
    return pd.get_dummies(series.astype(str), prefix=prefix).astype(float)


def build(data_dir):
    d = Path(data_dir)
    emp = pd.read_csv(d / "employees.csv")
    ven = pd.read_csv(d / "vendors.csv")
    po = pd.read_csv(d / "purchase_orders.csv")
    inv = pd.read_csv(d / "invoices.csv")
    con = pd.read_csv(d / "contracts.csv")
    gt = pd.read_csv(d / "ground_truth.csv").fillna("")
    assert list(gt["invoice_id"]) == list(inv["invoice_id"]), "ground_truth rows must align with invoices.csv"
    print(f"Loaded: {len(emp)} employees, {len(ven)} vendors, {len(po)} POs, {len(inv)} invoices, {len(con)} contracts")

    # ------------------------------------------------------------ helper joins
    po_i = po.set_index("po_id")
    ven_i = ven.set_index("vendor_id")
    rate = con.set_index("vendor_id")["agreed_rate"]

    # ------------------------------------------------------------ employees
    emp_basic = pd.concat([onehot(emp["department"], "dept"),
                           emp["role"].str.contains("Manager").astype(float).rename("is_manager")], axis=1)

    # ------------------------------------------------------------ vendors
    created_by_phone = emp.set_index("employee_id")["phone"].reindex(ven["created_by_employee_id"]).values
    ven_age = (REF_DATE - pd.to_datetime(ven["onboarding_date"])).dt.days
    n_pos = po.groupby("vendor_id").size().reindex(ven["vendor_id"]).fillna(0).values
    ven_basic = pd.concat([onehot(ven["vendor_category"], "vcat"),
                           (ven["has_contract"] == "Yes").astype(float).rename("has_contract")], axis=1)
    ven_basic["age_z"] = zscore(np.log1p(ven_age))
    ven_extra = pd.DataFrame({
        "phone_equals_creator": (ven["phone"].values == created_by_phone).astype(float),
        "email_equals_employee": ven["email"].str.lower().isin(set(emp["email"].str.lower())).astype(float).values,
        "n_pos_z": zscore(np.log1p(n_pos)),
    })

    # ------------------------------------------------------------ purchase orders
    onb = pd.to_datetime(po["vendor_id"].map(ven_i["onboarding_date"]))
    days_since_onb = (pd.to_datetime(po["date"]) - onb).dt.days
    same_day = po.groupby(["vendor_id", "date"])["po_id"].transform("count") - 1
    po_dt = pd.to_datetime(po["date"])
    near = np.zeros(len(po))                       # other POs to the same vendor within +-2 days (incl. same day)
    for _, g in po.groupby("vendor_id"):
        dts = po_dt[g.index].values.astype("datetime64[D]").astype(int)
        for k, ix in enumerate(g.index):
            near[ix] = int((np.abs(dts - dts[k]) <= 2).sum() - 1)
    po_basic = pd.concat([onehot(po["item_category"], "pocat")], axis=1)
    po_basic["amount_z"] = zscore(np.log(po["amount"]))
    po_extra = pd.DataFrame({
        "creator_is_approver": (po["created_by_employee_id"] == po["approved_by_employee_id"]).astype(float),
        "days_since_onboarding_z": zscore(np.log1p(days_since_onb.clip(lower=0))),
        "same_day_pos": same_day.clip(upper=3).astype(float),
        "pos_within_2_days": np.clip(near, 0, 3),
        "po_over_15000": (po["amount"] > 15000).astype(float),
    })

    # ------------------------------------------------------------ invoices
    ip = inv.merge(po.rename(columns={"amount": "po_amount", "item_category": "po_category", "date": "po_date"})[
        ["po_id", "vendor_id", "po_amount", "po_category", "po_date"]], on="po_id", how="left")
    ip["rate"] = ip["vendor_id"].map(rate)
    days_after = (pd.to_datetime(ip["date"]) - pd.to_datetime(ip["po_date"])).dt.days
    n_inv_on_po = inv.groupby("po_id")["invoice_id"].transform("count")

    # closeness to a sibling invoice on the same PO (1.0 when there is no sibling)
    sib = np.ones(len(inv))
    for _, g in inv.groupby("po_id"):
        if len(g) > 1:
            amts = g["amount"].values
            for k, ix in enumerate(g.index):
                others = np.delete(amts, k)
                sib[ix] = min(1.0, float(np.min(np.abs(others / amts[k] - 1))))

    inv_basic = pd.concat([onehot(inv["item_category"], "icat"), onehot(inv["payment_status"], "pay")], axis=1)
    inv_basic["amount_z"] = zscore(np.log(inv["amount"]))
    has_rate = ip["rate"].notna()
    inv_extra = pd.DataFrame({
        "amount_over_po": (ip["amount"] / ip["po_amount"]).fillna(1.0).clip(0, 3).values - 1.0,
        "category_matches_po": (ip["item_category"] == ip["po_category"]).astype(float).values,
        "has_rate": has_rate.astype(float).values,
        "amount_over_rate": np.where(has_rate, (ip["amount"] / ip["rate"]).fillna(0).clip(0, 4), 0.0),
        "days_after_po_z": zscore(days_after.fillna(0)),
        "n_invoices_on_po": (n_inv_on_po.values - 1).clip(max=3).astype(float),
        "closeness_to_sibling": 1.0 - sib,           # ~1 => nearly the same amount as another invoice on the PO
    })

    # ------------------------------------------------------------ contracts
    con_basic = pd.DataFrame({"rate_z": zscore(np.log(con["agreed_rate"]))})

    def T_(df):
        return torch.tensor(df.values.astype(np.float32))

    data = HeteroData()
    data["employee"].x_basic = T_(emp_basic); data["employee"].x_full = T_(emp_basic)
    data["vendor"].x_basic = T_(ven_basic); data["vendor"].x_full = T_(pd.concat([ven_basic, ven_extra], axis=1))
    data["purchase_order"].x_basic = T_(po_basic); data["purchase_order"].x_full = T_(pd.concat([po_basic, po_extra], axis=1))
    data["invoice"].x_basic = T_(inv_basic); data["invoice"].x_full = T_(pd.concat([inv_basic, inv_extra], axis=1))
    data["contract"].x_basic = T_(con_basic); data["contract"].x_full = T_(con_basic)
    for nt in data.node_types:                       # default features = full
        data[nt].x = data[nt].x_full

    # ------------------------------------------------------------ labels (TRUE fraud, from the answer key)
    data["invoice"].y = torch.tensor(gt["is_fraud"].values, dtype=torch.long)
    data["invoice"].fraud_type = gt["fraud_type"].tolist()
    data["invoice"].variant = gt["variant"].tolist()
    data["invoice"].case_id = gt["case_id"].tolist()
    data["invoice"].invoice_id = inv["invoice_id"].tolist()

    # ------------------------------------------------------------ edges
    emp_ix = {e: i for i, e in enumerate(emp["employee_id"])}
    ven_ix = {v: i for i, v in enumerate(ven["vendor_id"])}
    po_ix = {p: i for i, p in enumerate(po["po_id"])}

    def edges(src, n_dst):
        return torch.tensor([src, list(range(n_dst))], dtype=torch.long)

    data["employee", "created", "vendor"].edge_index = edges([emp_ix[e] for e in ven["created_by_employee_id"]], len(ven))
    data["employee", "raised", "purchase_order"].edge_index = edges([emp_ix[e] for e in po["created_by_employee_id"]], len(po))
    data["employee", "approved", "purchase_order"].edge_index = edges([emp_ix[e] for e in po["approved_by_employee_id"]], len(po))
    data["vendor", "received", "purchase_order"].edge_index = edges([ven_ix[v] for v in po["vendor_id"]], len(po))
    data["purchase_order", "has_invoice", "invoice"].edge_index = edges([po_ix[p] for p in inv["po_id"]], len(inv))
    data["vendor", "has_contract", "contract"].edge_index = edges([ven_ix[v] for v in con["vendor_id"]], len(con))
    return T.ToUndirected()(data), inv_basic.shape[1], inv_basic.shape[1] + inv_extra.shape[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(REPO_ROOT / "data"))
    ap.add_argument("--out", default=None, help="default: <data>/graph_data.pt")
    a = ap.parse_args()
    data, nb, nf = build(a.data)
    print(data)
    n_fraud = int(data["invoice"].y.sum())
    print(f"\nInvoice features: basic={nb}, full={nf}   fraud invoices (true labels): {n_fraud} of {data['invoice'].num_nodes}")
    out = Path(a.out) if a.out else Path(a.data) / "graph_data.pt"
    torch.save(data, out)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
