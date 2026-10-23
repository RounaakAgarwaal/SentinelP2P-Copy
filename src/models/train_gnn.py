"""
SentinelP2P - Phase 2 step 2: train and honestly evaluate the fraud GNN.

    python src/models/train_gnn.py                       # supervised, full features, 5-fold CV x 3 seeds
    python src/models/train_gnn.py --features basic      # raw attributes only (no relational features)
    python src/models/train_gnn.py --experiment holdout  # also: never show one fraud type, test on it
    python src/models/train_gnn.py --experiment both

How it is evaluated (why the numbers can be trusted)
  * Labels are the TRUE planted fraud (ground_truth.csv), not rule flags.
  * 5-fold cross-validation grouped by fraud case: both invoices of one planted
    case always sit in the same fold, so the model is never tested on a case it
    saw during training.  Every invoice gets an out-of-fold (unseen) score.
  * The decision threshold is picked on a validation slice of the TRAINING folds.
  * Repeated for several random seeds; mean +- std is reported.
  * Compared against the Phase 1 rules on the same invoices, split into
    "standard" cases (textbook pattern) and "evasive" cases (built to dodge the
    plain rules).  That split is the point of Phase 2: does the GNN catch what the
    rules miss, and does it also keep false alarms low?
  * holdout experiment: one fraud type is removed from training and validation
    entirely, then we measure how many of its invoices the GNN still flags
    (does it learn "suspicious" or only memorise known patterns?).

Outputs: data/gnn_scores.csv (invoice_id, gnn_risk_score, gnn_prediction, + out-of-fold marker),
         data/gnn_evaluation.csv, data/gnn_holdout.csv
"""
import argparse
import copy
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score
from sklearn.model_selection import StratifiedGroupKFold
from torch_geometric.nn import HeteroConv, SAGEConv

warnings.filterwarnings("ignore")
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "utils"))
from rules_pandas import RULE_COLUMNS, compute_flags  # noqa: E402

RULE_TO_TYPE = dict(zip(RULE_COLUMNS, ["shell_vendor", "split_po", "duplicate_invoice", "same_creator_approver",
                                       "new_vendor_high_value", "contract_rate_mismatch", "vendor_employee_email",
                                       "category_mismatch"]))


class FraudGNN(torch.nn.Module):
    """Per-type input projection -> 3 rounds of relation-wise SAGEConv (with residuals) -> invoice classifier.
    3 rounds let information travel invoice -> PO -> vendor -> contract (and back)."""

    def __init__(self, in_dims, edge_types, hidden=32, layers=3, dropout=0.3):
        super().__init__()
        self.proj = torch.nn.ModuleDict({nt: torch.nn.Linear(d, hidden) for nt, d in in_dims.items()})
        self.convs = torch.nn.ModuleList([
            HeteroConv({et: SAGEConv((hidden, hidden), hidden) for et in edge_types}, aggr="sum")
            for _ in range(layers)])
        self.out = torch.nn.Linear(hidden, 2)
        self.dropout = dropout

    def forward(self, x_dict, edge_index_dict):
        h = {k: F.relu(self.proj[k](x)) for k, x in x_dict.items()}
        for conv in self.convs:
            new = conv(h, edge_index_dict)
            h = {k: F.dropout(F.relu(new[k]) + h[k], p=self.dropout, training=self.training) if k in new else h[k]
                 for k in h}
        return self.out(h["invoice"])


def best_threshold(y, p):
    grid = np.linspace(0.05, 0.95, 19)
    scores = [f1_score(y, p >= t, zero_division=0) for t in grid]
    best = max(scores)
    ties = [t for t, s in zip(grid, scores) if s >= best - 1e-9]
    return float(np.median(ties)) if best > 0 else 0.5


