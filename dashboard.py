"""
SentinelP2P - fraud dashboard (Streamlit).

    streamlit run dashboard.py

Needs (in <repo>/data, produced by the pipeline):
    dashboard_data.csv   <- python build_dashboard_data.py   (rules + GNN + RAG per invoice)
    employees.csv vendors.csv purchase_orders.csv invoices.csv contracts.csv
Optional (extra pages light up when present):
    rule_evaluation.csv, gnn_evaluation.csv, gnn_holdout.csv, ground_truth.csv  (model evaluation page)

Pages
  1. Overview            - totals, who caught what, alerts by rule, flagged invoices over time
  2. Review & Inspector  - filter / rank flagged invoices; per-invoice investigation built ONLY from
                           internal evidence (vendor/PO/contract records, rule explanations, GNN score,
                           RAG evidence); auditor decisions are saved to data/audit_log.csv
  3. Contract Search     - semantic search over the contracts + the RAG mismatch list
  4. Model Evaluation    - rules vs GNN vs combined, against the planted-fraud answer key
There is no simulated "external registry" step: nothing here claims to have checked something it did not.
"""
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="SentinelP2P - Fraud Dashboard", layout="wide", initial_sidebar_state="expanded")

DEFAULT_DATA = Path(__file__).resolve().parent / "data"

RULE_INFO = {
    "shell_vendor": "The vendor's phone number is the same as the phone of the employee who created the vendor record.",
    "split_po": "The same vendor received 2+ purchase orders on one day; each is under the approval limit (Rs.15,000) but together they exceed it.",
    "duplicate_invoice": "A later invoice on the same PO has exactly the same amount as an earlier one.",
    "same_creator_approver": "The employee who raised this purchase order also approved it (no segregation of duties).",
    "new_vendor_high_value": "The vendor received a PO above Rs.15,000 within 7 days of being onboarded.",
    "contract_rate_mismatch": "The invoice is more than 30% above the contract's agreed rate.",
    "vendor_employee_email": "The vendor's email address is the same as an employee's email address.",
    "category_mismatch": "The invoice's item category differs from the purchase order's category.",
}


def pretty(col):
    return col.replace("rule_", "").replace("_", " ")


# ----------------------------------------------------------------------------- data
data_dir = Path(st.sidebar.text_input("Data folder", value=str(DEFAULT_DATA)))


@st.cache_data
def load(folder):
    f = Path(folder)
    if not (f / "dashboard_data.csv").exists():
        return None
    t = {n: pd.read_csv(f / f"{n}.csv") for n in ("employees", "vendors", "purchase_orders", "invoices", "contracts")}
    d = pd.read_csv(f / "dashboard_data.csv")
    d["date"] = pd.to_datetime(d["date"])
    d["gnn_risk_score"] = d["gnn_risk_score"].fillna(0.0)
    d["gnn_prediction"] = d["gnn_prediction"].fillna(0).astype(int)
    d["rag_status"] = d["rag_status"].fillna("n/a")
    d["is_flagged"] = (d["overall_status"] == "Flagged").astype(int)
    d = d.merge(t["purchase_orders"][["po_id", "vendor_id"]], on="po_id", how="left")
    for c in [c for c in d.columns if c.startswith("rule_")]:
        d[c] = d[c].astype(bool)
    return d, t


loaded = load(str(data_dir))
if loaded is None:
    st.error(f"`dashboard_data.csv` not found in {data_dir}. Run the pipeline first: "
             "`python src/models/train_gnn.py` then `python build_dashboard_data.py`.")
    st.stop()
df, T = loaded
RULES = [c for c in df.columns if c.startswith("rule_")]

rag_path = data_dir / "rag_similarity_scores.csv"
rag_df = pd.read_csv(rag_path) if rag_path.exists() else pd.DataFrame()
if "evidence" in rag_df.columns:
    df = df.merge(rag_df[["invoice_id", "evidence"]], on="invoice_id", how="left")
else:
    df["evidence"] = ""

st.sidebar.title("SentinelP2P")
st.sidebar.caption("Procure-to-Pay fraud intelligence")
page = st.sidebar.radio("Page", ["Overview", "Review & Inspector", "Contract Search (RAG)", "Model Evaluation"])
st.sidebar.divider()
st.sidebar.caption(f"{len(df)} invoices | {int(df['is_flagged'].sum())} flagged")


