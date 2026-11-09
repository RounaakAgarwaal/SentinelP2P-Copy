# SentinelP2P project report

Procure-to-pay fraud intelligence: synthetic Indian-enterprise P2P data, eight planted fraud types, rule detectors, a heterogeneous GNN, contract RAG, and a Streamlit investigator UI.

Reconciled against every tracked Python source, the static web page, the generated manifest, and the committed CSV inventory. Snapshot checked on 9 Nov 2026. There is no `requirements.txt`, `pyproject.toml`, or `README.md`; install dependencies manually as described below.

**Current data snapshot:** 644 invoices · 88 planted fraud invoices (13.66%) · 69 planted fraud cases · 8 fraud scheme types. The generated world also contains 100 employees, 304 vendors, 674 purchase orders, and 133 contracts. Counts come from `data/dataset_manifest.json`.

---

## What to re-run for a demo

With the current `data/` folder already filled, launch only Streamlit:

```bash
streamlit run dashboard.py
```

Optionally open `web/index.html` as a pitch page.

Do **not** re-run `generate_dataset.py`, `plant_fraud.py`, `train_gnn.py`, or `contract_rag.py` before a talk — they overwrite artifacts or take minutes to hours. The first visit to Contract Search attempts to load `all-MiniLM-L6-v2`; Streamlit caches the search index for the session and falls back to TF-IDF if the model cannot load.

### Full rebuild (only when intentionally replacing the snapshot)

Run from the repository root in this order. These commands overwrite matching files in `data/`; preserve any local audit log or outputs you need first.

```bash
python src/data_generation/generate_dataset.py
python src/utils/rules_pandas.py
python src/models/build_graph.py
python src/models/train_gnn.py
python src/rag/contract_rag.py
python build_dashboard_data.py
```

For the optional held-out fraud-type experiment, use `python src/models/train_gnn.py --experiment both`; it writes `gnn_holdout.csv` and takes substantially longer. To compare Neo4j and pandas rule outputs, run `python src/utils/evaluate_rules.py --compare data/rule_flags.csv data/rule_flags_pandas.csv`. The dashboard join gives `rule_flags.csv` precedence, so replace or remove an old Neo4j result if you want to use the pandas output.

---

## Execution flow

The normal data flow is one-way. Rule and RAG outputs are built from business records; the GNN uses `ground_truth.csv` for supervised labels, but labels are excluded from its feature vectors. Evaluation reads the answer key only after predictions exist. Grouped outer folds keep each planted `case_id` out of the training labels for its test invoices. This is a transductive graph experiment: the model can access graph structure and input features for all nodes, including outer-fold test invoices, while their labels are withheld.

```
1. generate_dataset.py
        │
        ▼
2. data/*.csv  (employees, vendors, POs, invoices, contracts, ground_truth)
        │
        ├──► 3a. rules_pandas.py ─────────────────────────┐
        ├──► 3b. load_to_neo4j.py → 4. fraud_checks.py ───┤
        ├──► 3c. build_graph.py → 4. train_gnn.py ────────┤
        └──► 3d. contract_rag.py ─────────────────────────┤
                                                          ▼
                                              5. build_dashboard_data.py
                                                          │
                                                          ▼
                                              6. dashboard.py   (demo UI)
```

`web/index.html` is a static marketing page in parallel; it is not fed by the CSVs.

### Stage-by-stage

