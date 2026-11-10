"""Typed response models for the Sentinel AI retrieval foundation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RetrievedSource(BaseModel):
    source_id: str
    source_type: str
    record_type: str
    fields: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class RetrievalGroup(BaseModel):
    records: list[RetrievedSource] = Field(default_factory=list)
    availability: dict[str, Any] = Field(default_factory=dict)
    status: Literal["matched", "no_match", "unavailable"]


class AIRetrievalResponse(BaseModel):
    query: str
    structured: RetrievalGroup
    documents: RetrievalGroup
    status: Literal["matched", "no_match", "unavailable"]
    safety: dict[str, Any]
