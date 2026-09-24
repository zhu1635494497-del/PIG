from __future__ import annotations

from pig.application.errors import ApplicationError
from pig.domain.entities import Node, Source
from pig.domain.enums import NodeKind, RelationshipType
from pig.domain.repositories import UnitOfWork


def external_source_parts(
    uow: UnitOfWork, source: Source, node: Node
) -> tuple[str, ...]:
    """Return evidence names only for a Node materialized under a Folder Source."""

    if source.root_node_id is None:
        raise ApplicationError(
            code="SOURCE_ROOT_REQUIRED", message="Source has no root Node"
        )
    parts: list[str] = []
    current = node
    visited: set[str] = set()
    while current.id != source.root_node_id:
        if current.id in visited:
            raise ApplicationError(
                code="LINEAGE_CYCLE", message="Node ancestry contains a cycle"
            )
        visited.add(current.id)
        relationship = uow.catalog.relationship_for_child(current.id)
        if relationship is None:
            raise ApplicationError(
                code="LINEAGE_INCOMPLETE", message="Node has no parent relationship"
            )
        if relationship.type == RelationshipType.FOLDER_CONTAINS:
            parts.append(current.original_name)
        elif current.id == node.id and node.kind == NodeKind.FILE:
            return ()
        parent = uow.catalog.get_node(relationship.parent_node_id)
        if parent is None:
            raise ApplicationError(
                code="LINEAGE_INCOMPLETE", message="Node parent is missing"
            )
        current = parent
    parts.reverse()
    return tuple(parts)
