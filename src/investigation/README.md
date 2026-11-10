# Investigation foundation

This package combines internal CSV checks with a deterministic LangGraph research workflow. It does not change detector logic, run GST checks, make fraud decisions, or block/release payments. Search results are external leads and are not treated as proof.

## LangGraph architecture

`src/investigation/workflow.py` defines a typed `InvestigationState` (`TypedDict`) and a sequential six-node `StateGraph`:

1. `load_existing_data` calls the Day 1 `start_investigation` service. This loads vendor/invoice/rule/GNN/RAG/internal-check data and creates the SQLite investigation.
2. `external_business_search` searches the vendor name with available address, registration number, email, and phone context.
3. `company_registration_research` searches public registration results. A result is called verified only when it is on an MCA registry host, contains the supplied registration identifier, and includes an explicit registration status. Other matches remain possible or unverified.
4. `company_age_research` looks for an incorporation date and calculates an age only when a date is present. Official confirmation requires the MCA host plus a matching registration identifier.
5. `address_research` searches the supplied business name/address. Search snippets can yield `possible_match` or `unverified`; this workflow does not label a physical location verified from snippets.
6. `persist_external_evidence` stores findings and completes the investigation. Each research node catches its own provider failures so later checks still run.

The graph has no LLM node and has no decision or payment-action node. Its purpose is evidence collection and orchestration, leaving human review outside the graph.

## Dependencies and credentials

Use Python 3.10 or newer. Install the isolated Phase 3 dependencies in a project virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-phase3.txt
```

Configure `TAVILY_API_KEY` in the process environment. The Tavily REST adapter also accepts `TAVILY_API_URL` to point at a compatible endpoint; do not commit credentials. If the API key is absent, each web check records `unavailable` rather than failing the workflow.

The provider is isolated behind the `SearchProvider` protocol in `external_search.py`; Tavily is the current adapter. Research nodes can be tested with an injected provider and do not require live web access in tests.

## Start an investigation

From the repository root:

```bash
.venv/bin/python -m src.investigation.cli --vendor-id VEN001
```

The command reads existing `data/` CSVs, creates or resumes the SQLite schema at `data/investigations.sqlite3`, persists the investigation, internal findings, and external findings, then prints a JSON state. Add `--invoice-id INV0001` to scope it to a related invoice, `--data-dir PATH` to select another data directory, or `--db PATH` to select another SQLite file. Bank account values are masked in input and evidence records.

## Python entry points

- `build_investigation_input(vendor_id, data_dir, invoice_id=None)` builds a state-shaped dictionary without creating a database record.
- `start_investigation(vendor_id, data_dir, db_path, invoice_id=None)` builds that dictionary, creates an investigation, and persists the internal verification findings.
- `run_internal_vendor_checks(vendor_id, data_dir)` runs the phone, email, bank account, and registration number comparisons independently of SQLite.
- `run_vendor_investigation(vendor_id, data_dir=..., db_path=..., search_provider=...)` invokes the compiled graph; `build_investigation_graph()` can be used when a caller wants to manage invocation itself.
- `src.investigation.storage` provides initialization and CRUD operations for investigations and evidence.

## LangGraph handoff

The graph loads Day 1 state through `start_investigation`. Relevant state keys are `vendor_id`, `invoice_id`, `investigation_id`, `investigation_input`, `external_evidence`, `persisted_external_evidence`, and `errors`. Inside `investigation_input`, each invoice contains its existing `rule_flags`, `gnn` score/prediction, and `contract_rag` result when the corresponding files are available. A missing result is `None`; inspect `data_availability` before deciding whether a check was unavailable or returned no match.

## External evidence storage

The Day 1 `evidence` table is extended additively with nullable `source_url` and `retrieved_at` columns. Existing investigations and evidence rows are preserved; old rows retain `NULL` provenance fields because their original URLs/times were not recorded. New external rows store both fields, `source_type`, the finding, matched entity, and verification status. `created_at` remains the SQLite record-creation time; `retrieved_at` is the search retrieval time.

## Known limitations

- This uses search results and short returned content, not a direct company-registry API or full page verification. An MCA search result can support a cautious match; it is not a substitute for a formal registry lookup.
- Third-party snippets may be stale, ambiguous, or incorrect. Address results are never considered proof of occupancy or business use.
- Company/date/status extraction is conservative pattern matching, not entity resolution. Missing facts stay missing.
- Automated tests mock the provider. A live Tavily request requires a valid credential, network access, and provider quota; it has not been exercised by the test suite.
- The SQLite database is local and intended for this development workflow. External evidence collection makes no fraud decision and triggers no payment action.