| Stage | Command | What happens | Re-run for demo? |
|---|---|---|---|
| 0. Env | Python venv + pip | Install libraries below. Create `.env` only if you will show Neo4j. | Once per machine |
| 1. Generate | `python src/data_generation/generate_dataset.py` | Faker builds employees, vendors, POs, invoices, contracts, plus planted fraud and the hidden answer key. Seed 42 is the current snapshot. | No — already in `data/` |
| 2. Rules (pandas) | `python src/utils/rules_pandas.py` | Eight boolean flags per invoice, same logic as Cypher, no database. | No unless CSVs changed |
| 2b. Rules (Neo4j) | `python src/models/load_to_neo4j.py` then `python src/utils/fraud_checks.py` | Optional graph demo path. Writes `rule_flags.csv`. Needs a running Neo4j and `.env`. The loader clears the graph by default; pass `--keep` to skip the clear (only for an empty/compatible database). | Only if showing Neo4j Browser |
| 3. Graph + GNN | `python src/models/build_graph.py` then `train_gnn.py` | HeteroData in `graph_data.pt`, then 5-fold grouped CV × 3 seeds × 200 epochs. Writes `gnn_scores.csv`. | No — slow; scores exist |
| 4. RAG | `python src/rag/contract_rag.py` | MiniLM embeddings in Qdrant, auto-tunes a similarity margin, writes `rag_similarity_scores.csv`. | No unless regenerating |
| 5. Join | `python build_dashboard_data.py` | Merges invoices + rules + GNN + RAG into `dashboard_data.csv` and sets `overall_status` Flagged/Clear. | No unless inputs changed |
| 6. Demo UI | `streamlit run dashboard.py` | Live investigator: Overview, Review, Contract Search, Model Evaluation. Auditor form appends `audit_log.csv`. | **Yes — every demo** |

---

## Data flow

Entities and Neo4j relationships: Employee **CREATED** Vendor; Employee **RAISED** and **APPROVED** PurchaseOrder; Vendor **RECEIVED** PO; PO **HAS_INVOICE** Invoice; Employee **SUBMITTED** Invoice; Vendor **HAS_CONTRACT** Contract. `build_graph.py` uses the corresponding heterogeneous relations and adds reverse edges with PyG's `ToUndirected` transform.

An invoice is **Flagged** if any rule is true, or `gnn_prediction == 1`, or `rag_status == mismatch`.

### Layer A — tabular facts

`employees.csv` (100), `vendors.csv` (304), `purchase_orders.csv` (674), `invoices.csv` (644), `contracts.csv` (133). IDs EMP/VEN/PO/INV/CON. Reference date inside the synthetic world is **2026-09-30**. Approval limit Rs.15,000; rate mismatch if invoice > 1.3× contract rate; new-vendor window 7 days.

### Layer B — hidden labels

`ground_truth.csv` is one row per invoice (`is_fraud`, `fraud_type`, `variant`, `case_id`). `ground_truth_cases.csv` has one row per planted case; a case can span multiple invoices, explaining why 69 cases yield 88 fraud invoices. Never load these files into Neo4j or use their columns as GNN inputs. `build_graph.py` does attach the fraud label `y` and metadata for supervised training and evaluation; only the labels of training invoices contribute to each fold's loss.

### Layer C — three detectors

- **Rules:** 8 booleans in `rule_flags.csv` or `rule_flags_pandas.csv`.
- **GNN:** `gnn_risk_score` in [0,1] and `gnn_prediction` 0/1 from out-of-fold votes.
- **RAG:** embeds parsed contract services and historically observed invoice descriptions; compares a description's best match against the vendor's own clauses/service profile. Mismatch if the nonnegative similarity gap is greater than the configured margin (currently 0.20). Status can also be `ok`, `no_contract_on_file`, or `contract_unreadable`; only `mismatch` contributes to overall Flagged status. This is semantic similarity retrieval, not an LLM generation step.

### Layer D — investigator join

`build_dashboard_data.py` left-joins on `invoice_id`. It prefers `rule_flags.csv` when present, otherwise uses `rule_flags_pandas.csv`. The dashboard reads the five entity CSVs for inspector details (vendor phone/email collisions, PO creator/approver, vendor contracts). Auditor decisions append to `audit_log.csv` with local timestamp, invoice/vendor IDs, decision, and optional note.

### Eight schemes (how a row becomes fraud)

| Type | How it is planted | Rule that targets it | Evasive variant |
|---|---|---|---|
| `shell_vendor` | New vendor; phone equals the employee who created it; two POs under the limit | `rule_shell_vendor` | None (always standard) |
| `split_po` | Two POs same vendor, each ≤15k, sum >15k | `rule_split_po` | POs dated one day apart so same-day rule misses |
| `duplicate_invoice` | Second invoice on same PO, same amount | `rule_duplicate_invoice` | Amount jittered ~0.6–2% so exact-match misses |
| `same_creator_approver` | `created_by_employee_id == approved_by_employee_id` | `rule_same_creator_approver` | None |
| `new_vendor_high_value` | PO >15k within 7 days of onboarding | `rule_new_vendor_high_value` | PO on day 9–14 |
| `contract_rate_mismatch` | Invoice 1.4–2.3× `agreed_rate` | `rule_contract_rate_mismatch` | Inflate only 1.12–1.27× (under 1.3 threshold) |
| `vendor_employee_email` | Vendor email equals some employee, different creator | `rule_vendor_employee_email` | None |
| `category_mismatch` | Invoice category/description swapped vs PO (half on contract vendors so RAG can fire) | `rule_category_mismatch` + RAG | None |