def train_fold(data, train_idx, val_idx, epochs, hidden, lr, seed):
    torch.manual_seed(seed)
    np.random.seed(seed)
    in_dims = {nt: data[nt].x.shape[1] for nt in data.node_types}
    model = FraudGNN(in_dims, data.edge_types, hidden=hidden)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=5e-4)
    y = data["invoice"].y
    n_pos = int((y[train_idx] == 1).sum())
    n_neg = int((y[train_idx] == 0).sum())
    w = torch.tensor([1.0, min(10.0, n_neg / max(n_pos, 1))])
    tr = torch.as_tensor(train_idx)
    va = torch.as_tensor(val_idx)
    best_state, best_ap = None, -1.0
    for ep in range(1, epochs + 1):
        model.train()
        opt.zero_grad()
        out = model(data.x_dict, data.edge_index_dict)
        F.cross_entropy(out[tr], y[tr], weight=w).backward()
        opt.step()
        if ep % 5 == 0:
            model.eval()
            with torch.no_grad():
                p = F.softmax(model(data.x_dict, data.edge_index_dict), dim=1)[:, 1]
            ap = average_precision_score(y[va].numpy(), p[va].numpy()) if y[va].sum() > 0 else 0.0
            if ap > best_ap:
                best_ap, best_state = ap, copy.deepcopy(model.state_dict())
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        p = F.softmax(model(data.x_dict, data.edge_index_dict), dim=1)[:, 1].numpy()
    return p


def run_cv(data, groups, seed, args, exclude_mask=None):
    """5-fold grouped CV. Returns out-of-fold probability and binary prediction for every invoice."""
    y = data["invoice"].y.numpy()
    n = len(y)
    oof_p, oof_pred = np.zeros(n), np.zeros(n, dtype=int)
    outer = StratifiedGroupKFold(n_splits=args.folds, shuffle=True, random_state=seed)
    for tr_all, te in outer.split(np.zeros(n), y, groups):
        if exclude_mask is not None:                      # held-out fraud type: never seen in training
            tr_all = tr_all[~exclude_mask[tr_all]]
        inner = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed + 1)
        a, b = next(inner.split(np.zeros(len(tr_all)), y[tr_all], groups[tr_all]))
        tr, va = tr_all[a], tr_all[b]
        p = train_fold(data, tr, va, args.epochs, args.hidden, args.lr, seed)
        thr = best_threshold(y[va], p[va])
        oof_p[te] = p[te]
        oof_pred[te] = (p[te] >= thr).astype(int)
    return oof_p, oof_pred


