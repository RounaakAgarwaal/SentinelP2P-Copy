from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceAvailability(BaseModel):
    available: bool
    reason: str | None = None
    missing_columns: list[str] = Field(default_factory=list)
    row_count: int | None = None
    modified_at: str | None = None


class DashboardMetric(BaseModel):
    value: int | float | None = None
    available: bool
    unit: Literal["count", "ratio"] | None = None
    definition: str
    reason: str | None = None


class SummaryMetrics(BaseModel):
    total_invoices: DashboardMetric
    flagged_invoices: DashboardMetric
    flagged_invoice_share: DashboardMetric
    total_vendors: DashboardMetric
    pending_audit_reviews: DashboardMetric
    audited_invoices: DashboardMetric


class DashboardSummaryResponse(BaseModel):
    metrics: SummaryMetrics
    source_files_updated_at: str | None = None
    sources: dict[str, SourceAvailability]
    notes: list[str] = Field(default_factory=list)


class RiskBin(BaseModel):
    label: str
    min_score: float | None = None
    max_score: float | None = None
    invoice_count: int


class RiskDistributionResponse(BaseModel):
    available: bool
    kind: Literal["gnn_score_quartiles", "review_flag_counts", "unavailable"]
    bins: list[RiskBin] = Field(default_factory=list)
    note: str
    source: SourceAvailability


class RuleCount(BaseModel):
    rule: str
    flagged_invoices: int


class DetectionChannel(BaseModel):
    available: bool
    reason: str | None = None
    invoice_count: int | None = None
    detail: str | None = None


class DetectionOverviewResponse(BaseModel):
    invoice_count: int | None = None
    rules: DetectionChannel
    rule_counts: list[RuleCount] = Field(default_factory=list)
    gnn: DetectionChannel
    rag: DetectionChannel
    rag_status_counts: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class RecentInvoice(BaseModel):
    invoice_id: str
    vendor_id: str | None = None
    vendor_name: str | None = None
    amount: float | None = None
    invoice_date: str | None = None
    risk_score: float | None = None
    detection_sources: list[str] = Field(default_factory=list)
    review_status: Literal["decision_recorded", "no_decision_recorded", "unavailable"]
    human_decision: str | None = None


class RecentInvoicesResponse(BaseModel):
    available: bool
    items: list[RecentInvoice] = Field(default_factory=list)
    reason: str | None = None
    sources: dict[str, SourceAvailability]
    note: str


class HighRiskVendor(BaseModel):
    vendor_id: str
    vendor_name: str | None = None
    related_invoice_count: int
    flagged_invoice_count: int
    max_gnn_score: float | None = None
    risk_indicator: str
    investigation_status: str | None = None
    investigation_recorded: bool | None = None


class HighRiskVendorsResponse(BaseModel):
    available: bool
    items: list[HighRiskVendor] = Field(default_factory=list)
    reason: str | None = None
    sources: dict[str, SourceAvailability]
    note: str


class InvestigationItem(BaseModel):
    investigation_id: str
    vendor_id: str
    vendor_name: str | None = None
    invoice_id: str | None = None
    status: str
    created_at: str
    completed_at: str | None = None


class HumanDecisionItem(BaseModel):
    time: str
    invoice_id: str
    vendor_id: str
    decision: str


class RecentInvestigationsResponse(BaseModel):
    investigations_available: bool
    investigations: list[InvestigationItem] = Field(default_factory=list)
    investigations_reason: str | None = None
    decisions_available: bool
    human_decisions: list[HumanDecisionItem] = Field(default_factory=list)
    decisions_reason: str | None = None
    note: str
