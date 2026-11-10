from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response

from app.core.config import settings
from app.repositories.invoices import InvoiceRepository
from app.schemas.invoices import (
    InvoiceDetailResponse,
    InvoiceInvestigationsResponse,
    InvoiceListResponse,
    StartInvoiceInvestigationResponse,
)
from app.services.invoices import InvoiceService

router = APIRouter(prefix="/invoices", tags=["invoices"])


def _service() -> InvoiceService:
    repository = InvoiceRepository(settings.data_dir, settings.investigation_db)
    return InvoiceService(repository, data_dir=str(settings.data_dir), investigation_db=str(settings.investigation_db))


@router.get("", response_model=InvoiceListResponse)
def list_invoices(
    q: str = Query(default="", max_length=200),
    status: Literal["all", "flagged", "clear"] = "all",
    vendor_id: str = Query(default="", max_length=100),
    signal: str = Query(default="", max_length=100),
    sort_by: Literal["invoice_id", "vendor_name", "amount", "date", "risk_score", "overall_status"] = "date",
    sort_dir: Literal["asc", "desc"] = "desc",
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    result = _service().list_invoices(
        query=q, status=status, vendor_filter=vendor_id, signal=signal,
        sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset,
    )
    if not result["available"]:
        raise HTTPException(status_code=503, detail="Invoice dashboard data is unavailable")
    return result


@router.get("/{invoice_id}", response_model=InvoiceDetailResponse)
def invoice_detail(invoice_id: str) -> dict:
    result = _service().detail(invoice_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return result


@router.get("/{invoice_id}/investigations", response_model=InvoiceInvestigationsResponse)
def invoice_investigations(invoice_id: str) -> dict:
    result = _service().investigations(invoice_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return result


@router.post("/{invoice_id}/investigations", response_model=StartInvoiceInvestigationResponse, status_code=201)
def start_invoice_investigation(invoice_id: str, response: Response) -> dict:
    try:
        result = _service().start_investigation(invoice_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if not result.get("created"):
        response.status_code = 200
    return result
