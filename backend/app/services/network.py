from __future__ import annotations

from typing import Any

from app.repositories.network import NetworkRepository


class NetworkService:
    def __init__(self, repository: NetworkRepository) -> None:
        self.repository = repository

    def graph(self, **filters: Any) -> dict[str, Any]:
        return self.repository.graph(**filters)

    def node_detail(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        return self.repository.node_detail(entity_type, entity_id)
