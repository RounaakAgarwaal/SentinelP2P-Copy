from __future__ import annotations

import csv
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.investigation.external_search import MissingSearchCredentials, TavilySearchProvider
from src.investigation.inputs import build_investigation_input
from src.investigation.research import (
    build_company_identity_summary,
    research_address,
    research_business,
    research_company_age,
    research_registration,
)
from src.investigation.service import start_investigation
from src.investigation.storage import create_evidence, create_investigation, get_investigation, list_evidence
from src.investigation.workflow import run_vendor_investigation

LANGGRAPH_AVAILABLE = importlib.util.find_spec("langgraph") is not None


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class StubProvider:
    def __init__(self, results=None, error: Exception | None = None):
        self.results = results or []
        self.error = error
        self.queries: list[str] = []

    def search(self, query: str, *, max_results: int = 5):
        self.queries.append(query)
        if self.error:
            raise self.error
        return list(self.results)


class StubResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class StubSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


class InvestigationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.db = self.root / "investigations.sqlite3"
        write_csv(self.data / "vendors.csv", [
            "vendor_id", "vendor_name", "email", "phone", "address", "bank_account",
            "registration_number", "vendor_category", "onboarding_date", "has_contract", "created_by_employee_id",
        ], [{
            "vendor_id": "VEN101", "vendor_name": "North Star Components", "email": "info@northstar.example",
            "phone": "+91 98765 43210", "address": "14 Sample Road, Pune, Maharashtra",
            "bank_account": "123456789012", "registration_number": "REG-00123",
            "vendor_category": "IT Hardware", "onboarding_date": "2024-01-01", "has_contract": "No",
            "created_by_employee_id": "EMP001",
        }])
        write_csv(self.data / "employees.csv", [
            "employee_id", "name", "email", "phone", "department", "role", "join_date",
        ], [])
        write_csv(self.data / "purchase_orders.csv", ["po_id", "vendor_id"], [{"po_id": "PO100", "vendor_id": "VEN101"}])
        write_csv(self.data / "invoices.csv", ["invoice_id", "po_id"], [{"invoice_id": "INV100", "po_id": "PO100"}])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_tavily_adapter_uses_mock_response_and_bearer_credential(self) -> None:
        session = StubSession(StubResponse({"results": [{
            "title": "North Star Components", "url": "https://example.com/vendor", "content": "Company listing", "score": 0.9,
        }]}))
        provider = TavilySearchProvider(api_key="test-token", session=session)
        results = provider.search("North Star Components")
        self.assertEqual(results[0]["url"], "https://example.com/vendor")
        args, kwargs = session.calls[0]
        self.assertEqual(args[0], "https://api.tavily.com/search")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(kwargs["json"]["query"], "North Star Components")

    def test_business_search_uses_available_vendor_context(self) -> None:
        vendor = {
            "vendor_id": "VEN101", "vendor_name": "North Star Components", "address": "14 Sample Road",
            "registration_number": "REG-00123", "email": "info@northstar.example", "phone": "+91 98765 43210",
        }
        provider = StubProvider([{"title": "North Star Components", "url": "https://example.com/north-star", "content": "North Star Components listing"}])
        from src.investigation.research import build_business_search_query
        findings = research_business(vendor, provider)
        self.assertIn("14 Sample Road", provider.queries[0])
        self.assertIn("REG-00123", provider.queries[0])
        self.assertIn("info@northstar.example", provider.queries[0])
        self.assertIn("+91 98765 43210", provider.queries[0])
        self.assertIn("North Star Components", build_business_search_query(vendor))
        self.assertEqual(findings[0]["verification_status"], "possible_match")

    def test_non_cin_registration_identifier_is_not_officially_verified(self) -> None:
        vendor = {"vendor_id": "VEN101", "vendor_name": "North Star Components", "registration_number": "REG-00123"}
        provider = StubProvider([{
            "title": "North Star Components REG-00123",
            "url": "https://www.mca.gov.in/company/REG-00123",
            "content": "North Star Components. Registration number REG-00123. Date of Incorporation: 01/01/2010. Registration Status: Active.",
        }])
        registration = research_registration(vendor, provider)[0]
        age = research_company_age(vendor, provider)[0]
        self.assertEqual(registration["verification_status"], "possible_match")
        self.assertEqual(registration["matched_entity"]["registration_status"], "Active")
        self.assertEqual(registration["matched_entity"]["incorporation_date"], "2010-01-01")
        self.assertEqual(age["verification_status"], "possible_match")
        self.assertGreater(age["matched_entity"]["company_age_years"], 0)

    def test_third_party_registration_result_is_not_officially_verified(self) -> None:
        vendor = {"vendor_id": "VEN101", "vendor_name": "North Star Components", "registration_number": "REG-00123"}
        provider = StubProvider([{
            "title": "North Star Components REG-00123",
            "url": "https://company-directory.example/north-star",
            "content": "North Star Components REG-00123 Registration Status: Active",
        }])
        result = research_registration(vendor, provider)[0]
        self.assertEqual(result["verification_status"], "possible_match")
        self.assertEqual(result["source_type"], "third_party_directory")

    def test_external_evidence_url_and_retrieval_time_persist(self) -> None:
        investigation = create_investigation(self.db, "VEN101")
        row = create_evidence(
            self.db, investigation_id=investigation["investigation_id"],
            check_type="external_business_search", finding="Potential listing found.",
            matched_entity={"vendor_id": "VEN101"}, verification_status="possible_match",
            source_type="third_party_web", source_url="https://example.com/vendor",
            retrieved_at="2026-11-09T10:00:00+00:00",
        )
        saved = list_evidence(self.db, investigation["investigation_id"])[0]
        self.assertEqual(saved["source_url"], "https://example.com/vendor")
        self.assertEqual(saved["retrieved_at"], "2026-11-09T10:00:00+00:00")
        self.assertEqual(saved["evidence_id"], row["evidence_id"])

    def test_external_url_is_preserved_without_attributing_it_to_internal_evidence(self) -> None:
        payload = start_investigation("VEN101", self.data, self.db)
        url = "https://example.com/north-star"
        external = create_evidence(
            self.db, investigation_id=payload["investigation_id"],
            check_type="external_business_search", finding="Possible business listing.",
            matched_entity={"vendor_id": "VEN101"}, verification_status="possible_match",
            source_type="third_party_web", source_url=url, retrieved_at="2026-11-09T10:00:00+00:00",
        )
        saved = list_evidence(self.db, payload["investigation_id"])
        external_saved = [item for item in saved if item["evidence_id"] == external["evidence_id"]]
        internal_saved = [item for item in saved if item["evidence_id"] != external["evidence_id"]]
        self.assertTrue(all(item["source_url"] == url for item in external_saved))
        self.assertTrue(all(item["source_url"] is None for item in internal_saved))

    def test_missing_api_credentials_raise_without_network_request(self) -> None:
        session = StubSession(StubResponse({"results": []}))
        with patch.dict(os.environ, {}, clear=True):
            provider = TavilySearchProvider(api_key=None, session=session)
            with self.assertRaises(MissingSearchCredentials):
                provider.search("North Star Components")
        self.assertEqual(session.calls, [])

    @unittest.skipUnless(LANGGRAPH_AVAILABLE, "LangGraph dependency is not installed in this Python environment")
    def test_successful_workflow_search_persists_source_urls_and_context(self) -> None:
        result = {
            "title": "North Star Components REG-00123",
            "url": "https://www.mca.gov.in/mcafoportal/companyLLPMasterData.do",
            "content": "North Star Components registration number REG-00123. Date of Incorporation: 01/01/2010. Registration Status: Active. Registered office 14 Sample Road, Pune, Maharashtra.",
            "score": 0.99,
        }
        provider = StubProvider([result])
        state = run_vendor_investigation(
            "VEN101", data_dir=self.data, db_path=self.db, search_provider=provider,
        )
        all_queries = "\n".join(provider.queries)
        self.assertGreaterEqual(len(provider.queries), 4)
        self.assertIn('"North Star Components"', all_queries)
        self.assertIn("India", all_queries)
        self.assertIn('"REG-00123"', all_queries)
        self.assertIn('"14 Sample Road, Pune, Maharashtra"', all_queries)
        self.assertIn("info@northstar.example", all_queries)
        self.assertIn("+91 98765 43210", all_queries)
        self.assertEqual(len(state["persisted_external_evidence"]), 4)
        registration = next(item for item in state["external_evidence"] if item["check_type"] == "company_registration_research")
        self.assertEqual(registration["verification_status"], "possible_match")
        self.assertEqual(registration["matched_entity"]["incorporation_date"], "2010-01-01")
        age = next(item for item in state["external_evidence"] if item["check_type"] == "company_age_research")
        self.assertEqual(age["verification_status"], "possible_match")
        address = next(item for item in state["external_evidence"] if item["check_type"] == "address_research")
        self.assertEqual(address["verification_status"], "possible_match")
        saved = list_evidence(self.db, state["investigation_id"])
        search_check_types = {item["check_type"] for item in state["external_evidence"]}
        search_evidence = [item for item in saved if item["check_type"] in search_check_types]
        internal_evidence = [item for item in saved if item["check_type"] not in search_check_types]
        self.assertEqual(len(search_evidence), len(state["external_evidence"]))
        self.assertTrue(all(item["source_url"] == result["url"] for item in search_evidence))
        self.assertTrue(all(item["retrieved_at"] for item in search_evidence))
        self.assertTrue(all(item["source_url"] is None for item in internal_evidence))
        self.assertTrue(internal_evidence)
        self.assertEqual(get_investigation(self.db, state["investigation_id"])["status"], "completed")

    @unittest.skipUnless(LANGGRAPH_AVAILABLE, "LangGraph dependency is not installed in this Python environment")
    def test_missing_credentials_mark_all_external_checks_unavailable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            state = run_vendor_investigation("VEN101", data_dir=self.data, db_path=self.db)
        self.assertEqual(len(state["external_evidence"]), 4)
        self.assertTrue(all(item["verification_status"] == "unavailable" for item in state["external_evidence"]))
        self.assertEqual(len(state["persisted_external_evidence"]), 4)

    @unittest.skipUnless(LANGGRAPH_AVAILABLE, "LangGraph dependency is not installed in this Python environment")
    def test_no_search_results_are_recorded_as_unavailable(self) -> None:
        state = run_vendor_investigation(
            "VEN101", data_dir=self.data, db_path=self.db, search_provider=StubProvider([]),
        )
        self.assertEqual(len(state["external_evidence"]), 4)
        self.assertTrue(all(item["verification_status"] == "unavailable" for item in state["external_evidence"]))

    def test_registration_information_unavailable_without_results(self) -> None:
        finding = research_registration({"vendor_id": "VEN101", "vendor_name": "North Star Components"}, StubProvider([]))[0]
        self.assertEqual(finding["verification_status"], "unavailable")
        self.assertIsNone(finding["matched_entity"])
        self.assertIsNone(finding["source_url"])

    def test_address_information_unavailable_without_results(self) -> None:
        finding = research_address({"vendor_id": "VEN101", "vendor_name": "North Star Components",
                                    "address": "14 Sample Road"}, StubProvider([]))[0]
        self.assertEqual(finding["verification_status"], "unavailable")
        self.assertIsNone(finding["source_url"])

    def test_exact_cin_and_legal_name_match_official_registry(self) -> None:
        vendor = {"vendor_id": "REAL001", "vendor_name": "Tata Consultancy Services Limited",
                  "registration_number": "L22210MH1995PLC084781", "city": "Mumbai",
                  "state": "Maharashtra", "country": "India"}
        result = {"title": "Tata Consultancy Services Limited",
                  "url": "https://www.mca.gov.in/company/master-data",
                  "content": "CIN: L22210MH1995PLC084781. Date of Incorporation: 25/01/1995. Registration Status: Active."}
        provider = StubProvider([result])
        finding = research_registration(vendor, provider)[0]
        self.assertEqual(finding["verification_status"], "verified")
        self.assertEqual(finding["verification_level"], "official_registry_verified")
        self.assertEqual(finding["source_type"], "government_registry")
        self.assertEqual(finding["matched_entity"]["registration_number"], vendor["registration_number"])
        self.assertEqual(finding["source_url"], result["url"])
        self.assertTrue(any(vendor["registration_number"] in q for q in provider.queries))

    def test_conflicting_cin_is_rejected(self) -> None:
        vendor = {"vendor_id": "REAL001", "vendor_name": "Tata Consultancy Services Limited",
                  "registration_number": "L22210MH1995PLC084781"}
        result = {"title": vendor["vendor_name"], "url": "https://www.mca.gov.in/company/other",
                  "content": "CIN: L22210MH1995PLC099999. Date of Incorporation: 01/01/2001. Registration Status: Active."}
        findings = research_registration(vendor, StubProvider([result]))
        self.assertEqual(findings[0]["verification_status"], "unavailable")
        self.assertIsNone(findings[0]["source_url"])

    def test_similar_name_is_not_treated_as_vendor_match(self) -> None:
        vendor = {"vendor_id": "REAL001", "vendor_name": "Tata Consultancy Services Limited",
                  "registration_number": "L22210MH1995PLC084781"}
        result = {"title": "Tata Consultancy Service Limited",
                  "url": "https://example.org/similar", "content": "Tata Consultancy Service Limited CIN unrelated."}
        findings = research_registration(vendor, StubProvider([result]))
        self.assertTrue(all(item["verification_status"] != "verified" for item in findings))
        self.assertIsNone(findings[0]["matched_entity"]["registration_number"])

    def test_foreign_entity_with_similar_name_is_rejected(self) -> None:
        vendor = {"vendor_id": "REAL001", "vendor_name": "Tata Consultancy Services Limited",
                  "registration_number": "L22210MH1995PLC084781"}
        result = {"title": "Tata Consultancy Services UK Limited",
                  "url": "https://find-and-update.company-information.service.gov.uk/company/12345678",
                  "content": "Tata Consultancy Services UK Limited. Incorporated in England. Date of incorporation: 01/02/2000."}
        findings = research_company_age(vendor, StubProvider([result]))
        self.assertEqual(findings[0]["verification_status"], "unavailable")
        self.assertIsNone(findings[0]["source_url"])
        self.assertIsNone(findings[0]["matched_entity"])

    def test_duplicate_urls_are_normalized_and_removed(self) -> None:
        vendor = {"vendor_id": "REAL001", "vendor_name": "Tata Consultancy Services Limited",
                  "registration_number": "L22210MH1995PLC084781", "city": "Mumbai", "state": "Maharashtra",
                  "country": "India"}
        first = {"title": "Tata Consultancy Services Limited", "url": "https://example.org/tcs?utm_source=a#top",
                 "content": "Tata Consultancy Services Limited company information."}
        second = {"title": "Tata Consultancy Services Limited", "url": "https://www.example.org/tcs?utm_source=b",
                  "content": "Tata Consultancy Services Limited company information."}
        findings = research_business(vendor, StubProvider([first, second]))
        source_findings = [item for item in findings if item["source_url"]]
        self.assertEqual(len(source_findings), 1)

    def test_third_party_incorporation_date_is_not_officially_verified(self) -> None:
        vendor = {"vendor_id": "REAL001", "vendor_name": "Tata Consultancy Services Limited",
                  "registration_number": "L22210MH1995PLC084781"}
        result = {"title": "Tata Consultancy Services Limited", "url": "https://company-directory.example/tcs",
                  "content": "CIN: L22210MH1995PLC084781. Date of Incorporation: 25/01/1995."}
        finding = research_company_age(vendor, StubProvider([result]))[0]
        self.assertEqual(finding["verification_status"], "unverified")
        self.assertEqual(finding["matched_entity"]["incorporation_date"], "1995-01-25")
        self.assertEqual(finding["matched_entity"]["incorporation_year"], 1995)
        self.assertEqual(finding["source_type"], "third_party_directory")
        self.assertEqual(finding["verification_level"], "third_party_match")

    def test_repeated_advertisements_with_identical_facts_collapse_to_one_source(self) -> None:
        vendor = {"vendor_id": "REAL001", "vendor_name": "Tata Consultancy Services Limited",
                  "registration_number": "L22210MH1995PLC084781", "address": "9 Nirmal Building Mumbai"}
        facts = "Tata Consultancy Services Limited CIN L22210MH1995PLC084781. Registered office 9 Nirmal Building Mumbai. Registration Status: Active."
        results = [
            {"title": "Public notice", "url": f"https://paper-{index}.example/notice", "content": facts}
            for index in range(1, 4)
        ]
        findings = research_registration(vendor, StubProvider(results))
        source_findings = [item for item in findings if item["source_url"]]
        self.assertEqual(len(source_findings), 1)

    def test_distinct_incorporation_year_is_preserved_during_fact_deduplication(self) -> None:
        vendor = {"vendor_id": "REAL001", "vendor_name": "Tata Consultancy Services Limited",
                  "registration_number": "L22210MH1995PLC084781", "address": "9 Nirmal Building Mumbai",
                  "official_website": "https://www.tcs.com"}
        ad = {"title": "Notice", "url": "https://paper.example/ad",
              "content": "Tata Consultancy Services Limited CIN L22210MH1995PLC084781. Registered office 9 Nirmal Building Mumbai."}
        annual_report = {"title": "Annual Report", "url": "https://www.tcs.com/report.pdf",
                         "content": "Tata Consultancy Services Limited CIN L22210MH1995PLC084781. Registered office 9 Nirmal Building Mumbai. The company was incorporated in 1995."}
        findings = research_registration(vendor, StubProvider([ad, annual_report]))
        source_findings = [item for item in findings if item["source_url"]]
        self.assertEqual(len(source_findings), 2)
        self.assertEqual({item["source_url"] for item in source_findings}, {ad["url"], annual_report["url"]})

    def test_official_company_document_year_is_not_registry_verification_or_exact_age(self) -> None:
        vendor = {"vendor_id": "REAL001", "vendor_name": "Tata Consultancy Services Limited",
                  "registration_number": "L22210MH1995PLC084781", "official_website": "https://www.tcs.com"}
        report = {"title": "Annual Report", "url": "https://www.tcs.com/report.pdf",
                  "content": "Tata Consultancy Services Limited CIN L22210MH1995PLC084781 was incorporated in 1995."}
        finding = research_company_age(vendor, StubProvider([report]))[0]
        self.assertEqual(finding["verification_level"], "official_company_document")
        self.assertEqual(finding["verification_status"], "possible_match")
        self.assertEqual(finding["matched_entity"]["incorporation_year"], 1995)
        self.assertIsNone(finding["matched_entity"]["incorporation_date"])
        self.assertIsNone(finding["matched_entity"]["company_age_years"])

    def test_identity_summary_separates_supplied_and_corroborated_facts(self) -> None:
        vendor = {"vendor_id": "REAL001", "vendor_name": "Tata Consultancy Services Limited",
                  "registration_number": "L22210MH1995PLC084781", "address": "9 Nirmal Building Mumbai"}
        result = {"title": vendor["vendor_name"], "url": "https://www.mca.gov.in/company/REAL001",
                  "content": f"{vendor['vendor_name']} CIN {vendor['registration_number']}."}
        finding = research_registration(vendor, StubProvider([result]))[0]
        summary = build_company_identity_summary(vendor, [finding])
        self.assertEqual(summary["supplied"]["cin"], vendor["registration_number"])
        self.assertEqual(summary["externally_corroborated"]["cin"], vendor["registration_number"])
        self.assertEqual(summary["verification_level"], "official_registry_verified")
        self.assertEqual(summary["strongest_sources"][0]["source_url"], result["url"])

    def test_ambiguous_multiple_incorporation_dates_are_not_selected(self) -> None:
        from src.investigation.research import _incorporation_date
        self.assertIsNone(_incorporation_date(
            "Tata Consultancy Services Limited CIN L22210MH1995PLC084781. "
            "Date of Incorporation: 25/01/1995. Another entity Date of Incorporation: 01/02/2000."
        ))

    def test_sources_are_classified_by_official_domain(self) -> None:
        from src.investigation.research import _source_type
        vendor = {"official_website": "https://www.tcs.com/"}
        self.assertEqual(_source_type("https://www.tcs.com/investors", vendor), "official_company_website")
        self.assertEqual(_source_type("https://www.nseindia.com/filings", vendor), "stock_exchange_filing")
        self.assertEqual(_source_type("https://www.mca.gov.in/company", vendor), "government_registry")
        self.assertEqual(_source_type("https://directory.example/company", vendor), "third_party_directory")

    def test_no_relevant_results_returns_unavailable(self) -> None:
        vendor = {"vendor_id": "REAL001", "vendor_name": "Tata Consultancy Services Limited",
                  "registration_number": "L22210MH1995PLC084781"}
        result = {"title": "Other Company", "url": "https://example.org/other",
                  "content": "Other Company CIN L22210MH1995PLC099999."}
        findings = research_registration(vendor, StubProvider([result]))
        self.assertEqual(findings[0]["verification_status"], "unavailable")
        self.assertIsNone(findings[0]["source_url"])

    def test_real_vendor_csv_loads_only_research_fields(self) -> None:
        csv_path = Path(__file__).resolve().parents[1] / "test_data" / "real_vendor_test.csv"
        payload = build_investigation_input("REAL001", self.data / "missing-internal-data", vendor_csv=csv_path)
        vendor = payload["vendor_details"]
        self.assertEqual(vendor["vendor_id"], "REAL001")
        self.assertEqual(vendor["vendor_name"], "Tata Consultancy Services Limited")
        self.assertEqual(vendor["registration_number"], "L22210MH1995PLC084781")
        self.assertNotIn("known_public_fact", vendor)
        self.assertNotIn("expected_agent_behavior", str(payload))
        self.assertEqual(payload["related_invoices"], [])

    def test_real_vendor_csv_rejects_unknown_vendor(self) -> None:
        csv_path = Path(__file__).resolve().parents[1] / "test_data" / "real_vendor_test.csv"
        with self.assertRaisesRegex(ValueError, "Unknown vendor_id"):
            build_investigation_input("REAL999", self.data, vendor_csv=csv_path)

    def test_real_vendor_csv_rejects_missing_file(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "Vendor CSV not found"):
            build_investigation_input("REAL001", self.data, vendor_csv=self.root / "missing.csv")

    def test_real_vendor_csv_rejects_missing_required_columns(self) -> None:
        bad_csv = self.root / "bad-vendors.csv"
        write_csv(bad_csv, ["vendor_id", "city"], [{"vendor_id": "REAL001", "city": "Mumbai"}])
        with self.assertRaisesRegex(ValueError, "legal_or_public_name"):
            build_investigation_input("REAL001", self.data, vendor_csv=bad_csv)

    def test_real_vendor_without_internal_datasets_is_unavailable_not_no_match(self) -> None:
        csv_path = Path(__file__).resolve().parents[1] / "test_data" / "real_vendor_test.csv"
        missing_data_dir = self.root / "no-synthetic-datasets"
        payload = start_investigation("REAL001", missing_data_dir, self.db, vendor_csv=csv_path)
        findings = payload["internal_verification_findings"]
        self.assertEqual(len(findings), 4)
        self.assertTrue(all(item["verification_status"] == "unavailable_no_internal_records" for item in findings))
        self.assertTrue(all(item["matched_entity"] is None for item in findings))
        self.assertFalse(payload["data_availability"]["internal_records"]["available"])
        self.assertTrue(all(item["verification_status"] != "no_match" for item in findings))
        saved = list_evidence(self.db, payload["investigation_id"])
        self.assertEqual(len(saved), 4)
        self.assertTrue(all(item["source_url"] is None for item in saved))

    @unittest.skipUnless(LANGGRAPH_AVAILABLE, "LangGraph dependency is not installed in this Python environment")
    def test_real_vendor_workflow_uses_mock_search_and_persists_provenance(self) -> None:
        csv_path = Path(__file__).resolve().parents[1] / "test_data" / "real_vendor_test.csv"
        result = {"title": "TCS company listing", "url": "https://example.com/tcs",
                  "content": "Tata Consultancy Services Limited company listing"}
        provider = StubProvider([result])
        state = run_vendor_investigation("REAL001", data_dir=self.root / "unused", db_path=self.db,
                                         vendor_csv=csv_path, search_provider=provider)
        all_queries = "\n".join(provider.queries)
        self.assertGreaterEqual(len(provider.queries), 4)
        self.assertIn('"Tata Consultancy Services Limited"', all_queries)
        self.assertIn("Mumbai Maharashtra India", all_queries)
        self.assertIn('"L22210MH1995PLC084781"', all_queries)
        self.assertIn('"9th Floor, Nirmal Building, Nariman Point, Mumbai 400 021"', all_queries)
        self.assertNotIn("expected_agent_behavior", all_queries)
        external_saved = [item for item in list_evidence(self.db, state["investigation_id"])
                          if item["source_type"] != "internal_records"]
        self.assertTrue(external_saved)
        self.assertTrue(all(item["source_url"] == result["url"] for item in external_saved))
        self.assertTrue(all(item["retrieved_at"] for item in external_saved))
        summary = state["company_identity_summary"]
        self.assertEqual(summary["supplied"]["legal_name"], "Tata Consultancy Services Limited")
        self.assertIn("externally_corroborated", summary)
        self.assertNotIn("fraud_decision", summary)
        internal_saved = [item for item in list_evidence(self.db, state["investigation_id"])
                          if item["source_type"] == "internal_records"]
        self.assertEqual(len(internal_saved), 4)
        self.assertTrue(all(item["verification_status"] == "unavailable_no_internal_records" for item in internal_saved))

    @unittest.skipUnless(LANGGRAPH_AVAILABLE, "LangGraph dependency is not installed in this Python environment")
    def test_provider_failure_in_one_node_does_not_abort_graph(self) -> None:
        state = run_vendor_investigation(
            "VEN101", data_dir=self.data, db_path=self.db, search_provider=StubProvider(error=ConnectionError()),
        )
        self.assertEqual(len(state["external_evidence"]), 4)
        self.assertEqual(len(state["errors"]), 4)
        self.assertTrue(all(item["verification_status"] == "unavailable" for item in state["external_evidence"]))
        self.assertEqual(len(state["persisted_external_evidence"]), 4)

    def test_day1_database_migration_preserves_existing_records(self) -> None:
        legacy_db = self.root / "day1.sqlite3"
        connection = sqlite3.connect(legacy_db)
        connection.executescript("""
            CREATE TABLE investigations (
                investigation_id TEXT PRIMARY KEY, vendor_id TEXT NOT NULL, invoice_id TEXT,
                status TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT
            );
            CREATE TABLE evidence (
                evidence_id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL, check_type TEXT NOT NULL,
                finding TEXT NOT NULL, matched_entity TEXT, verification_status TEXT NOT NULL,
                source_type TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id) ON DELETE CASCADE
            );
            INSERT INTO investigations VALUES ('legacy-i', 'VEN101', NULL, 'open', '2026-01-01T00:00:00+00:00', NULL);
            INSERT INTO evidence VALUES ('legacy-e', 'legacy-i', 'phone_match', 'Existing finding', NULL,
                                         'match_found', 'internal_records', '2026-01-01T00:00:00+00:00');
        """)
        connection.commit()
        connection.close()

        from src.investigation.storage import initialize_database
        initialize_database(legacy_db)
        connection = sqlite3.connect(legacy_db)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(evidence)")}
        counts = (connection.execute("SELECT count(*) FROM investigations").fetchone()[0],
                  connection.execute("SELECT count(*) FROM evidence").fetchone()[0])
        connection.close()
        self.assertIn("source_url", columns)
        self.assertIn("retrieved_at", columns)
        self.assertEqual(counts, (1, 1))
        legacy = list_evidence(legacy_db, "legacy-i")[0]
        self.assertEqual(legacy["finding"], "Existing finding")
        self.assertIsNone(legacy["source_url"])
        self.assertIsNone(legacy["retrieved_at"])


if __name__ == "__main__":
    unittest.main()