def summarize(y, pred, p):
    return {"precision": precision_score(y, pred, zero_division=0), "recall": recall_score(y, pred, zero_division=0),
            "f1": f1_score(y, pred, zero_division=0), "pr_auc": average_precision_score(y, p)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(REPO_ROOT / "data"))
    ap.add_argument("--features", choices=["full", "basic"], default="full")
    ap.add_argument("--experiment", choices=["supervised", "holdout", "both"], default="supervised")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--epochs", type=int, default=200)
    ap.add_argument("--hidden", type=int, default=32)
    ap.add_argument("--lr", type=float, default=0.01)
    args = ap.parse_args()

    d = Path(args.data)
    data = torch.load(d / "graph_data.pt", weights_only=False)
    for nt in data.node_types:
        data[nt].x = data[nt][f"x_{args.features}"]
    y = data["invoice"].y.numpy()
    ftype = np.array(data["invoice"].fraud_type)
    variant = np.array(data["invoice"].variant)
    case = np.array(data["invoice"].case_id)
    inv_ids = np.array(data["invoice"].invoice_id)
    groups = np.array([c if c else f"clean_{i}" for i, c in enumerate(case)])
    groups = pd.factorize(groups)[0]

    flags = compute_flags(d).set_index("invoice_id").loc[inv_ids]
    rule_any = flags[RULE_COLUMNS].any(axis=1).values.astype(int)
    print(f"Graph: {data['invoice'].num_nodes} invoices, {int(y.sum())} fraud | features={args.features} "
          f"(invoice dim {data['invoice'].x.shape[1]}) | {args.folds}-fold grouped CV x {args.seeds} seeds\n")

    # =============================================================== supervised
    if args.experiment in ("supervised", "both"):
        per_seed, probs, preds = [], [], []
        for s in range(args.seeds):
            p, pr = run_cv(data, groups, 42 + s, args)
            probs.append(p); preds.append(pr)
            per_seed.append(summarize(y, pr, p))
            print(f"  seed {42 + s}: precision={per_seed[-1]['precision']:.2f} recall={per_seed[-1]['recall']:.2f} "
                  f"F1={per_seed[-1]['f1']:.2f} PR-AUC={per_seed[-1]['pr_auc']:.2f}")
        m = pd.DataFrame(per_seed)
        print("\n" + "=" * 78)
        print(f"GNN ({args.features} features), out-of-fold, mean +- std over {args.seeds} seeds")
        for c in m.columns:
            print(f"  {c:10s} {m[c].mean():.3f} +- {m[c].std(ddof=0):.3f}")
        r = summarize(y, rule_any, rule_any)
        print(f"RULES (Phase 1)  precision={r['precision']:.3f} recall={r['recall']:.3f} F1={r['f1']:.3f}")

        avg_p = np.mean(probs, axis=0)
        vote = (np.mean(preds, axis=0) >= 0.5).astype(int)
        gnn_flag_rate = np.mean([pr.mean() for pr in preds])
        rows = []
        print("\nRECALL BY FRAUD TYPE AND VARIANT (share of planted fraud invoices flagged)")
        print(f"{'fraud type':26s}{'variant':10s}{'n':>4s}{'rules':>8s}{'GNN':>8s}{'rules OR GNN':>14s}")
        for ft in sorted(set(ftype) - {""}):
            for var in ("standard", "evasive"):
                m_ = (ftype == ft) & (variant == var)
                if not m_.any():
                    continue
                g = np.mean([pr[m_].mean() for pr in preds])
                rr, comb = rule_any[m_].mean(), np.mean([(np.maximum(pr, rule_any))[m_].mean() for pr in preds])
                rows.append({"fraud_type": ft, "variant": var, "n": int(m_.sum()), "rules_recall": rr,
                             "gnn_recall": g, "combined_recall": comb})
                print(f"{ft:26s}{var:10s}{int(m_.sum()):4d}{rr:8.2f}{g:8.2f}{comb:14.2f}")
        pd.DataFrame(rows).to_csv(d / ("gnn_evaluation.csv" if args.features == "full" else f"gnn_evaluation_{args.features}.csv"), index=False)

        clean = y == 0
        print(f"\nFALSE ALARMS on {int(clean.sum())} legitimate invoices:  rules={int(rule_any[clean].sum())}   "
              f"GNN={np.mean([pr[clean].sum() for pr in preds]):.1f} (avg over seeds)")
        comb_all = [np.maximum(pr, rule_any) for pr in preds]
        cm = np.mean([summarize(y, c, c)["recall"] for c in comb_all]), np.mean([summarize(y, c, c)["precision"] for c in comb_all])
        print(f"RULES OR GNN combined:  recall={cm[0]:.3f} precision={cm[1]:.3f}")

        # only the full-feature model feeds the dashboard; the ablation must not overwrite it
        sc_name = "gnn_scores.csv" if args.features == "full" else f"gnn_scores_{args.features}.csv"
        pd.DataFrame({"invoice_id": inv_ids, "gnn_risk_score": avg_p, "gnn_prediction": vote}).to_csv(
            d / sc_name, index=False)
        print(f"\nSaved out-of-fold scores for all {len(inv_ids)} invoices -> {d / sc_name}")

    # =============================================================== hold-out fraud type
    if args.experiment in ("holdout", "both"):
        print("\n" + "=" * 78)
        print("HOLD-OUT EXPERIMENT: one fraud type is removed from training/validation, then tested")
        print(f"{'held-out type':26s}{'n':>4s}{'rules':>8s}{'GNN recall':>12s}{'GNN false alarms':>18s}")
        rows = []
        for ft in sorted(set(ftype) - {""}):
            mask = ftype == ft
            rec, fa = [], []
            for s in range(args.seeds):
                _, pr = run_cv(data, groups, 42 + s, args, exclude_mask=mask)
                rec.append(pr[mask].mean())
                fa.append(pr[y == 0].sum())
            rows.append({"held_out_type": ft, "n": int(mask.sum()), "rules_recall": rule_any[mask].mean(),
                         "gnn_recall": float(np.mean(rec)), "gnn_false_alarms": float(np.mean(fa))})
            print(f"{ft:26s}{int(mask.sum()):4d}{rule_any[mask].mean():8.2f}{np.mean(rec):12.2f}{np.mean(fa):18.1f}")
        pd.DataFrame(rows).to_csv(d / "gnn_holdout.csv", index=False)
        print("\nReading: high GNN recall on a type it never saw = it learned 'suspicious', not just known patterns.")


if __name__ == "__main__":
    main()