# ============================================================================= 1. OVERVIEW
if page == "Overview":
    st.title("Overview")
    st.caption("An invoice is flagged when any rule fires, the GNN predicts fraud, or the contract check (RAG) finds a mismatch.")
    c = st.columns(5)
    c[0].metric("Invoices", len(df))
    c[1].metric("Flagged for review", int(df["is_flagged"].sum()))
    c[2].metric("Rule alerts", int(df[RULES].any(axis=1).sum()))
    c[3].metric("GNN alerts", int((df["gnn_prediction"] == 1).sum()))
    c[4].metric("RAG mismatches", int((df["rag_status"] == "mismatch").sum()))

    left, right = st.columns(2)
    with left:
        st.subheader("Who caught what")
        r, g, m = df[RULES].any(axis=1), df["gnn_prediction"] == 1, df["rag_status"] == "mismatch"
        who = pd.DataFrame({"Invoices": {
            "Rules only": int((r & ~g & ~m).sum()), "GNN only": int((~r & g & ~m).sum()),
            "RAG only": int((~r & ~g & m).sum()), "Rules + GNN": int((r & g).sum()),
            "Not flagged": int((~r & ~g & ~m).sum())}})
        st.bar_chart(who)
    with right:
        st.subheader("Alerts by rule")
        st.bar_chart(pd.DataFrame({"Invoices": {pretty(c_): int(df[c_].sum()) for c_ in RULES}}))

    st.subheader("Flagged invoices over time")
    ts = df.assign(month=df["date"].dt.to_period("M").dt.to_timestamp()).groupby("month")["is_flagged"].sum()
    st.line_chart(ts.rename("Flagged invoices"))
    st.subheader("Highest-risk invoices")
    top = df.sort_values(["is_flagged", "gnn_risk_score"], ascending=False).head(10)
    st.dataframe(top[["invoice_id", "vendor_id", "amount", "description", "overall_status", "gnn_risk_score", "rag_status"]],
                 hide_index=True,
                 column_config={"amount": st.column_config.NumberColumn("Amount", format="Rs.%.2f"),
                                "gnn_risk_score": st.column_config.ProgressColumn("GNN risk", min_value=0, max_value=1, format="%.2f")})


