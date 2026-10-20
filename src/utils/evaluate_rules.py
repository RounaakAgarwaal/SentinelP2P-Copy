"""
SentinelP2P - score the Phase 1 rules against the hidden answer key.

    python src/utils/evaluate_rules.py                       # data/rule_flags.csv vs data/ground_truth.csv
    python src/utils/evaluate_rules.py --flags data/rule_flags_pandas.csv
    python src/utils/evaluate_rules.py --compare data/rule_flags.csv data/rule_flags_pandas.csv   # Cypher vs pandas

Each rule is matched with the fraud type it was written to catch (RULE_TO_TYPE).
"standard" cases are the textbook pattern; "evasive" cases were built to dodge the
plain rule, so recall on them shows the honest limit of rule-based detection.
"""
import argparse
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]

RULE_TO_TYPE = {
    "rule_shell_vendor": "shell_vendor",
    "rule_split_po": "split_po",
    "rule_duplicate_invoice": "duplicate_invoice",
    "rule_same_creator_approver": "same_creator_approver",
    "rule_new_vendor_high_value": "new_vendor_high_value",
    "rule_contract_rate_mismatch": "contract_rate_mismatch",
    "rule_vendor_employee_email": "vendor_employee_email",
    "rule_category_mismatch": "category_mismatch",
}


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * p * r / (p + r) if p == p and r == r and p + r else float("nan")
    return p, r, f


def compare(a, b):
    fa, fb = pd.read_csv(a).set_index("invoice_id"), pd.read_csv(b).set_index("invoice_id")
    cols = [c for c in RULE_TO_TYPE if c in fa.columns and c in fb.columns]
    ok = True
    for c in cols:
        x, y = fa[c].astype(bool), fb[c].astype(bool).reindex(fa.index)
        diff = x[x != y]
        print(f"{c:30s} {x.sum():4d} vs {y.sum():4d}  {'MATCH' if diff.empty else 'DIFF: ' + ', '.join(diff.index[:10])}")
        ok &= diff.empty
    print("\nALL RULES IDENTICAL" if ok else "\nMISMATCH - check the Cypher query for the rules marked DIFF")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flags", default=str(REPO_ROOT / "data" / "rule_flags.csv"))
    ap.add_argument("--truth", default=str(REPO_ROOT / "data" / "ground_truth.csv"))
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "rule_evaluation.csv"))
    a = ap.parse_args()
    if a.compare:
        return compare(*a.compare)

    fl = pd.read_csv(a.flags)
    gt = pd.read_csv(a.truth).fillna("")
    df = fl.merge(gt, on="invoice_id")
    rules = [c for c in RULE_TO_TYPE if c in df.columns]
    df["any_rule"] = df[rules].astype(bool).any(axis=1)
    truth = df["is_fraud"] == 1

    tp = (df["any_rule"] & truth).sum()
    fp = (df["any_rule"] & ~truth).sum()
    fn = (~df["any_rule"] & truth).sum()
    p, r, f = prf(tp, fp, fn)
    print("=" * 78)
    print(f"OVERALL  invoices={len(df)}  fraud={truth.sum()}  flagged={df['any_rule'].sum()}")
    print(f"         TP={tp} FP={fp} FN={fn}   precision={p:.3f} recall={r:.3f} F1={f:.3f}")

    rows = []
    print("\nPER RULE (rule vs the fraud type it targets)")
    print(f"{'rule':30s}{'flagged':>8s}{'TP':>5s}{'FP':>5s}{'FN':>5s}{'prec':>7s}{'recall':>8s}{'std recall':>12s}{'evasive recall':>16s}")
    for rule, ftype in RULE_TO_TYPE.items():
        if rule not in df.columns:
            continue
        flagged = df[rule].astype(bool)
        is_type = df["fraud_type"] == ftype
        tp, fp, fn = (flagged & is_type).sum(), (flagged & ~is_type).sum(), (~flagged & is_type).sum()
        p, r, _ = prf(tp, fp, fn)

        def rec(variant):
            m = is_type & (df["variant"] == variant)
            return (flagged & m).sum() / m.sum() if m.sum() else float("nan")

        rs, re_ = rec("standard"), rec("evasive")
        rows.append({"rule": rule, "fraud_type": ftype, "flagged": int(flagged.sum()), "tp": int(tp), "fp": int(fp),
                     "fn": int(fn), "precision": p, "recall": r, "recall_standard": rs, "recall_evasive": re_})
        print(f"{rule:30s}{flagged.sum():8d}{tp:5d}{fp:5d}{fn:5d}{p:7.2f}{r:8.2f}{rs:12.2f}{re_:16.2f}")
    pd.DataFrame(rows).to_csv(a.out, index=False)

    print("\nFALSE POSITIVES (flagged by a rule but not planted fraud)")
    fpdf = df[df["any_rule"] & ~truth]
    print("  none" if fpdf.empty else fpdf[["invoice_id"] + rules].to_string(index=False))
    print("\nMISSED FRAUD (planted but no rule fired)")
    miss = df[~df["any_rule"] & truth]
    print("  none" if miss.empty else miss[["invoice_id", "fraud_type", "variant", "case_id"]].to_string(index=False))
    print(f"\nPer-rule table saved to {a.out}")


if __name__ == "__main__":
    main()
