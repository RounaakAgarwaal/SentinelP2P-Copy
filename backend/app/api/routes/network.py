from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.repositories.network import NetworkRepository
from app.schemas.network import NetworkGraphResponse, NetworkNodeDetailResponse
from app.services.network import NetworkService

router = APIRouter(prefix="/network", tags=["vendor network"])
EntityType = Literal["employee", "vendor", "purchase_order", "invoice", "contract"]


def _service() -> NetworkService:
    return NetworkService(NetworkRepository(settings.data_dir))


@router.get("", response_model=NetworkGraphResponse)
def network_graph(
    q: str = Query(default="", max_length=200),
    entity_type: list[EntityType] = Query(default=[]),
    relationship_type: list[str] = Query(default=[]),
    overview: bool = Query(default=False),
) -> dict:
    return _service().graph(query=q, entity_types=entity_type, relationship_types=relationship_type, overview=overview)


@router.get("/nodes/{entity_type}/{entity_id}", response_model=NetworkNodeDetailResponse)
def network_node_detail(
    entity_type: EntityType,
    entity_id: str,
) -> dict:
    if not entity_id or len(entity_id) > 200:
        raise HTTPException(status_code=422, detail="Invalid entity ID")
    result = _service().node_detail(entity_type, entity_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Network entity not found")
    return result
