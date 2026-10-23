import argparse
from pathlib import Path

import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--data", default=str(Path(__file__).resolve().parent / "data"))
d = Path(ap.parse_args().data)

invoices = pd.read_csv(d / "invoices.csv")
rules = pd.read_csv(d / ("rule_flags.csv" if (d / "rule_flags.csv").exists() else "rule_flags_pandas.csv"))
gnn = pd.read_csv(d / "gnn_scores.csv")
rag = pd.read_csv(d / "rag_similarity_scores.csv")
print("Rows -> invoices:", len(invoices), "| rules:", len(rules), "| gnn:", len(gnn), "| rag:", len(rag))

combined = invoices[["invoice_id", "po_id", "amount", "item_category", "description",
                     "date", "payment_status", "submitted_by_employee_id"]].copy()
combined = combined.merge(rules, on="invoice_id", how="left")
combined = combined.merge(gnn, on="invoice_id", how="left")
combined = combined.merge(rag[["invoice_id", "similarity", "rag_status", "best_match_service"]], on="invoice_id", how="left")

rule_cols = [c for c in combined.columns if c.startswith("rule_")]
combined["any_rule_flagged"] = combined[rule_cols].astype(bool).any(axis=1)
combined["num_rules_flagged"] = combined[rule_cols].astype(bool).sum(axis=1)
combined["overall_status"] = (combined["any_rule_flagged"] | (combined["gnn_prediction"] == 1)
                              | (combined["rag_status"] == "mismatch")).map({True: "Flagged", False: "Clear"})
combined.to_csv(d / "dashboard_data.csv", index=False)

print(combined["overall_status"].value_counts())
print(combined["rag_status"].value_counts(dropna=False))
