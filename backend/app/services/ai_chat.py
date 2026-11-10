"""Chat orchestration that keeps retrieval, generation and citations separate."""

from __future__ import annotations

import re
from typing import Any

from app.services.answer_provider import AnswerProvider, UnconfiguredAnswerProvider
from app.services.ollama_provider import OllamaProviderError
from app.services.query_understanding import identify_intent, is_greeting


_PROHIBITED_DECISION_PATTERNS = (
    re.compile(r"\b(?:vendor|supplier|company)\b.{0,80}\b(?:fraudulent|legitimate)\b", re.IGNORECASE),
    re.compile(r"\b(?:block|release|approve|reject|execute|withhold)\b.{0,60}\b(?:payment|invoice)\b", re.IGNORECASE),
    re.compile(r"\b(?:payment|invoice)\b.{0,60}\b(?:should|must|recommend|recommendation is to)\b.{0,30}\b(?:block|release|approve|reject|pay|withhold)\b", re.IGNORECASE),
)


class AIChatService:
    def __init__(self, retrieval_service: Any, answer_provider: AnswerProvider | None = None,
                 entity_resolver: Any | None = None) -> None:
        self.retrieval_service = retrieval_service
        self.answer_provider = answer_provider or UnconfiguredAnswerProvider()
        self.entity_resolver = entity_resolver

    def respond(self, request: dict[str, Any]) -> dict[str, Any]:
        message = request["message"].strip()
        history = [item if isinstance(item, dict) else item.dict() for item in request.get("conversation_history", [])]

        safety = {
            "fraud_conclusion": None,
            "payment_decision": None,
            "history_is_evidence": False,
        }
        if is_greeting(message):
            return {
                "status": "greeting", "conversation_id": request.get("conversation_id"),
                "answer": "Hello! I can help you look up invoices, vendors, purchase orders, contracts, relationships, and investigation evidence.",
                "message": "Hello! I can help you look up invoices, vendors, purchase orders, contracts, relationships, and investigation evidence.",
                "retrieval_status": "no_match", "sources": [], "citations": [],
                "source_availability": {}, "safety": safety,
            }

        intent = identify_intent(message)
        if intent.unsupported:
            return {
                "status": "unsupported_question", "conversation_id": request.get("conversation_id"),
                "answer": None,
                "message": "I can help retrieve SentinelP2P invoice, vendor, purchase order, contract, relationship, detector, audit, or investigation records. This question is outside those supported data sources.",
                "retrieval_status": "no_match", "sources": [], "citations": [],
                "source_availability": {}, "safety": safety,
            }

        resolved_entity = None
        if intent.entity_type and intent.identifier and self.entity_resolver:
            resolved_entity = self.entity_resolver(intent.entity_type, intent.identifier)
            if not resolved_entity.get("available"):
                return {
                    "status": "retrieval_unavailable", "conversation_id": request.get("conversation_id"),
                    "answer": None,
                    "message": f"The {intent.entity_type.replace('_', ' ')} source is unavailable, so I could not check identifier {intent.identifier}.",
                    "retrieval_status": "unavailable", "sources": [], "citations": [],
                    "source_availability": {"identifier_lookup": {"available": False,
                        "reason": resolved_entity.get("reason")}}, "safety": safety,
                }
            if not resolved_entity.get("found"):
                return {
                    "status": "entity_not_found", "conversation_id": request.get("conversation_id"),
                    "answer": None,
                    "message": f"No exact {intent.entity_type.replace('_', ' ')} record was found for {intent.identifier}. I did not substitute a similar identifier.",
                    "retrieval_status": "no_match", "sources": [], "citations": [],
                    "source_availability": {"identifier_lookup": {"available": True,
                        "reason": "record_not_found"}}, "safety": safety,
                }
            intent = type(intent)(intent.kind, intent.entity_type, resolved_entity.get("resolved_id"), False)

        # The current question is the retrieval query. History is passed only to
        # a future answer provider as conversational context, never treated as evidence.
        if resolved_entity:
            lookup_kwargs = {
                "entity_type": intent.entity_type,
                "entity_id": intent.identifier,
                "intent": intent.kind,
                "limit": 8,
            }
            if intent.entity_type == "invoice":
                lookup_kwargs["invoice_id"] = intent.identifier
            elif intent.entity_type == "vendor":
                lookup_kwargs["vendor_id"] = intent.identifier
            retrieved = self.retrieval_service.retrieve(message, **lookup_kwargs)
        elif self.entity_resolver:
            retrieved = self.retrieval_service.retrieve(message, intent=intent.kind, limit=8)
        else:
            retrieved = self.retrieval_service.retrieve(message)
        source_records = [*retrieved.get("structured", {}).get("records", []),
                          *retrieved.get("documents", {}).get("records", [])]
        citations = [{
            "source_id": source["source_id"],
            "source_type": source["source_type"],
            "record_type": source["record_type"],
            "provenance": source.get("provenance", {}),
        } for source in source_records if source.get("source_id")]
        retrieval_status = retrieved.get("status", "unavailable")
        availability = {
            "structured": retrieved.get("structured", {}).get("availability", {}),
            "documents": retrieved.get("documents", {}).get("availability", {}),
        }
        if not self.answer_provider.configured:
            detail = (
                "No matching records were retrieved; missing or unavailable sources do not establish a negative finding. "
                if retrieval_status != "matched" else
                "Relevant records were retrieved, but natural-language answer generation is not configured. "
            )
            return {
                "status": "provider_not_configured",
                "conversation_id": request.get("conversation_id"),
                "answer": None,
                "message": detail + "Retrieved records and citations are included for review.",
                "retrieval_status": retrieval_status,
                "sources": source_records,
                "citations": citations,
                "source_availability": availability,
                "safety": safety,
            }

        if not source_records:
            return {
                "status": "retrieval_unavailable",
                "conversation_id": request.get("conversation_id"),
                "answer": None,
                "message": "No supporting records were retrieved. Missing or unavailable records do not establish a negative finding, so no model answer was generated.",
                "retrieval_status": retrieval_status,
                "sources": [],
                "citations": [],
                "source_availability": availability,
                "safety": safety,
            }

        try:
            generated = self.answer_provider.generate(
                question=message,
                conversation_history=[{"role": item["role"], "content": item["content"]} for item in history],
                sources=source_records,
            )
        except OllamaProviderError as error:
            return {
                "status": "provider_error", "error_code": error.code,
                "conversation_id": request.get("conversation_id"), "answer": None,
                "message": error.public_message, "retrieval_status": retrieval_status,
                "sources": source_records, "citations": citations,
                "source_availability": availability, "safety": safety,
            }
        valid_ids = {source["source_id"] for source in source_records}
        raw_cited_ids = generated.get("cited_source_ids")
        if not isinstance(raw_cited_ids, list) or any(not isinstance(source_id, str) for source_id in raw_cited_ids):
            raw_cited_ids = []
        if any(source_id not in valid_ids for source_id in raw_cited_ids):
            return {
                "status": "grounding_failed", "conversation_id": request.get("conversation_id"),
                "answer": None, "message": "The answer included a citation outside the retrieved sources, so no answer was returned.",
                "retrieval_status": retrieval_status, "sources": source_records, "citations": citations,
                "source_availability": availability, "safety": safety,
            }
        cited_ids = list(dict.fromkeys(raw_cited_ids))
        answer_text = generated.get("answer")
        if isinstance(answer_text, str) and any(pattern.search(answer_text) for pattern in _PROHIBITED_DECISION_PATTERNS):
            return {
                "status": "grounding_failed", "conversation_id": request.get("conversation_id"),
                "answer": None, "message": "The answer contained a prohibited fraud classification or payment action, so it was withheld.",
                "retrieval_status": retrieval_status, "sources": source_records, "citations": citations,
                "source_availability": availability, "safety": safety,
            }
        if generated.get("insufficient_evidence") is True:
            generated["answer"] = "The retrieved evidence is insufficient to answer this question."
            cited_ids = []
        if generated.get("answer") and not cited_ids:
            if generated.get("insufficient_evidence") is not True:
                return {
                    "status": "grounding_failed", "conversation_id": request.get("conversation_id"),
                    "answer": None, "message": "The answer provider did not cite retrieved sources, so no answer was returned.",
                    "retrieval_status": retrieval_status, "sources": source_records, "citations": citations,
                    "source_availability": availability, "safety": safety,
                }
        citation_by_id = {citation["source_id"]: citation for citation in citations}
        return {
            "status": "answered", "conversation_id": request.get("conversation_id"),
            "answer": generated.get("answer"), "message": "Answer grounded in the cited retrieved records.",
            "retrieval_status": retrieval_status, "sources": source_records,
            "citations": [citation_by_id[source_id] for source_id in cited_ids],
            "source_availability": availability, "safety": safety,
        }
