import argparse
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_RE = r"(?:provide|supply) (.*?) (?:at an agreed|at the agreed|for an agreed)"
COLLECTION = "contract_services"


# ----------------------------------------------------------------------------- embedders
def make_embedder(name, corpus):
    if name == "minilm":
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return lambda texts: np.asarray(model.encode(list(texts), normalize_embeddings=True), dtype=float)
    from sklearn.feature_extraction.text import TfidfVectorizer
    tf = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit(list(corpus))
    return lambda texts: tf.transform(list(texts)).toarray()


# ----------------------------------------------------------------------------- vector store
class ContractIndex:
    """Thin wrapper around a Qdrant collection of contract service embeddings."""

    def __init__(self, vectors, payloads, path=None):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
        self.client = QdrantClient(path=path) if path else QdrantClient(":memory:")
        if self.client.collection_exists(COLLECTION):
            self.client.delete_collection(COLLECTION)
        self.client.create_collection(COLLECTION, vectors_config=VectorParams(size=vectors.shape[1], distance=Distance.COSINE))
        self.client.upsert(COLLECTION, points=[PointStruct(id=i, vector=v.tolist(), payload=p)
                                               for i, (v, p) in enumerate(zip(vectors, payloads))])

    def search(self, vec, kind=None, vendor_id=None, services=None, limit=1):
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
        must = []
        if kind:
            must.append(FieldCondition(key="kind", match=MatchValue(value=kind)))
        if vendor_id:
            must.append(FieldCondition(key="vendor_id", match=MatchValue(value=vendor_id)))
        if services:
            must.append(FieldCondition(key="service", match=MatchAny(any=list(services))))
        flt = Filter(must=must) if must else None
        if hasattr(self.client, "query_points"):
            hits = self.client.query_points(COLLECTION, query=vec.tolist(), query_filter=flt, limit=limit, with_payload=True).points
        else:  # older qdrant-client
            hits = self.client.search(COLLECTION, query_vector=vec.tolist(), query_filter=flt, limit=limit, with_payload=True)
        return [(h.score, h.payload) for h in hits]


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * p * r / (p + r) if tp else 0.0
    return p, r, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(REPO_ROOT / "data"))
    ap.add_argument("--embedder", choices=["minilm", "tfidf"], default="minilm")
    ap.add_argument("--margin", type=float, default=None, help="force a margin (default: auto-tune)")
    ap.add_argument("--qdrant-path", default=None, help="folder for an on-disk Qdrant index (default: in memory)")
    ap.add_argument("--profile-share", type=float, default=0.05, help="min share of a service's invoices for a description to join its profile")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    d = Path(a.data)
    rng = random.Random(a.seed)

    inv = pd.read_csv(d / "invoices.csv").merge(pd.read_csv(d / "purchase_orders.csv")[["po_id", "vendor_id"]], on="po_id", how="left")
    con = pd.read_csv(d / "contracts.csv")

    # ---- 1. parse contracts (never silently drop or mislabel)
    con["service"] = con["contract_text"].str.extract(SERVICE_RE)[0].str.strip()
    con["service_source"] = np.where(con["service"].notna(), "parsed", "unparsed")
    con["service"] = con["service"].fillna(con["contract_text"])
    if (con["service_source"] == "unparsed").any():
        print(f"WARNING: {(con['service_source'] == 'unparsed').sum()} contract clause(s) did not match the template; "
              f"their invoices get rag_status='contract_unreadable' (manual review) if no clause of the vendor parses.")
    descs = sorted(inv["description"].unique())
    services = sorted(con["service"].unique())
    print(f"{len(inv)} invoices | {len(con)} contracts / {con['vendor_id'].nunique()} vendors | "
          f"{len(services)} distinct services | {len(descs)} distinct descriptions | embedder={a.embedder}")

    vendor_services = con.groupby("vendor_id")["service"].agg(lambda x: sorted(set(x)))
    own_service = vendor_services.map(lambda x: "; ".join(x))
    n_con = con.groupby("vendor_id").size()
    src = con.groupby("vendor_id")["service_source"].agg(lambda x: "unparsed" if (x == "unparsed").any() else "parsed")
    text_by_vendor = con.groupby("vendor_id")["contract_text"].agg(" || ".join)

    # ---- 2. learn what each service's invoices usually say (label-free "service profiles")
    #      A description joins service S's profile when it appears on >= PROFILE_SHARE of the invoices of vendors
    #      whose contract is S (and >= 3 times).  Real mismatches are rare, so they never reach that share.
    single = inv[inv["vendor_id"].map(n_con).eq(1)].copy()
    single["service"] = single["vendor_id"].map(lambda v: vendor_services[v][0])
    cnt = single.groupby(["service", "description"]).size().rename("n").reset_index()
    cnt["share"] = cnt["n"] / cnt.groupby("service")["n"].transform("sum")
    profile = cnt[(cnt["share"] >= a.profile_share) & (cnt["n"] >= 3)]
    print(f"Service profiles learned from history: {len(profile)} (service, description) pairs "
          f"[share >= {a.profile_share:.0%}, n >= 3]")

    # ---- 3. embed once, index in Qdrant (contract clauses + learned profile descriptions)
    enc = make_embedder(a.embedder, descs + services)
    dvec = dict(zip(descs, enc(descs)))
    svec = dict(zip(services, enc(services)))
    vecs = [svec[x] for x in con["service"]] + [dvec[x] for x in profile["description"]]
    payloads = ([{"kind": "clause", "contract_id": r.contract_id, "vendor_id": r.vendor_id, "service": r.service} for r in con.itertuples()]
                + [{"kind": "profile", "vendor_id": "", "service": r.service, "description": r.description} for r in profile.itertuples()])
    index = ContractIndex(np.array(vecs), payloads, path=a.qdrant_path)

    # ---- 4. retrieval scores (cached per (description, vendor))
    best_cache, own_cache = {}, {}

    def best_for(desc):
        if desc not in best_cache:
            s_, p_ = index.search(dvec[desc], limit=1)[0]
            best_cache[desc] = (s_, p_["service"])
        return best_cache[desc]

    def own_for(desc, vendor):
        key = (desc, vendor)
        if key not in own_cache:
            clause = index.search(dvec[desc], kind="clause", vendor_id=vendor, limit=int(n_con[vendor]))
            prof = index.search(dvec[desc], kind="profile", services=vendor_services[vendor], limit=1)
            own_cache[key] = max([h[0] for h in clause + prof])      # best over the vendor's own clauses and service profile
        return own_cache[key]

    # vendors whose every clause is unparsable cannot be judged by meaning -> flagged for manual review, not "mismatch"
    unreadable = set(con.groupby("vendor_id")["service_source"].agg(lambda x: (x == "unparsed").all()).loc[lambda x: x].index)
    assess = inv[inv["vendor_id"].isin(n_con.index) & ~inv["vendor_id"].isin(unreadable)].copy()
    assess["own"] = [own_for(r.description, r.vendor_id) for r in assess.itertuples()]
    bb = [best_for(x) for x in assess["description"]]
    assess["best"] = [b[0] for b in bb]
    assess["best_service"] = [b[1] for b in bb]
    assess["gap"] = (assess["best"] - assess["own"]).clip(lower=0)

    # ---- 5. auto-tune the margin on a label-free swap test
    # which contract service does each description belong to?  (majority of the vendors that invoice it)
    desc_service = (assess.assign(sv=assess["vendor_id"].map(lambda v: vendor_services[v][0]))
                    .groupby("description")["sv"].agg(lambda x: x.mode().iat[0]))
    pool = [(r.description, r.vendor_id) for r in assess.itertuples()]
    swaps = []
    for r in assess.itertuples():
        for _ in range(10):                                       # a random description of a DIFFERENT service
            other = rng.choice(pool)[0]
            if desc_service[other] not in vendor_services[r.vendor_id]:
                b = best_for(other)
                swaps.append({"vendor_id": r.vendor_id, "true_desc": r.description, "swapped_desc": other,
                              "gap": max(0.0, b[0] - own_for(other, r.vendor_id))})
                break
    sw = pd.DataFrame(swaps)
    grid = np.round(np.arange(0.0, 0.41, 0.01), 2)

    def f1_at(m):
        tp, fn, fp = int((sw["gap"] > m).sum()), int((sw["gap"] <= m).sum()), int((assess["gap"] > m).sum())
        return prf(tp, fp, fn)

    if a.margin is None:
        scores = [f1_at(m)[2] for m in grid]
        best = max(scores)
        margin = float(np.median([m for m, s in zip(grid, scores) if s >= best - 1e-9]))
        print(f"\nMargin auto-tuned on {len(sw)} synthetic description swaps vs {len(assess)} untouched invoices: {margin:.2f}")
    else:
        margin = a.margin
        print(f"\nMargin forced to {margin:.2f}")
    (d / "rag_config.json").write_text(json.dumps({"margin": margin, "embedder": a.embedder, "seed": a.seed}, indent=2))

    # ---- 6. final statuses + evidence
    inv["n_contracts"] = inv["vendor_id"].map(n_con)
    inv = inv.merge(assess[["invoice_id", "own", "best", "best_service", "gap"]], on="invoice_id", how="left")
    inv["rag_status"] = np.where(inv["vendor_id"].isin(unreadable), "contract_unreadable",
                         np.where(inv["own"].isna(), "no_contract_on_file", np.where(inv["gap"] > margin, "mismatch", "ok")))
    inv["contract_text"] = inv["vendor_id"].map(text_by_vendor)
    inv["service_source"] = inv["vendor_id"].map(src)
    inv["margin"] = margin
    inv["evidence"] = np.where(inv["rag_status"] == "mismatch",
                               "Invoice reads like '" + inv["best_service"].fillna("") + "' but the contract covers '" +
                               inv["vendor_id"].map(own_service).fillna("") + "' (gap " + inv["gap"].round(2).astype(str) + ")", "")
    out = inv.rename(columns={"own": "similarity", "best": "best_match_score", "best_service": "best_match_service"})
    out[["invoice_id", "vendor_id", "contract_text", "similarity", "best_match_service", "best_match_score", "rag_status",
         "margin", "gap", "n_contracts", "service_source", "evidence"]].to_csv(d / "rag_similarity_scores.csv", index=False)
    print(f"\nrag_status:\n{out['rag_status'].value_counts().to_string()}")

    # ---- 7. evaluation
    p, r, f = f1_at(margin)
    print("\n" + "=" * 78)
    print("A) SWAP TEST (synthetic mismatches; used for tuning, so slightly optimistic)")
    print(f"   positives={len(sw)}  negatives={len(assess)}   precision={p:.3f} recall={r:.3f} F1={f:.3f}")
    sw["caught"] = sw["gap"] > margin
    sw["true_service"] = sw["vendor_id"].map(own_service)
    pair = sw.groupby(["true_service", "swapped_desc"])["caught"].agg(["mean", "size"]).reset_index()
    pair = pair[pair["size"] >= 3].sort_values("mean").head(5)
    if len(pair):
        print("   hardest look-alike pairs (contract service vs wrongly-invoiced description -> recall):")
        for x in pair.itertuples():
            print(f"     {x.true_service[:38]:38s} <- {x.swapped_desc[:34]:34s} {x.mean:.2f} (n={x.size})")

    gt_path = d / "ground_truth.csv"
    if gt_path.exists():
        gt = pd.read_csv(gt_path).fillna("")
        m = out.merge(gt, on="invoice_id")
        ass = ~m["rag_status"].isin(["no_contract_on_file", "contract_unreadable"])
        target = ass & (m["fraud_type"] == "category_mismatch")
        flag = ass & (m["rag_status"] == "mismatch")
        tp, fp = int((flag & target).sum()), int((flag & ~target).sum())
        fn = int((target & ~flag).sum())
        p, r, f = prf(tp, fp, fn)
        print("\nB) REAL PLANTED FRAUD (hidden answer key; never used for tuning)")
        print(f"   invoices with a contract: {int(ass.sum())} | planted category-mismatch frauds among them: {int(target.sum())}")
        print(f"   flagged={int(flag.sum())}  caught={tp}  false alarms on legitimate invoices={int((flag & (m['is_fraud'] == 0)).sum())}  "
              f"other-type fraud flagged={int((flag & ~target & (m['is_fraud'] == 1)).sum())}")
        print(f"   precision={p:.3f} recall={r:.3f} F1={f:.3f}   (n is small: {int(target.sum())} positives)")
        fpr = m[flag & (m["is_fraud"] == 0)][["invoice_id", "description", "best_match_service", "gap"]]
        if len(fpr):
            print("   false alarms:\n" + fpr.head(10).to_string(index=False))
        miss = m[target & ~flag][["invoice_id", "description", "gap"]]
        if len(miss):
            print("   missed:\n" + miss.to_string(index=False))

    print("\nMargin sweep on the swap test (precision / recall / F1):")
    for mg in (0.02, 0.05, 0.10, 0.15, 0.20, 0.30):
        pp, rr, ff = f1_at(mg)
        print(f"   margin {mg:.2f}: {pp:.2f} / {rr:.2f} / {ff:.2f}")
    print(f"\nSaved {d / 'rag_similarity_scores.csv'} and {d / 'rag_config.json'}")


if __name__ == "__main__":
    main()
