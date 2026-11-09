"""LangGraph workflow for internal context and conservative public web research."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from .external_search import MissingSearchCredentials, SearchProvider, TavilySearchProvider
from .research import (
    build_company_identity_summary,
    research_address,
    research_business,
    research_company_age,
    research_registration,
)
from .service import start_investigation
from .storage import create_evidence, update_investigation


class InvestigationState(TypedDict, total=False):
    vendor_id: str
    invoice_id: str | None
    data_dir: str
    db_path: str
    vendor_csv: str | None
    investigation_id: str
    investigation_input: dict[str, Any]
    external_evidence: list[dict[str, Any]]
    persisted_external_evidence: list[dict[str, Any]]
    company_identity_summary: dict[str, Any]
    errors: list[dict[str, str]]


def _unavailable(check_type: str, message: str) -> dict[str, Any]:
    from datetime import datetime, timezone

    return {
        "check_type": check_type,
        "finding": message,
        "matched_entity": None,
        "verification_status": "unavailable",
        "source_type": "web_search",
        "source_url": None,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _append_node_error(state: InvestigationState, node_name: str, error: Exception) -> list[dict[str, str]]:
    # Store error class only. Exception messages may contain provider request details.
    return [*state.get("errors", []), {"node": node_name, "error_type": type(error).__name__}]


def build_investigation_graph(
    search_provider: SearchProvider | None = None,
    *,
    default_data_dir: str | Path | None = None,
    default_db_path: str | Path | None = None,
):
    """Build and compile a six-node graph; provider injection supports offline testing."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as error:
        raise RuntimeError(
            "LangGraph is required for vendor investigations. Install requirements-phase3.txt in the active Python environment."
        ) from error

    repo_root = Path(__file__).resolve().parents[2]
    data_default = Path(default_data_dir) if default_data_dir else repo_root / "data"
    db_default = Path(default_db_path) if default_db_path else data_default / "investigations.sqlite3"
    provider = search_provider or TavilySearchProvider()

    def load_existing_data(state: InvestigationState) -> dict[str, Any]:
        try:
            payload = start_investigation(
                state["vendor_id"],
                state.get("data_dir", str(data_default)),
                state.get("db_path", str(db_default)),
                invoice_id=state.get("invoice_id"),
                vendor_csv=state.get("vendor_csv"),
            )
            return {
                "investigation_id": payload["investigation_id"],
                "investigation_input": payload,
                "external_evidence": [],
                "persisted_external_evidence": [],
                "errors": state.get("errors", []),
            }
        except Exception as error:
            return {
                "investigation_input": {},
                "external_evidence": [],
                "persisted_external_evidence": [],
                "errors": _append_node_error(state, "load_existing_data", error),
            }

    def run_research_node(
        state: InvestigationState,
        *,
        node_name: str,
        check_type: str,
        research_function,
    ) -> dict[str, Any]:
        payload = state.get("investigation_input") or {}
        vendor = payload.get("vendor_details")
        if not vendor:
            finding = _unavailable(check_type, "Research skipped because vendor input data was unavailable.")
            return {"external_evidence": [*state.get("external_evidence", []), finding]}
        try:
            findings = research_function(vendor, provider)
            return {"external_evidence": [*state.get("external_evidence", []), *findings]}
        except MissingSearchCredentials:
            finding = _unavailable(check_type, "External search unavailable: configure TAVILY_API_KEY.")
            return {"external_evidence": [*state.get("external_evidence", []), finding]}
        except Exception as error:
            finding = _unavailable(check_type, f"External provider request failed ({type(error).__name__}).")
            return {
                "external_evidence": [*state.get("external_evidence", []), finding],
                "errors": _append_node_error(state, node_name, error),
            }

    def external_business_search(state: InvestigationState) -> dict[str, Any]:
        return run_research_node(state, node_name="external_business_search",
                                 check_type="external_business_search", research_function=research_business)

    def company_registration_research(state: InvestigationState) -> dict[str, Any]:
        return run_research_node(state, node_name="company_registration_research",
                                 check_type="company_registration_research", research_function=research_registration)

    def company_age_research(state: InvestigationState) -> dict[str, Any]:
        return run_research_node(state, node_name="company_age_research",
                                 check_type="company_age_research", research_function=research_company_age)

    def address_research(state: InvestigationState) -> dict[str, Any]:
        return run_research_node(state, node_name="address_research",
                                 check_type="address_research", research_function=research_address)

    def persist_external_evidence(state: InvestigationState) -> dict[str, Any]:
        investigation_id = state.get("investigation_id")
        db_path = state.get("db_path", str(db_default))
        if not investigation_id:
            return {"errors": [*state.get("errors", []), {
                "node": "persist_external_evidence", "error_type": "MissingInvestigationId"
            }]}
        persisted = []
        errors = list(state.get("errors", []))
        for evidence in state.get("external_evidence", []):
            try:
                persisted.append(create_evidence(
                    db_path,
                    investigation_id=investigation_id,
                    check_type=evidence["check_type"],
                    finding=evidence["finding"],
                    matched_entity=evidence.get("matched_entity"),
                    verification_status=evidence["verification_status"],
                    source_type=evidence["source_type"],
                    source_url=evidence.get("source_url"),
                    retrieved_at=evidence.get("retrieved_at"),
                ))
            except Exception as error:
                errors.append({"node": "persist_external_evidence", "error_type": type(error).__name__})
        try:
            update_investigation(db_path, investigation_id, status="completed")
        except Exception as error:
            errors.append({"node": "persist_external_evidence", "error_type": type(error).__name__})
        vendor = ((state.get("investigation_input") or {}).get("vendor_details") or {})
        summary = build_company_identity_summary(vendor, state.get("external_evidence", []))
        return {"persisted_external_evidence": persisted, "company_identity_summary": summary, "errors": errors}

    builder = StateGraph(InvestigationState)
    builder.add_node("load_existing_data", load_existing_data)
    builder.add_node("external_business_search", external_business_search)
    builder.add_node("company_registration_research", company_registration_research)
    builder.add_node("company_age_research", company_age_research)
    builder.add_node("address_research", address_research)
    builder.add_node("persist_external_evidence", persist_external_evidence)
    builder.add_edge(START, "load_existing_data")
    builder.add_edge("load_existing_data", "external_business_search")
    builder.add_edge("external_business_search", "company_registration_research")
    builder.add_edge("company_registration_research", "company_age_research")
    builder.add_edge("company_age_research", "address_research")
    builder.add_edge("address_research", "persist_external_evidence")
    builder.add_edge("persist_external_evidence", END)
    return builder.compile()


def run_vendor_investigation(
    vendor_id: str,
    *,
    invoice_id: str | None = None,
    data_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    vendor_csv: str | Path | None = None,
    search_provider: SearchProvider | None = None,
) -> InvestigationState:
    """Run the workflow; no node sets a fraud decision or performs payment actions."""
    repo_root = Path(__file__).resolve().parents[2]
    resolved_data = Path(data_dir) if data_dir else repo_root / "data"
    resolved_db = Path(db_path) if db_path else resolved_data / "investigations.sqlite3"
    graph = build_investigation_graph(
        search_provider,
        default_data_dir=resolved_data,
        default_db_path=resolved_db,
    )
    return graph.invoke({
        "vendor_id": vendor_id,
        "invoice_id": invoice_id,
        "data_dir": str(resolved_data),
        "db_path": str(resolved_db),
        "vendor_csv": str(vendor_csv) if vendor_csv is not None else None,
        "external_evidence": [],
        "errors": [],
    })
