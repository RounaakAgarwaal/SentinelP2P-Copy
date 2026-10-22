"""
SentinelP2P - Phase 2 step 3: contract-aware RAG check.

For every invoice whose vendor has a contract, ask: "does what was invoiced match
what the contract says this vendor supplies?"

    python src/rag/contract_rag.py                      # uses all-MiniLM-L6-v2 (needs internet once to download)
    python src/rag/contract_rag.py --margin 0.10
    python src/rag/contract_rag.py --embedder tfidf     # offline fallback (weaker; for a quick logic check only)

Method
  1. Pull the service phrase out of each contract ("... shall provide <service> at an agreed rate ...").
  2. Embed the invoice description and all distinct contract services.
  3. own  = similarity(description, vendor's own contract service)
     best = highest similarity over ALL services
     status = 'ok' if own >= best - margin else 'mismatch'  ("the invoice describes some other kind of work")
     'no_contract_on_file' when the vendor has no contract.
  Relative scoring (own vs best) is used because absolute cosine scores differ a lot between
  services; this was the fix that made v1 work.

Because the generator's normal invoices are consistent with contracts, mismatches are rare and
meaningful.  The script prints a margin sweep and scores the RAG check against the hidden answer
key (it can only ever catch category_mismatch fraud on vendors that have a contract).

Writes data/rag_similarity_scores.csv with the columns the dashboard / agent expect:
invoice_id, vendor_id, contract_text, similarity, best_match_service, best_match_score, rag_status
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_RE = r"(?:provide|supply) (.*?) at an agreed"


def make_embedder(name):
    if name == "minilm":
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return lambda texts: model.encode(list(texts), normalize_embeddings=True)
    from sklearn.feature_extraction.text import TfidfVectorizer
    return lambda texts: None  # replaced below (tfidf needs a shared vocabulary)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(REPO_ROOT / "data"))
    ap.add_argument("--embedder", choices=["minilm", "tfidf"], default="minilm")
    ap.add_argument("--margin", type=float, default=0.10)
    a = ap.parse_args()
    d = Path(a.data)

    inv = pd.read_csv(d / "invoices.csv")
    po = pd.read_csv(d / "purchase_orders.csv")[["po_id", "vendor_id"]]
    con = pd.read_csv(d / "contracts.csv")
    inv = inv.merge(po, on="po_id", how="left")
    con["service"] = con["contract_text"].str.extract(SERVICE_RE)[0]
    by_vendor = con.drop_duplicates("vendor_id").set_index("vendor_id")
    services = sorted(con["service"].dropna().unique())
    descs = sorted(inv["description"].unique())
    print(f"{len(inv)} invoices | {len(services)} contract services | {len(descs)} distinct descriptions | embedder={a.embedder}")

    if a.embedder == "minilm":
        enc = make_embedder("minilm")
        dvec = dict(zip(descs, enc(descs)))
        svec = enc(services)
    else:
        from sklearn.feature_extraction.text import TfidfVectorizer
        tf = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit(descs + services)
        dm, sm = tf.transform(descs).toarray(), tf.transform(services).toarray()
        dvec = dict(zip(descs, dm))
        svec = sm
    sidx = {s: i for i, s in enumerate(services)}

    rows = []
    for _, r in inv.iterrows():
        v = r["vendor_id"]
        if v not in by_vendor.index:
            rows.append({"invoice_id": r["invoice_id"], "vendor_id": v, "contract_text": None, "similarity": np.nan,
                         "best_match_service": None, "best_match_score": np.nan})
            continue
        c = by_vendor.loc[v]
        sims = svec @ dvec[r["description"]]
        rows.append({"invoice_id": r["invoice_id"], "vendor_id": v, "contract_text": c["contract_text"],
                     "similarity": float(sims[sidx[c["service"]]]),
                     "best_match_service": services[int(sims.argmax())], "best_match_score": float(sims.max())})
    df = pd.DataFrame(rows)

    def status(row, margin):
        if pd.isna(row["similarity"]):
            return "no_contract_on_file"
        return "ok" if row["similarity"] >= row["best_match_score"] - margin else "mismatch"

    df["rag_status"] = df.apply(status, axis=1, margin=a.margin)
    df.to_csv(d / "rag_similarity_scores.csv", index=False)
    print(f"\nrag_status (margin={a.margin}):\n{df['rag_status'].value_counts().to_string()}")

    gt_path = d / "ground_truth.csv"
    if gt_path.exists():
        gt = pd.read_csv(gt_path).fillna("")
        m = df.merge(gt, on="invoice_id")
        assess = m["rag_status"] != "no_contract_on_file"
        target = (m["fraud_type"] == "category_mismatch") & assess
        print(f"\nScored against the answer key: {int(assess.sum())} invoices have a contract; "
              f"{int(target.sum())} of them are category-mismatch fraud (the only type RAG can see)")
        print(f"{'margin':>8s}{'flagged':>9s}{'caught':>8s}{'recall':>8s}{'precision':>11s}   other fraud types flagged")
        for mg in (0.02, 0.05, 0.10, 0.15, 0.20, 0.30):
            flag = assess & (m["similarity"] < m["best_match_score"] - mg)
            tp = int((flag & target).sum())
            other = int((flag & ~target & (m["is_fraud"] == 1)).sum())
            prec = tp / flag.sum() if flag.sum() else float("nan")
            rec = tp / target.sum() if target.sum() else float("nan")
            print(f"{mg:8.2f}{int(flag.sum()):9d}{tp:8d}{rec:8.2f}{prec:11.2f}   {other}")
        print("\nPick the margin with high precision (few false alarms on normal invoices); rerun with --margin X.")
    print(f"\nSaved {d / 'rag_similarity_scores.csv'}")


if __name__ == "__main__":
    main()
