"""Schemas for Sentinel AI chat requests and grounded response metadata."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, constr, validator

from app.schemas.ai_retrieval import RetrievedSource


ChatText = constr(strip_whitespace=True, min_length=1, max_length=4000)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: ChatText


class AIChatRequest(BaseModel):
    message: ChatText
    conversation_history: list[ChatMessage] = Field(default_factory=list)
    conversation_id: constr(strip_whitespace=True, min_length=1, max_length=128) | None = None

    @validator("conversation_history")
    def history_is_bounded(cls, history: list[ChatMessage]) -> list[ChatMessage]:
        if len(history) > 12:
            raise ValueError("conversation_history may contain at most 12 messages")
        return history


class ChatCitation(BaseModel):
    source_id: str
    source_type: str
    record_type: str
    provenance: dict[str, Any] = Field(default_factory=dict)


class AIChatResponse(BaseModel):
    status: Literal["greeting", "unsupported_question", "entity_not_found", "provider_not_configured", "provider_error", "answered", "retrieval_unavailable", "grounding_failed"]
    conversation_id: str | None = None
    answer: str | None = None
    error_code: str | None = None
    message: str
    retrieval_status: Literal["matched", "no_match", "unavailable"]
    sources: list[RetrievedSource] = Field(default_factory=list)
    citations: list[ChatCitation] = Field(default_factory=list)
    source_availability: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)
