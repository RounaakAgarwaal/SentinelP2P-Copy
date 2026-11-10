"""Read-only relationship graph assembled from the existing source CSVs."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.repositories.dashboard import DashboardRepository


ENTITY_FILES: dict[str, tuple[str, str]] = {
    "employee": ("employees.csv", "employee_id"),
    "vendor": ("vendors.csv", "vendor_id"),
    "purchase_order": ("purchase_orders.csv", "po_id"),
    "invoice": ("invoices.csv", "invoice_id"),
    "contract": ("contracts.csv", "contract_id"),
}
PLACEHOLDERS = {"", "na", "n/a", "none", "null", "nan", "unknown", "not available"}


def _value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.casefold() in PLACEHOLDERS else text


def _normalized(value: Any, *, field: str) -> str:
    text = _value(value) or ""
    if field == "phone":
        return re.sub(r"\D", "", text)
    if field == "email":
        # Email punctuation is significant; compare only case-insensitively.
        return text.casefold()
    return "".join(char for char in text.casefold() if char.isalnum())


def _mask_bank(value: Any) -> str | None:
    raw = _value(value)
    if raw is None:
        return None
    compact = re.sub(r"\s+", "", raw)
    return f"••••{compact[-4:]}" if len(compact) >= 4 else "••••"


class NetworkRepository:
    """Builds graph records from CSV IDs and exact normalized vendor values."""

    def __init__(self, data_dir: str | Path) -> None:
        self.source = DashboardRepository(data_dir, Path(data_dir) / "investigations.sqlite3")

    def _tables(self) -> dict[str, Any]:
        required = {
            "employee": {"employee_id"},
            "vendor": {"vendor_id"},
            "purchase_order": {"po_id", "vendor_id"},
            "invoice": {"invoice_id", "po_id"},
            "contract": {"contract_id", "vendor_id"},
        }
        return {
            kind: self.source.csv_table(filename, required_columns=required[kind])
            for kind, (filename, _) in ENTITY_FILES.items()
        }

    @staticmethod
    def _node(kind: str, row: dict[str, Any], identifier: str) -> dict[str, Any]:
        props = {str(key): _value(value) for key, value in row.items()}
        if kind == "vendor" and "bank_account" in props:
            props["bank_account"] = _mask_bank(props["bank_account"])
        labels = {
            "employee": ("name", "employee_id"),
            "vendor": ("vendor_name", "vendor_id"),
            "purchase_order": ("po_id", "po_id"),
            "invoice": ("invoice_id", "invoice_id"),
            "contract": ("contract_id", "contract_id"),
        }
        label_key, _ = labels[kind]
        return {
            "id": f"{kind}:{identifier}", "entity_type": kind,
            "entity_id": identifier, "label": _value(row.get(label_key)) or identifier,
            "properties": props,
        }

    def graph(
        self,
        *,
        query: str = "",
        entity_types: list[str] | None = None,
        relationship_types: list[str] | None = None,
        overview: bool = False,
    ) -> dict[str, Any]:
        tables = self._tables()
        nodes: dict[str, dict[str, Any]] = {}
        rows_by_type: dict[str, list[dict[str, Any]]] = {}
        id_counts: dict[str, dict[str, int]] = {}
        for kind, (_, id_column) in ENTITY_FILES.items():
            table = tables[kind]
            rows_by_type[kind] = table.rows if table.available else []
            counts: defaultdict[str, int] = defaultdict(int)
            for row in rows_by_type[kind]:
                identifier = _value(row.get(id_column))
                if identifier:
                    counts[identifier] += 1
            id_counts[kind] = dict(counts)
            # Duplicate primary keys are ambiguous. Keep a display node but omit
            # any relationship that would rely on that identifier.
            for row in rows_by_type[kind]:
                identifier = _value(row.get(id_column))
                if identifier and f"{kind}:{identifier}" not in nodes:
                    nodes[f"{kind}:{identifier}"] = self._node(kind, row, identifier)

        edges: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}

        def add(source_kind: str, source_id: Any, target_kind: str, target_id: Any,
                relationship: str, matched_field: str | None = None,
                matched_value: str | None = None) -> None:
            source = _value(source_id)
            target = _value(target_id)
            if not source or not target:
                return
            if id_counts.get(source_kind, {}).get(source) != 1 or id_counts.get(target_kind, {}).get(target) != 1:
                return
            source_node, target_node = f"{source_kind}:{source}", f"{target_kind}:{target}"
            if source_node not in nodes or target_node not in nodes:
                return
            key = (source_node, target_node, relationship, matched_field)
            edges.setdefault(key, {
                "id": "|".join(str(part) for part in key),
                "source": source_node, "target": target_node,
                "relationship_type": relationship, "label": relationship.replace("_", " "),
                "details": {
                    "matched_field": matched_field,
                    "matched_value": matched_value,
                    "source_entity_id": source,
                    "target_entity_id": target,
                },
            })

        for vendor in rows_by_type["vendor"]:
            add("employee", vendor.get("created_by_employee_id"), "vendor", vendor.get("vendor_id"), "created")
        for po in rows_by_type["purchase_order"]:
            add("employee", po.get("created_by_employee_id"), "purchase_order", po.get("po_id"), "raised")
            add("employee", po.get("approved_by_employee_id"), "purchase_order", po.get("po_id"), "approved")
            add("vendor", po.get("vendor_id"), "purchase_order", po.get("po_id"), "received")
        for invoice in rows_by_type["invoice"]:
            add("purchase_order", invoice.get("po_id"), "invoice", invoice.get("invoice_id"), "has_invoice")
            add("employee", invoice.get("submitted_by_employee_id"), "invoice", invoice.get("invoice_id"), "submitted")
        for contract in rows_by_type["contract"]:
            add("vendor", contract.get("vendor_id"), "contract", contract.get("contract_id"), "has_contract")

        vendors = rows_by_type["vendor"]
        for field in ("phone", "email", "registration_number", "bank_account"):
            groups: defaultdict[str, list[str]] = defaultdict(list)
            for vendor in vendors:
                identifier = _value(vendor.get("vendor_id"))
                raw = _value(vendor.get(field))
                normalized = _normalized(raw, field=field)
                minimum_length = 7 if field == "phone" else 1
                if identifier and normalized and len(normalized) >= minimum_length:
                    groups[normalized].append(identifier)
            for normalized, identifiers in groups.items():
                unique = sorted(set(identifiers))
                if len(unique) < 2:
                    continue
                display_value = _mask_bank(normalized) if field == "bank_account" else None
                relationship = f"shared_{field}"
                for index, left in enumerate(unique):
                    for right in unique[index + 1:]:
                        add("vendor", left, "vendor", right, relationship, field, display_value)

        available_nodes = list(nodes.values())
        available_edges = list(edges.values())
        available_relationship_types = sorted({edge["relationship_type"] for edge in available_edges})
        requested_types = set(entity_types or [])
        requested_relationships = set(relationship_types or [])
        if requested_types:
            available_nodes = [node for node in available_nodes if node["entity_type"] in requested_types]
        node_ids = {node["id"] for node in available_nodes}
        if requested_relationships:
            available_edges = [edge for edge in available_edges if edge["relationship_type"] in requested_relationships]
            connected_ids = {edge["source"] for edge in available_edges} | {edge["target"] for edge in available_edges}
            available_nodes = [node for node in available_nodes if node["id"] in connected_ids]
            node_ids = {node["id"] for node in available_nodes}
        available_edges = [edge for edge in available_edges if edge["source"] in node_ids and edge["target"] in node_ids]
        if query.strip():
            needle = query.casefold().strip()
            matching_ids = {
                node["id"] for node in available_nodes
                if needle in " ".join(str(value or "") for value in [node["label"], node["entity_id"], *node["properties"].values()]).casefold()
            }
            neighbor_ids = {
                edge["target"] if edge["source"] in matching_ids else edge["source"]
                for edge in available_edges
                if edge["source"] in matching_ids or edge["target"] in matching_ids
            }
            node_ids = matching_ids | neighbor_ids
            available_nodes = [node for node in available_nodes if node["id"] in node_ids]
            available_edges = [edge for edge in available_edges if edge["source"] in node_ids and edge["target"] in node_ids]
        elif overview and available_nodes:
            # Build a readable connected slice around vendor records rather than
            # selecting high-degree nodes alone (which can select employees
            # without any of their vendor/PO neighbors and produce no edges).
            degree: defaultdict[str, int] = defaultdict(int)
            adjacent: defaultdict[str, set[str]] = defaultdict(set)
            for edge in available_edges:
                degree[edge["source"]] += 1
                degree[edge["target"]] += 1
                adjacent[edge["source"]].add(edge["target"])
                adjacent[edge["target"]].add(edge["source"])
            seeds = [node for node in available_nodes if node["entity_type"] == "vendor"]
            if not seeds:
                seeds = available_nodes
            seeds.sort(key=lambda node: (-degree[node["id"]], node["id"]))
            chosen: set[str] = set()
            for seed in seeds:
                first_hop = adjacent[seed["id"]]
                second_hop = {neighbor for first in first_hop for neighbor in adjacent[first]}
                proposed = chosen | {seed["id"]} | first_hop | second_hop
                if len(proposed) > 70 and chosen:
                    break
                chosen = proposed
            available_nodes = [node for node in available_nodes if node["id"] in chosen]
            chosen_ids = {node["id"] for node in available_nodes}
            available_edges = [edge for edge in available_edges if edge["source"] in chosen_ids and edge["target"] in chosen_ids]
        available_nodes.sort(key=lambda node: (node["entity_type"], node["entity_id"]))
        available_edges.sort(key=lambda edge: (edge["relationship_type"], edge["source"], edge["target"]))
        return {
            "available": any(tables[kind].available for kind in ENTITY_FILES),
            "nodes": available_nodes,
            "edges": available_edges,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "available_relationship_types": available_relationship_types,
            "sources": {
                kind: {"available": tables[kind].available, "reason": tables[kind].reason,
                       "missing_columns": list(tables[kind].missing_columns), "row_count": len(rows_by_type[kind])}
                for kind in ENTITY_FILES
            },
        }

    def node_detail(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        graph = self.graph()
        node_key = f"{entity_type}:{entity_id}"
        node = next((item for item in graph["nodes"] if item["id"] == node_key), None)
        if node is None:
            return None
        edges = [edge for edge in graph["edges"] if edge["source"] == node_key or edge["target"] == node_key]
        index = {item["id"]: item for item in graph["nodes"]}
        connected = []
        for edge in edges:
            other_id = edge["target"] if edge["source"] == node_key else edge["source"]
            connected.append({"node": index[other_id], "relationship": edge})
        return {"node": node, "connections": connected, "connection_count": len(connected), "sources": graph["sources"]}