# ============================================================================= 2. REVIEW & INSPECTOR
elif page == "Review & Inspector":
    st.title("Review & Inspector")
    f1, f2, f3 = st.columns([1, 2, 1])
    status = f1.multiselect("Status", sorted(df["overall_status"].unique()), default=["Flagged"])
    methods = f2.multiselect("Detected by (all selected)", ["GNN", "RAG mismatch"] + [pretty(c) for c in RULES])
    min_risk = f3.slider("Min GNN risk", 0.0, 1.0, 0.0, 0.05)

    view = df[df["overall_status"].isin(status)] if status else df
    for mth in methods:
        view = view[view["gnn_prediction"] == 1] if mth == "GNN" else \
               view[view["rag_status"] == "mismatch"] if mth == "RAG mismatch" else \
               view[view["rule_" + mth.replace(" ", "_")]]
    view = view[view["gnn_risk_score"] >= min_risk].sort_values(["num_rules_flagged", "gnn_risk_score"], ascending=False)

    st.subheader(f"{len(view)} invoices")
    st.dataframe(view[["invoice_id", "vendor_id", "amount", "description", "date", "overall_status", "num_rules_flagged",
                       "gnn_risk_score", "rag_status"]],
                 hide_index=True,
                 column_config={"amount": st.column_config.NumberColumn("Amount", format="Rs.%.2f"),
                                "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                                "gnn_risk_score": st.column_config.ProgressColumn("GNN risk", min_value=0, max_value=1, format="%.2f")})
    if view.empty:
        st.info("No invoices match the filters.")
        st.stop()

    st.divider()
    st.subheader("Invoice investigation")
    inv_id = st.selectbox("Invoice", view["invoice_id"].tolist())
    row = df[df["invoice_id"] == inv_id].iloc[0]
    po = T["purchase_orders"].set_index("po_id").loc[row["po_id"]]
    ven = T["vendors"].set_index("vendor_id").loc[row["vendor_id"]]
    emp = T["employees"].set_index("employee_id")
    con = T["contracts"][T["contracts"]["vendor_id"] == row["vendor_id"]]

    a, b = st.columns(2)
    with a:
        with st.container(border=True):
            st.markdown("**Invoice**")
            st.write(f"{inv_id} | Rs.{row['amount']:,.2f} | {row['item_category']} | {row['date']:%d %b %Y} | {row['payment_status']}")
            st.write(f"Description: *{row['description']}*")
            st.write(f"Purchase order {row['po_id']}: Rs.{po['amount']:,.2f}, {po['item_category']}, {po['date']}, {po['payment_terms']}")
            st.write(f"Raised by {emp.loc[po['created_by_employee_id'], 'name']} ({po['created_by_employee_id']}), "
                     f"approved by {emp.loc[po['approved_by_employee_id'], 'name']} ({po['approved_by_employee_id']})")
        with st.container(border=True):
            st.markdown("**Vendor**")
            st.write(f"{ven['vendor_name']} ({row['vendor_id']}) | {ven['vendor_category']} | onboarded {ven['onboarding_date']}")
            st.write(f"Created by {emp.loc[ven['created_by_employee_id'], 'name']} ({ven['created_by_employee_id']})")
            st.write(f"Phone {ven['phone']} | Email {ven['email']}")
            same_phone = T["employees"][T["employees"]["phone"] == ven["phone"]]
            same_email = T["employees"][T["employees"]["email"].str.lower() == str(ven["email"]).lower()]
            for e in same_phone.itertuples():
                st.warning(f"Vendor phone equals employee {e.name} ({e.employee_id})")
            for e in same_email.itertuples():
                st.warning(f"Vendor email equals employee {e.name} ({e.employee_id})")
            vp = T["purchase_orders"][T["purchase_orders"]["vendor_id"] == row["vendor_id"]]
            st.write(f"This vendor has {len(vp)} purchase orders totalling Rs.{vp['amount'].sum():,.0f}.")
            if con.empty:
                st.write("No contract on file.")
            for c_ in con.itertuples():
                st.write(f"Contract {c_.contract_id}: {c_.contract_text}")
    with b:
        with st.container(border=True):
            st.markdown("**Why it was flagged**")
            fired = [c_ for c_ in RULES if row[c_]]
            for c_ in fired:
                st.error(f"**{pretty(c_)}** - {RULE_INFO.get(c_.replace('rule_', ''), '')}")
            if row["gnn_prediction"] == 1:
                st.warning(f"GNN predicts fraud (risk {row['gnn_risk_score']:.0%}). The GNN looks at the invoice together with "
                           "its PO, vendor, employees and contract.")
            if row["rag_status"] == "mismatch":
                st.warning(f"Contract check (RAG): {row['evidence']}")
            if not fired and row["gnn_prediction"] != 1 and row["rag_status"] != "mismatch":
                st.success("No rule, GNN or contract check flagged this invoice.")
            st.caption(f"GNN risk score {row['gnn_risk_score']:.1%} | contract check: {row['rag_status']}")

        with st.container(border=True):
            st.markdown("**Auditor decision**")
            log_path = data_dir / "audit_log.csv"
            with st.form(f"decision_{inv_id}"):
                decision = st.radio("Decision", ["Escalate / block vendor", "Hold for more information", "Release payment"])
                note = st.text_input("Note (optional)")
                if st.form_submit_button("Save decision"):
                    rec = pd.DataFrame([{"time": datetime.now().isoformat(timespec="seconds"), "invoice_id": inv_id,
                                         "vendor_id": row["vendor_id"], "decision": decision, "note": note}])
                    rec.to_csv(log_path, mode="a", header=not log_path.exists(), index=False)
                    st.success(f"Saved to {log_path.name}")
            if log_path.exists():
                past = pd.read_csv(log_path)
                past = past[past["invoice_id"] == inv_id]
                if len(past):
                    st.caption("Earlier decisions for this invoice")
                    st.dataframe(past, hide_index=True)


# ============================================================================= 3. CONTRACT SEARCH
elif page == "Contract Search (RAG)":
    st.title("Contract Search & Scope Check")
    st.caption("Search the contracts by meaning, and see invoices whose description does not match what the vendor's contract covers.")

    @st.cache_resource
    def build_search(contract_texts):
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2")
            vecs = model.encode(list(contract_texts), normalize_embeddings=True)
            return (lambda q: model.encode([q], normalize_embeddings=True)[0]), np.asarray(vecs), "MiniLM"
        except Exception:
            from sklearn.feature_extraction.text import TfidfVectorizer
            tf = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit(list(contract_texts))
            return (lambda q: tf.transform([q]).toarray()[0]), tf.transform(list(contract_texts)).toarray(), "TF-IDF (fallback)"

    contracts = T["contracts"]
    enc, mat, kind = build_search(tuple(contracts["contract_text"]))
    q = st.text_input("Search contracts", placeholder="e.g. which contract covers catering services?")
    if q:
        sims = mat @ enc(q)
        top = np.argsort(-sims)[:8]
        st.caption(f"Ranked by meaning ({kind}); score = similarity, higher is closer.")
        for i in top:
            c_ = contracts.iloc[i]
            with st.container(border=True):
                st.markdown(f"**{c_['contract_id']}** - vendor {c_['vendor_id']} - score {sims[i]:.2f}")
                st.write(c_["contract_text"])

    st.divider()
    st.subheader("Invoices that do not match their contract")
    mm = df[df["rag_status"] == "mismatch"]
    st.write(f"{len(mm)} mismatches; contract-status breakdown:")
    st.dataframe(df["rag_status"].value_counts().rename_axis("Status").reset_index(name="Invoices"), hide_index=True)
    if len(mm):
        st.dataframe(mm[["invoice_id", "vendor_id", "description", "evidence"]], hide_index=True)


# ============================================================================= 4. MODEL EVALUATION
else:
    st.title("Model Evaluation")
    gt_path = data_dir / "ground_truth.csv"
    if not gt_path.exists():
        st.info("`ground_truth.csv` (the planted-fraud answer key) was not found, so there is nothing to score against.")
        st.stop()
    st.caption("Scored against the hidden answer key written by the data generator. The key is never used by the detectors.")
    gt = pd.read_csv(gt_path).fillna("")
    m = df.merge(gt, on="invoice_id")
    y = m["is_fraud"] == 1

    def prf(flag):
        tp, fp, fn = int((flag & y).sum()), int((flag & ~y).sum()), int((~flag & y).sum())
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        return {"Flagged": int(flag.sum()), "True positives": tp, "False alarms": fp, "Missed": fn,
                "Precision": round(p, 3), "Recall": round(r, 3), "F1": round(2 * p * r / (p + r), 3) if p + r else 0.0}

    rules_f = m[RULES].any(axis=1)
    gnn_f = m["gnn_prediction"] == 1
    rag_f = m["rag_status"] == "mismatch"
    table = pd.DataFrame({"Rules (Phase 1)": prf(rules_f), "GNN": prf(gnn_f), "RAG (contract)": prf(rag_f),
                          "Rules + GNN + RAG": prf(rules_f | gnn_f | rag_f)}).T
    st.subheader("Overall")
    st.dataframe(table)
    st.caption("The GNN scores are out-of-fold (each invoice scored by a model that never saw its fraud case). "
               "RAG only looks at description-vs-contract, so low recall on other fraud types is expected.")

    st.subheader("Recall by fraud type")
    rows = []
    for ft in sorted(set(m["fraud_type"]) - {""}):
        for var in ("standard", "evasive"):
            s = (m["fraud_type"] == ft) & (m["variant"] == var)
            if s.any():
                rows.append({"Fraud type": ft, "Variant": var, "Cases (invoices)": int(s.sum()),
                             "Rules": round(rules_f[s].mean(), 2), "GNN": round(gnn_f[s].mean(), 2),
                             "RAG": round(rag_f[s].mean(), 2), "Any": round((rules_f | gnn_f | rag_f)[s].mean(), 2)})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.caption("'Evasive' cases were built to dodge the plain rules (e.g. split POs a day apart, inflated rate just under the threshold).")

    ho = data_dir / "gnn_holdout.csv"
    if ho.exists():
        st.subheader("GNN on a fraud type it never saw in training")
        st.dataframe(pd.read_csv(ho), hide_index=True)
        st.caption("Low recall here means the GNN mostly learns known patterns; it complements the rules but does not replace them.")