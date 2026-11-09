"""Evidence-focused public research transformations for web search results."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .external_search import SearchProvider, SearchResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalized(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _cin_values(text: str) -> set[str]:
    # Indian CIN: listing status + industry code + state + year + company type + number.
    return {value.upper() for value in re.findall(r"\b[A-Z]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b", text.upper())}


def _is_cin(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}", value.strip().upper()))


def _source_type(url: str, vendor: dict[str, Any] | None = None) -> str:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    official_url = str((vendor or {}).get("official_website", ""))
    official_host = (urlsplit(official_url).hostname or "").lower().removeprefix("www.")
    normalized_host = host.removeprefix("www.")
    if host == "mca.gov.in" or host.endswith(".mca.gov.in") or host in {"mcacdm.nic.in", "www.mcacdm.nic.in"}:
        return "government_registry"
    if host.endswith(".gov.in") or host.endswith(".nic.in"):
        return "government_directory"
    if host in {"nseindia.com", "www.nseindia.com", "bseindia.com", "www.bseindia.com"} or host.endswith((".nseindia.com", ".bseindia.com")):
        return "stock_exchange_filing"
    if official_host and (normalized_host == official_host or normalized_host.endswith("." + official_host)):
        return "official_company_website"
    if any(token in host for token in ("directory", "zaubacorp", "tofler", "quickcompany", "companycheck", "opencorporates", "companieshouse")):
        return "third_party_directory"
    return "other"


def _body(result: SearchResult) -> str:
    return f"{result.get('title', '')}\n{result.get('content', '')}".strip()


def _exact_name(name: str, text: str) -> bool:
    """Match the full normalized legal name as a phrase, not a short substring."""
    name_words = re.findall(r"[A-Z0-9]+", name.upper())
    if not name_words:
        return False
    pattern = r"(?<![A-Z0-9])" + r"[^A-Z0-9]+".join(map(re.escape, name_words)) + r"(?![A-Z0-9])"
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


def _foreign_entity(text: str, url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    foreign_domain = host.endswith((".co.uk", ".gov.uk", ".uk", ".com.au", ".ca")) or "companieshouse.gov.uk" in host
    foreign_legal_context = bool(re.search(
        r"\b(incorporated|registered|formed)\s+(in|under the laws of)\s+(the )?(united kingdom|uk|england|wales|scotland|united states|usa|australia|canada)\b",
        text, re.IGNORECASE,
    ))
    if not (foreign_domain or foreign_legal_context):
        return False
    # A foreign subsidiary/branch may be relevant as context, but is not the Indian parent entity.
    return not bool(re.search(r"\b(overseas subsidiary|foreign subsidiary|uk subsidiary|branch office|establishment of)\b", text, re.IGNORECASE))


def _canonical_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().removeprefix("www.")
        path = re.sub(r"/+$", "", parts.path) or "/"
        query = urlencode(sorted((key, value) for key, value in parse_qsl(parts.query) if not key.lower().startswith("utm_")))
        return urlunsplit((parts.scheme.lower(), host, path, query, ""))
    except ValueError:
        return url.strip().lower()


def _incorporation_year(text: str) -> int | None:
    """Extract a year only when the source explicitly ties it to incorporation."""
    full_date = _incorporation_date(text)
    if full_date:
        return int(full_date[:4])
    patterns = (
        r"\b(?:year of incorporation|incorporation year)\s*[:\-]?\s*(19\d{2}|20\d{2})\b",
        r"\b(?:incorporated|incorporation)\s+(?:(?:in|during)\s+|year\s+)?(?:the\s+year\s+of\s+)?(19\d{2}|20\d{2})\b",
        r"\b(?:incorporated|incorporation)\s+(?:in\s+)?the\s+year\s+(19\d{2}|20\d{2})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _material_facts(result: SearchResult, vendor: dict[str, Any]) -> tuple[Any, ...]:
    text = _body(result)
    candidate = _candidate(vendor, result)
    years = tuple(sorted(set(re.findall(r"\b(?:year of incorporation|incorporation year|incorporated(?: in)?(?: the year)?|incorporation(?: in)?)\s*[:\-]?\s*(?:the\s+year\s+)?(19\d{2}|20\d{2})\b", text, re.I))))
    raw_dates = re.findall(
        r"(?:date of incorporation|incorporated on|incorporation date|date incorporated|date of registration|registered on)\s*[:\-]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})",
        text, flags=re.I,
    )
    full_dates = tuple(sorted(set(_parse_date(value) or _normalized(value) for value in raw_dates)))
    statuses = tuple(sorted({value.lower() for value in re.findall(r"(?:registration\s+status|status)\s*[:\-]?\s*(active|inactive|struck\s+off|dissolved|suspended)\b", text, re.I)}))
    address = str(vendor.get("address", ""))
    address_match = bool(address and _normalized(address) in _normalized(text))
    identifiers = tuple(sorted(_cin_values(text)))
    if not any((identifiers, full_dates, years, statuses, address_match)):
        return ()
    return (candidate["exact_name"], identifiers, tuple(sorted(full_dates)), tuple(sorted(years)), statuses, address_match)


_SOURCE_STRENGTH = {
    "government_registry": 0,
    "official_company_website": 1,
    "stock_exchange_filing": 2,
    "government_directory": 3,
    "third_party_directory": 4,
    "other": 5,
}


def _deduplicate(results: list[SearchResult], vendor: dict[str, Any] | None = None) -> list[SearchResult]:
    """Collapse URL and fact-equivalent repeats, preferring stronger sources.

    Facts that differ by CIN, incorporation year/date, registration status, or supplied
    address are kept as separate evidence even when the surrounding text is similar.
    """
    vendor = vendor or {}
    url_results: list[SearchResult] = []
    url_indexes: dict[str, int] = {}
    for result in results:
        url = str(result.get("url", ""))
        if not url.startswith(("https://", "http://")):
            continue
        canonical = _canonical_url(url)
        if canonical in url_indexes:
            prior = url_results[url_indexes[canonical]]
            prior_content = str(prior.get("content", ""))
            extra_content = str(result.get("content", ""))
            if extra_content and _normalized(extra_content) not in _normalized(prior_content):
                prior["content"] = (prior_content + "\n" + extra_content).strip()
            if not prior.get("title") and result.get("title"):
                prior["title"] = result["title"]
            continue
        url_indexes[canonical] = len(url_results)
        url_results.append(dict(result))

    grouped: dict[tuple[Any, ...], SearchResult] = {}
    ungrouped: list[SearchResult] = []
    for result in url_results:
        facts = _material_facts(result, vendor)
        if not facts:
            ungrouped.append(result)
            continue
        prior = grouped.get(facts)
        if prior is None:
            grouped[facts] = result
            continue
        prior_source = _source_type(str(prior.get("url", "")), vendor)
        source = _source_type(str(result.get("url", "")), vendor)
        prior_key = (_SOURCE_STRENGTH.get(prior_source, 99), -float(prior.get("score") or 0))
        current_key = (_SOURCE_STRENGTH.get(source, 99), -float(result.get("score") or 0))
        if current_key < prior_key:
            grouped[facts] = result

    # For non-fact-bearing snippets, retain the previous content-similarity protection.
    content_unique: list[SearchResult] = []
    seen_content: list[str] = []
    for result in ungrouped:
        content = _normalized(_body(result))
        if content and any(SequenceMatcher(None, content, old).ratio() >= 0.92 for old in seen_content):
            continue
        content_unique.append(result)
        if content:
            seen_content.append(content)
    return [*grouped.values(), *content_unique]


def _search_queries(provider: SearchProvider, queries: list[str], vendor: dict[str, Any]) -> list[SearchResult]:
    gathered: list[SearchResult] = []
    for query in queries:
        if query.strip():
            gathered.extend(provider.search(query, max_results=5))
    return _deduplicate(gathered, vendor)


def _location(vendor: dict[str, Any]) -> str:
    return " ".join(str(vendor.get(field, "")).strip() for field in ("city", "state", "country") if str(vendor.get(field, "")).strip())


def _priority_domains(vendor: dict[str, Any]) -> str:
    domains = ["mca.gov.in", "mcacdm.nic.in", "nseindia.com", "bseindia.com"]
    official = urlsplit(str(vendor.get("official_website", ""))).hostname
    if official:
        domains.insert(0, official.removeprefix("www."))
    return "(" + " OR ".join(f"site:{domain}" for domain in domains) + ")"


def build_business_search_query(vendor: dict[str, Any]) -> str:
    """Exact legal name + Indian location with preferred authoritative domains."""
    name = str(vendor.get("vendor_name", "")).strip()
    location = _location(vendor)
    address = str(vendor.get("address", "")).strip()
    registration = str(vendor.get("registration_number", "")).strip()
    contacts = [str(vendor.get(key, "")).strip() for key in ("email", "phone") if str(vendor.get(key, "")).strip()]
    return " ".join(part for part in (f'"{name}"' if name else "", location,
                                      f'"{address}"' if address else "",
                                      f'"{registration}"' if registration else "", *contacts,
                                      "India", _priority_domains(vendor)) if part)


def _empty_result(check_type: str, message: str) -> dict[str, Any]:
    return {
        "check_type": check_type, "finding": message, "matched_entity": None,
        "verification_status": "unavailable", "source_type": "other", "source_url": None,
        "retrieved_at": _now(),
    }


def _candidate(vendor: dict[str, Any], result: SearchResult) -> dict[str, Any]:
    text = _body(result)
    name = str(vendor.get("vendor_name", "")).strip()
    supplied_number = str(vendor.get("registration_number", "")).strip().upper()
    cin_values = _cin_values(text)
    exact_cin = bool(supplied_number and _normalized(supplied_number) in {_normalized(value) for value in cin_values})
    conflicting_cin = bool(cin_values and supplied_number and not exact_cin)
    exact_number = bool(supplied_number and _normalized(supplied_number) in _normalized(text))
    registration_match = exact_cin or (not cin_values and exact_number)
    exact_name = _exact_name(name, text)
    source_type = _source_type(str(result.get("url", "")), vendor)
    foreign = _foreign_entity(text, str(result.get("url", "")))
    # Foreign incorporated entities and results with a different CIN cannot be evidence about
    # the Indian legal entity. Overseas affiliates remain contextual leads only.
    excluded = conflicting_cin or (foreign and not re.search(r"\b(overseas subsidiary|foreign subsidiary|uk subsidiary|branch office|establishment of)\b", text, re.I))
    return {
        "text": text, "exact_name": exact_name, "exact_cin": exact_cin,
        "exact_number": exact_number, "conflicting_cin": conflicting_cin,
        "registration_match": registration_match,
        "foreign": foreign, "excluded": excluded, "source_type": source_type,
    }


def _evidence(check_type: str, vendor: dict[str, Any], result: SearchResult, *, finding: str,
              status: str, matched_entity: dict[str, Any] | None = None) -> dict[str, Any]:
    candidate = _candidate(vendor, result)
    if candidate["exact_name"] and candidate["exact_cin"]:
        verification_level = {
            "government_registry": "official_registry_verified",
            "official_company_website": "official_company_document",
            "stock_exchange_filing": "stock_exchange_filing",
            "third_party_directory": "third_party_match",
        }.get(candidate["source_type"], "unverified")
    else:
        verification_level = "unverified"
    return {
        "check_type": check_type,
        "finding": finding,
        "matched_entity": {"vendor_id": vendor.get("vendor_id"), **(matched_entity or {}),
                           "title": str(result.get("title", "")), "source_excerpt": _body(result)[:2000]},
        "verification_status": status,
        "verification_level": verification_level,
        "source_type": _source_type(str(result["url"]), vendor),
        "source_url": str(result["url"]),
        "retrieved_at": _now(),
    }


def research_business(vendor: dict[str, Any], provider: SearchProvider) -> list[dict[str, Any]]:
    name = str(vendor.get("vendor_name", "")).strip()
    if not name:
        return [_empty_result("external_business_search", "No vendor business name is available to search.")]
    location = _location(vendor)
    registration = str(vendor.get("registration_number", "")).strip()
    address = str(vendor.get("address", "")).strip()
    queries = [build_business_search_query(vendor)]
    if registration:
        queries.append(f'"{registration}" India company { _priority_domains(vendor) }')
    if address:
        queries.append(f'"{address}" "{name}" {location} India { _priority_domains(vendor) }')
    results = _search_queries(provider, queries, vendor)
    if not results:
        return [_empty_result("external_business_search", "The web search returned no business results.")]
    findings = []
    for result in results:
        candidate = _candidate(vendor, result)
        if candidate["excluded"]:
            continue
        exact_identity = candidate["exact_name"] and (candidate["exact_cin"] or not _is_cin(registration))
        status = "possible_match" if exact_identity else "unverified"
        findings.append(_evidence("external_business_search", vendor, result,
            finding="Search result retained as a lead; it does not by itself verify the vendor.", status=status,
            matched_entity={"exact_name_match": candidate["exact_name"], "cin_match": candidate["exact_cin"]}))
    return findings or [_empty_result("external_business_search", "No search results passed the vendor identity relevance checks.")]


def _parse_date(value: str) -> str | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%B %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _incorporation_date(text: str) -> str | None:
    date_pattern = r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"
    pattern = rf"(?:date of incorporation|incorporated on|incorporation date|date incorporated|date of registration|registered on)\s*[:\-]?\s*{date_pattern}"
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
    # A snippet containing multiple entities/dates is ambiguous; never select the first at random.
    if len(matches) != 1:
        return None
    return _parse_date(matches[0].group(1))


def _registration_status(text: str) -> str | None:
    match = re.search(r"(?:(?:company\s+)?registration\s+status|status)\s*[:\-]?\s*(active|inactive|struck\s+off|dissolved|suspended)\b", text, re.I)
    return re.sub(r"\s+", " ", match.group(1)).title() if match else None


def _identity_queries(vendor: dict[str, Any], *, include_address: bool = False, age: bool = False) -> list[str]:
    name = str(vendor.get("vendor_name", "")).strip()
    registration = str(vendor.get("registration_number", "")).strip()
    location = _location(vendor)
    address = str(vendor.get("address", "")).strip()
    preferred = _priority_domains(vendor)
    queries = []
    if registration:
        queries.append(f'"{registration}" India {"incorporation date" if age else "company registration status"} {preferred}')
    if name:
        queries.append(f'"{name}" {location} India {"incorporation date" if age else "CIN registration status"} {preferred}')
    if include_address and name and address:
        queries.append(f'"{address}" "{name}" {location} India {preferred}')
    return queries


def research_registration(vendor: dict[str, Any], provider: SearchProvider) -> list[dict[str, Any]]:
    check_type = "company_registration_research"
    if not vendor.get("vendor_name") and not vendor.get("registration_number"):
        return [_empty_result(check_type, "No vendor name or registration identifier is available to search.")]
    results = _search_queries(provider, _identity_queries(vendor, include_address=True), vendor)
    findings = []
    supplied_number = str(vendor.get("registration_number", "")).strip()
    for result in results:
        candidate = _candidate(vendor, result)
        if candidate["excluded"]:
            continue
        status_found = _registration_status(candidate["text"])
        date_found = _incorporation_date(candidate["text"]) if candidate["exact_name"] and candidate["registration_match"] else None
        exact_identity = candidate["exact_name"] and (candidate["registration_match"] if supplied_number else True)
        verified = (candidate["source_type"] == "government_registry" and _is_cin(supplied_number)
                    and candidate["exact_cin"] and candidate["exact_name"] and status_found is not None)
        if verified:
            status = "verified"
            finding = "Official Indian registry evidence matches the exact legal name and supplied CIN and reports a registration status."
        elif candidate["exact_cin"] and candidate["exact_name"]:
            status = "possible_match"
            finding = "The exact legal name and CIN appear in a result, but the source does not qualify as official registry verification."
        elif candidate["exact_name"] or candidate["exact_number"]:
            status = "possible_match"
            finding = "A potentially relevant result was found, but exact legal entity and CIN agreement is incomplete."
        else:
            status = "unverified"
            finding = "The result did not establish the supplied legal entity and registration identifier."
        findings.append(_evidence(check_type, vendor, result, finding=finding, status=status, matched_entity={
            "company_name": str(vendor.get("vendor_name")) if candidate["exact_name"] else None,
            "registration_number": supplied_number if candidate["exact_cin"] or candidate["exact_number"] else None,
            "registration_status": status_found if (candidate["exact_name"] and (candidate["registration_match"] or not supplied_number)) else None,
            "incorporation_date": date_found,
            "exact_name_match": candidate["exact_name"], "cin_match": candidate["exact_cin"],
        }))
    return findings or [_empty_result(check_type, "No relevant public registration evidence was found.")]


def research_company_age(vendor: dict[str, Any], provider: SearchProvider) -> list[dict[str, Any]]:
    check_type = "company_age_research"
    if not vendor.get("vendor_name") and not vendor.get("registration_number"):
        return [_empty_result(check_type, "No vendor name or registration identifier is available to search.")]
    results = _search_queries(provider, _identity_queries(vendor, age=True), vendor)
    findings = []
    registration = str(vendor.get("registration_number", "")).strip()
    for result in results:
        candidate = _candidate(vendor, result)
        if candidate["excluded"]:
            continue
        identity_match = candidate["exact_cin"] or (candidate["registration_match"] and candidate["exact_name"] and not candidate["foreign"]) or (candidate["exact_name"] and not registration and not candidate["foreign"])
        incorporated = _incorporation_date(candidate["text"]) if identity_match else None
        incorporation_year = _incorporation_year(candidate["text"]) if identity_match else None
        age_years = None
        if incorporated:
            age_years = round((date.today() - date.fromisoformat(incorporated)).days / 365.2425, 2)
            if age_years < 0:
                incorporated = None
                age_years = None
        number_confirmed = candidate["exact_cin"] if _is_cin(registration) else candidate["registration_match"]
        authoritative = (candidate["source_type"] == "government_registry" and _is_cin(registration)
                         and candidate["exact_name"] and number_confirmed and incorporated is not None)
        if authoritative:
            status = "verified"
            finding = "Official Indian registry evidence matches the exact legal name and supplied CIN and reports this incorporation date."
        elif incorporated and candidate["source_type"] == "third_party_directory":
            status = "unverified"
            finding = "A third-party source reports an incorporation date, retained as unverified evidence."
        elif incorporated:
            status = "possible_match"
            finding = "A possible incorporation date is reported by a non-authoritative or incompletely matched source."
        elif incorporation_year:
            status = "possible_match" if candidate["source_type"] in {"official_company_website", "stock_exchange_filing"} else "unverified"
            finding = "The source reports an incorporation year only; no month or day has been inferred."
        else:
            status = "unverified"
            finding = "No incorporation date was attributed because the result did not match the supplied legal entity and CIN."
        findings.append(_evidence(check_type, vendor, result, finding=finding, status=status, matched_entity={
            "incorporation_date": incorporated, "incorporation_year": incorporation_year,
            "company_age_years": age_years,
            "exact_name_match": candidate["exact_name"], "cin_match": candidate["exact_cin"],
        }))
    return findings or [_empty_result(check_type, "No relevant public incorporation-date evidence was found.")]


def research_address(vendor: dict[str, Any], provider: SearchProvider) -> list[dict[str, Any]]:
    check_type = "address_research"
    name = str(vendor.get("vendor_name", "")).strip()
    address = str(vendor.get("address", "")).strip()
    if not address:
        return [_empty_result(check_type, "No vendor address is available to search.")]
    query = f'"{address}" "{name}" {_location(vendor)} India {_priority_domains(vendor)}'
    results = _search_queries(provider, [query], vendor)
    findings = []
    normalized_address = _normalized(address)
    for result in results:
        candidate = _candidate(vendor, result)
        if candidate["excluded"]:
            continue
        address_match = bool(normalized_address and normalized_address in _normalized(candidate["text"]))
        name_match = candidate["exact_name"]
        status = "possible_match" if address_match and name_match else "unverified"
        findings.append(_evidence(check_type, vendor, result,
            finding="The result mentions the supplied address and legal name; this does not establish occupancy or current use." if status == "possible_match" else "The result does not confirm both the supplied legal name and address.",
            status=status, matched_entity={"supplied_address_mentioned": address_match, "exact_name_match": name_match}))
    return findings or [_empty_result(check_type, "No relevant public address evidence was found.")]


_LEVEL_STRENGTH = {
    "official_registry_verified": 0,
    "official_company_document": 1,
    "stock_exchange_filing": 2,
    "third_party_match": 3,
    "unverified": 4,
}


def build_company_identity_summary(vendor: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Consolidate supplied identity and externally supported facts for human review."""
    ranked = sorted(
        (item for item in evidence if item.get("source_url")),
        key=lambda item: (_LEVEL_STRENGTH.get(item.get("verification_level", "unverified"), 99),
                          item.get("source_type", "other"), item.get("source_url", "")),
    )
    corroborated: dict[str, Any] = {
        "legal_name": None,
        "cin": None,
        "address": None,
        "incorporation_year": None,
        "incorporation_date": None,
    }
    for item in ranked:
        matched = item.get("matched_entity") or {}
        if matched.get("exact_name_match") or matched.get("company_name"):
            corroborated["legal_name"] = vendor.get("vendor_name")
        if matched.get("cin_match") or (matched.get("registration_number") and matched.get("registration_number") == vendor.get("registration_number")):
            corroborated["cin"] = vendor.get("registration_number")
        if matched.get("supplied_address_mentioned") and matched.get("exact_name_match"):
            corroborated["address"] = vendor.get("address")
        if matched.get("incorporation_year") and corroborated["incorporation_year"] is None:
            corroborated["incorporation_year"] = matched["incorporation_year"]
        if matched.get("incorporation_date") and corroborated["incorporation_date"] is None:
            corroborated["incorporation_date"] = matched["incorporation_date"]

    strongest_level = next((item.get("verification_level") for item in ranked
                            if item.get("verification_level") != "unverified"), "unverified")
    sources = []
    seen_urls: set[str] = set()
    for item in ranked:
        url = item.get("source_url")
        canonical = _canonical_url(str(url))
        if canonical in seen_urls:
            continue
        seen_urls.add(canonical)
        sources.append({
            "source_url": url,
            "source_type": item.get("source_type"),
            "verification_level": item.get("verification_level", "unverified"),
            "retrieved_at": item.get("retrieved_at"),
            "source_excerpt": (item.get("matched_entity") or {}).get("source_excerpt"),
        })
        if len(sources) == 5:
            break
    return {
        "vendor_id": vendor.get("vendor_id"),
        "supplied": {
            "legal_name": vendor.get("vendor_name"),
            "cin": vendor.get("registration_number"),
            "address": vendor.get("address"),
        },
        "externally_corroborated": corroborated,
        "verification_level": strongest_level,
        "strongest_sources": sources,
        "summary_note": "Evidence summary for human review; supplied values and external corroboration are shown separately. No fraud or payment decision is made.",
    }
