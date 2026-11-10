from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.invoices import router as invoices_router
from app.api.routes.vendors import router as vendors_router
from app.api.routes.network import router as network_router
from app.api.routes.ai import router as ai_router

router = APIRouter()
router.include_router(health_router)
router.include_router(dashboard_router)
router.include_router(invoices_router)
router.include_router(vendors_router)
router.include_router(network_router)
router.include_router(ai_router)