Also 5 benign traps: same-day small POs that sum under the limit, labeled not fraud, so `split_po` precision can be scored.

---

## File by file

Re-run column answers: do I execute this file every time I present?

### Python — generation and models

| File | Does | Reads | Writes | Re-run for demo? |
|---|---|---|---|---|
| `src/data_generation/generate_dataset.py` | Single source of truth for the synthetic world. Plants all 8 fraud types (standard + 25% evasive by default) and writes the answer key. Defaults: 100 employees, 280 clean vendors (+ fraud vendors), 600 clean POs, 8 cases/type, seed 42. | Nothing (Faker only) | employees, vendors, POs, invoices, contracts, `ground_truth*`, `dataset_manifest.json` | **No.** Overwrites the whole dataset; then you must rebuild rules, graph, GNN, RAG, dashboard join. |
| `src/models/plant_fraud.py` | Legacy second-pass planter: appends 15 extra cases per type onto existing CSVs. Hard-coded relative paths `../../data/`. Fraud planting already lives in `generate_dataset.py`. | The five entity CSVs | Overwrites vendors, POs, invoices (no `ground_truth` update) | **Never.** Running it would duplicate fraud, desync the answer key, and break evaluation. |
| `src/models/build_graph.py` | Builds PyG HeteroData with employee/vendor/purchase_order/invoice/contract nodes. Basic features include category/status one-hots and normalized amounts/rates; full features add rule-adjacent values such as phone/email collisions, approval separation, nearby POs, and sibling invoice similarity. Adds reverse edges. Attaches fraud labels for supervised learning. | Five entity CSVs + `ground_truth.csv` | `data/graph_data.pt` | No unless retraining the GNN. |
| `src/models/train_gnn.py` | FraudGNN: per-type Linear projection, 3 HeteroConv SAGE layers with residuals, 2-class invoice head. Outer StratifiedGroupKFold keeps `case_id` groups together; an inner grouped split selects a checkpoint and threshold. Scores are averaged across 3 seeds. Optional holdout experiment trains without one fraud type. | `graph_data.pt` + pandas `compute_flags()` for rule comparison | `gnn_scores.csv`, `gnn_evaluation.csv`, optionally `gnn_holdout.csv` | **No.** This is the slow step (minutes–hours on CPU). |
| `src/models/load_to_neo4j.py` | By default runs `DETACH DELETE`, creates constraints/indexes and nodes/relationships (CREATED, RAISED, APPROVED, RECEIVED, HAS_INVOICE, SUBMITTED, HAS_CONTRACT), then verifies counts against CSVs. `--keep` skips deletion. Does not load `ground_truth`. | Five entity CSVs + `.env` `NEO4J_*` | Neo4j database (destructive replacement by default) | Only if the live demo walks Neo4j Browser. Start Neo4j first. |

### Python — rules, RAG, join, UI

