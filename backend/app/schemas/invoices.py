from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class InvoiceListItem(BaseModel):
    invoice_id: str
    vendor_id: str | None = None
    vendor_name: str | None = None
    amount: float | None = None
    date: str | None = None
    overall_status: str | None = None
    risk_score: float | None = None
    gnn_prediction: bool | None = None
    signals: list[str] = Field(default_factory=list)
    human_decision: str | None = None
    human_decision_time: str | None = None
    human_decision_status: Literal["decision_recorded", "no_decision_recorded", "unavailable"]


class InvoiceListResponse(BaseModel):
    available: bool
    items: list[InvoiceListItem] = Field(default_factory=list)
    total: int | None = None
    limit: int
    offset: int
    available_signals: list[str] = Field(default_factory=list)
    available_vendors: list[dict[str, str | None]] = Field(default_factory=list)
    sources: dict[str, dict[str, Any]]
    reason: str | None = None


class InvoiceDetailResponse(BaseModel):
    invoice_id: str
    invoice: dict[str, Any]
    overall_status: str | None = None
    vendor_id: str | None = None
    vendor_mapping_conflict: bool = False
    vendor: dict[str, Any] | None = None
    purchase_orders: list[dict[str, Any]] = Field(default_factory=list)
    contracts: list[dict[str, Any]] = Field(default_factory=list)
    detection: dict[str, Any]
    human_decisions: list[dict[str, Any]] = Field(default_factory=list)
    sources: dict[str, dict[str, Any]]


class InvoiceInvestigationsResponse(BaseModel):
    available: bool
    investigations: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = None


class StartInvoiceInvestigationResponse(BaseModel):
    created: bool
    investigation: dict[str, Any]
    message: str
