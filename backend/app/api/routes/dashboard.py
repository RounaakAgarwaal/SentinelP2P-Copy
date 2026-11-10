from fastapi import APIRouter, Query

from app.core.config import settings
from app.repositories.dashboard import DashboardRepository
from app.schemas.dashboard import (
    DashboardSummaryResponse,
    DetectionOverviewResponse,
    HighRiskVendorsResponse,
    RecentInvestigationsResponse,
    RecentInvoicesResponse,
    RiskDistributionResponse,
)
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _service() -> DashboardService:
    return DashboardService(DashboardRepository(settings.data_dir, settings.investigation_db))


@router.get("/summary", response_model=DashboardSummaryResponse)
def summary() -> dict:
    return _service().summary()


@router.get("/risk-distribution", response_model=RiskDistributionResponse)
def risk_distribution() -> dict:
    return _service().risk_distribution()


@router.get("/detections", response_model=DetectionOverviewResponse)
def detections() -> dict:
    return _service().detection_overview()


@router.get("/recent-invoices", response_model=RecentInvoicesResponse)
def recent_invoices(limit: int = Query(default=10, ge=1, le=100)) -> dict:
    return _service().recent_invoices(limit=limit)


@router.get("/vendors", response_model=HighRiskVendorsResponse)
def vendors(limit: int = Query(default=8, ge=1, le=100)) -> dict:
    return _service().high_risk_vendors(limit=limit)


@router.get("/activity", response_model=RecentInvestigationsResponse)
def activity(limit: int = Query(default=10, ge=1, le=100)) -> dict:
    return _service().recent_investigations(limit=limit)