| File | Does | Reads | Writes | Re-run for demo? |
|---|---|---|---|---|
| `src/utils/rules_pandas.py` | Canonical 8-rule implementation in pandas. Also imported by `train_gnn.py` so GNN vs rules comparison uses the same flags. | Five entity CSVs | `rule_flags_pandas.csv` | No. Dashboard join prefers `rule_flags.csv` if present, else this file. |
| `src/utils/fraud_checks.py` | Same 8 rules as Cypher against Neo4j. Parameters `limit=15000`, `tolerance=1.3`, `new_days=7`. | Live Neo4j + `.env` | `rule_flags.csv` (default) | Only with a live Neo4j demo. Otherwise skip; pandas flags already exist. |
| `src/utils/evaluate_rules.py` | Precision/recall vs `ground_truth` per rule and standard vs evasive. Can `--compare` two flag CSVs (Neo4j vs pandas). | `rule_flags.csv` + `ground_truth.csv` | `rule_evaluation.csv` | No. Dashboard Model Evaluation recomputes similar metrics live. |
| `src/rag/contract_rag.py` | Parse services from contract text, learn label-free service profiles from invoice-description history, embed services/descriptions with MiniLM (or TF-IDF), index them in Qdrant, tune a margin on synthetic description swaps, and score invoices. The answer key is used only for its final evaluation output. | invoices, POs, contracts, optional `ground_truth` for evaluation only | `rag_similarity_scores.csv`, `rag_config.json`; optional on-disk Qdrant data with `--qdrant-path` | No. First MiniLM run downloads model weights. |
| `build_dashboard_data.py` | Join invoices + rules + gnn_scores + rag columns; any_rule OR gnn==1 OR rag mismatch ⇒ Flagged. | invoices, `rule_flags*`, `gnn_scores`, `rag_similarity_scores` | `dashboard_data.csv` | No unless you regenerated any detector output. |
| `dashboard.py` | Streamlit app. Pages: Overview (who caught what), Review & Inspector (filters, entity drill-down, auditor form), Contract Search (live MiniLM or TF-IDF fallback), Model Evaluation (vs hidden key + `gnn_holdout`). | `dashboard_data.csv` + entity CSVs + rag evidence + `ground_truth` + `gnn_holdout` | `audit_log.csv` on Save decision | **Yes.** This is the demo. Cache with sidebar Data folder defaulting to `./data`. |

### Web and data artifacts

