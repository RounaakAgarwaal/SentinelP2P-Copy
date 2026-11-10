from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response

from app.core.config import settings
from app.repositories.vendors import VendorRepository
from app.schemas.vendors import StartVendorInvestigationResponse, VendorDetailResponse, VendorListResponse
from app.services.vendors import VendorService

router = APIRouter(prefix="/vendors", tags=["vendors"])


def _service() -> VendorService:
    repository = VendorRepository(settings.data_dir, settings.investigation_db)
    return VendorService(repository, data_dir=str(settings.data_dir), investigation_db=str(settings.investigation_db))


@router.get("", response_model=VendorListResponse)
def list_vendors(
    q: str = Query(default="", max_length=200),
    status: Literal["all", "flagged", "clear", "no_invoices"] = "all",
    category: str = Query(default="", max_length=100),
    signal: str = Query(default="", max_length=100),
    sort_by: Literal["vendor_id", "vendor_name", "invoice_count", "total_transaction_value", "flagged_invoice_count", "vendor_category"] = "vendor_name",
    sort_dir: Literal["asc", "desc"] = "asc",
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    result = _service().list_vendors(
        query=q, status=status, category=category, signal=signal,
        sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset,
    )
    if not result["available"]:
        raise HTTPException(status_code=503, detail="Vendor data is unavailable")
    return result


@router.get("/{vendor_id}", response_model=VendorDetailResponse)
def vendor_detail(vendor_id: str) -> dict:
    result = _service().detail(vendor_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return result


@router.post("/{vendor_id}/investigations", response_model=StartVendorInvestigationResponse, status_code=201)
def start_vendor_investigation(vendor_id: str, response: Response) -> dict:
    try:
        result = _service().start_investigation(vendor_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    if not result.get("created"):
        response.status_code = 200
    return result
