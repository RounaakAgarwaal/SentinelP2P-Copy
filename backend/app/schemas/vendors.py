from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class VendorListItem(BaseModel):
    vendor_id: str
    vendor_name: str | None = None
    email: str | None = None
    phone: str | None = None
    registration_number: str | None = None
    bank_account: str | None = None
    vendor_category: str | None = None
    invoice_count: int | None = None
    total_transaction_value: float | None = None
    flagged_invoice_count: int | None = None
    risk_indicators: list[dict[str, Any]] | None = None
    risk_indicators_available: bool


class VendorListResponse(BaseModel):
    available: bool
    items: list[VendorListItem] = Field(default_factory=list)
    total: int | None = None
    limit: int
    offset: int
    available_categories: list[str] = Field(default_factory=list)
    available_signals: list[str] = Field(default_factory=list)
    sources: dict[str, dict[str, Any]]
    invoice_metrics_available: bool
    reason: str | None = None


class VendorDetailResponse(BaseModel):
    vendor_id: str
    vendor: dict[str, Any]
    invoice_count: int | None = None
    total_transaction_value: float | None = None
    flagged_invoice_count: int | None = None
    risk_indicators: list[str] | None = None
    risk_indicators_available: bool
    invoices: list[dict[str, Any]] = Field(default_factory=list)
    purchase_orders: list[dict[str, Any]] = Field(default_factory=list)
    contracts: list[dict[str, Any]] = Field(default_factory=list)
    internal_verification_findings: list[dict[str, Any]] = Field(default_factory=list)
    investigations: dict[str, Any]
    human_decisions: list[dict[str, Any]] = Field(default_factory=list)
    sources: dict[str, dict[str, Any]]


class StartVendorInvestigationResponse(BaseModel):
    created: bool
    investigation: dict[str, Any]
    message: str
