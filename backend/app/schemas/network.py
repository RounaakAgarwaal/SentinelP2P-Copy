from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NetworkNode(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class NetworkEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship_type: str
    label: str
    details: dict[str, Any] = Field(default_factory=dict)


class NetworkGraphResponse(BaseModel):
    available: bool
    nodes: list[NetworkNode] = Field(default_factory=list)
    edges: list[NetworkEdge] = Field(default_factory=list)
    total_nodes: int
    total_edges: int
    available_relationship_types: list[str] = Field(default_factory=list)
    sources: dict[str, dict[str, Any]] = Field(default_factory=dict)


class NetworkConnection(BaseModel):
    node: NetworkNode
    relationship: NetworkEdge


class NetworkNodeDetailResponse(BaseModel):
    node: NetworkNode
    connections: list[NetworkConnection] = Field(default_factory=list)
    connection_count: int
    sources: dict[str, dict[str, Any]] = Field(default_factory=dict)