| File | Does | Re-run for demo? |
|---|---|---|
| `web/index.html` | Static marketing/architecture page (Tailwind CDN + FontAwesome). Quickstart tells the audience to run `streamlit run dashboard.py`. Not wired to live CSVs. | Open in a browser if you want a title slide. No Python. Needs network for CDNs unless cached. |
| `data/dataset_manifest.json` | Counts and generator knobs for the current snapshot (seed 42, 88 fraud invoices). | No |
| `data/rag_config.json` | margin 0.2, embedder minilm, seed 42 | No |
| `data/dashboard_data.csv` | The table Streamlit must find or it stops with an error telling you to run `train_gnn` then `build_dashboard_data`. | No — already present (644 rows) |
| `data/rule_flags.csv`, `data/rule_flags_pandas.csv`, `data/rule_evaluation.csv` | Neo4j flags, pandas flags, and saved per-rule evaluation. The join prefers the Neo4j-named file if both flag files exist. | No |
| `data/gnn_scores.csv`, `data/gnn_evaluation.csv`, `data/gnn_holdout.csv` | Out-of-fold invoice scores/predictions, fraud type/variant results, and held-out-type results. | No |
| `data/rag_similarity_scores.csv` | Per-invoice contract similarity, status, margin, and evidence used by the join and investigator view. | No |
| `data/graph_data.pt` | Serialized PyG heterogeneous graph with features, edges, labels, and invoice metadata. Rebuilt by `build_graph.py`. | No |
| `data/audit_log.csv` | Append-only auditor decisions from the Review page. | No. Optional: delete before a clean demo so past notes do not show. |
| `.env` (gitignored) | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` for `load_to_neo4j` and `fraud_checks`. | Create once if using Neo4j. Not needed for Streamlit-only demo. |
| `.gitignore` | Ignores `venv`, `__pycache__`, `.env`, `qdrant_data/`, `fy`. Does not ignore `data/*.csv` — the snapshot is meant to be committed. | N/A |

---

## Libraries to install

No lockfile in the repo. Use Python 3.10+. Create a venv, then install the groups you actually need.

**Minimum for a Streamlit-only demo:**

```bash
pip install streamlit pandas numpy scikit-learn
```

Contract Search will fall back to TF-IDF if `sentence-transformers` is missing. Overview, Review, and Evaluation work without torch, Neo4j, or Qdrant because scores are already in CSV.

| Package | Install | Used by | Demo? |
|---|---|---|---|
| streamlit | `pip install streamlit` | `dashboard.py` | Required to present |
| pandas | `pip install pandas` | Almost every script | Required |
| numpy | `pip install numpy` | dashboard RAG search, GNN, graph, `contract_rag` | Required |
| scikit-learn | `pip install scikit-learn` | GNN metrics/CV; TF-IDF fallback in dashboard and `contract_rag` | Recommended (Contract Search fallback) |
| Faker | `pip install Faker` | `generate_dataset.py` only | Not needed if you keep existing CSVs |
| torch | `pip install torch` (CPU wheel is enough) | `build_graph.py`, `train_gnn.py` | Not needed to present precomputed scores |
| torch-geometric | `pip install torch-geometric` | HeteroData, HeteroConv, SAGEConv, ToUndirected | Not needed to present |
| sentence-transformers | `pip install sentence-transformers` | `contract_rag` default embedder; dashboard Contract Search | Optional. First use downloads `all-MiniLM-L6-v2` (~80MB). |
| qdrant-client | `pip install qdrant-client` | `src/rag/contract_rag.py` vector index (memory or `--qdrant-path`) | Not needed at demo time; dashboard does not query Qdrant |
| neo4j | `pip install neo4j` | `load_to_neo4j.py`, `fraud_checks.py` | Only with a Neo4j server running |
| python-dotenv | `pip install python-dotenv` | Loads repo-root `.env` for Neo4j | Only with Neo4j |

One-liner for a full research machine:

```bash
pip install streamlit pandas numpy scikit-learn Faker torch torch-geometric sentence-transformers qdrant-client neo4j python-dotenv
```

`torch-geometric` may need a matching torch build; follow the PyG install matrix if `import torch_geometric` fails.

---

## What the live dashboard actually does

| Page | Behaviour |
|---|---|
| **Overview** | Counts invoices, flagged, rule alerts, GNN alerts, RAG mismatches. The detector chart shows Rules only, GNN only, RAG only, Rules + GNN (including any RAG overlap), and Not flagged; it is not a complete Venn breakdown. Also shows rule totals, monthly flagged invoices, and top 10 by flag then GNN score. |
| **Review and Inspector** | Filter by status, detector, min GNN risk. Pick an invoice: shows PO, vendor, creator/approver names, phone/email collisions, fired rule explanations, GNN/RAG evidence, save auditor decision. |
| **Contract Search (RAG)** | Re-embeds all `contract_text` in-process (not Qdrant). Search box ranks contracts by cosine/TF-IDF. Table of `rag_status==mismatch` from the precomputed CSV. `@st.cache_resource` so it does not rebuild every rerun after the first. First load can be slow. |
| **Model Evaluation** | Needs `ground_truth.csv`. Precision/recall/F1 for rules, GNN, RAG, and the OR of all three. Recall by fraud type × variant. Shows `gnn_holdout.csv` if present (GNN tested on a type it never trained on). |

## Scope and interpretation

This repository is a synthetic demonstration and research prototype. The generator creates deterministic, rule-shaped cases and an answer key; metrics measure detection on that generated snapshot, not real enterprise performance. The GNN is supervised and transductive, and the RAG margin is tuned on synthetic description swaps. The dashboard reads local CSVs and writes local review decisions; the project has no live ERP/AP ingestion, payment control, identity/access layer, or production deployment configuration. Treat flags as investigation leads rather than adjudications.

---

## Demo runbook

**Every presentation**

1. `cd` to the repo.
2. Activate the venv.
3. `streamlit run dashboard.py`.
4. Walk Overview → pick a Flagged invoice on Review (shell vendor phone collision is visually obvious) → Contract Search if MiniLM is installed → Model Evaluation for “rules catch standard, GNN/RAG catch some evasive/semantic cases”.

**Do not run**

- `plant_fraud.py` (legacy, corrupts labels)
- `generate_dataset.py` (new world, stale scores)
- `train_gnn.py` (long)
- `contract_rag.py` unless you have time for a MiniLM download mid-talk

**Optional extra if Neo4j is already up**

```bash
python src/models/load_to_neo4j.py
```

Then show a Cypher `MATCH` in Neo4j Browser. `python src/utils/fraud_checks.py` is unnecessary if `rule_flags.csv` already matches the CSVs.
