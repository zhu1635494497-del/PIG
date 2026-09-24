from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional, Sequence

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from pig.domain import entities, enums
from pig.domain.exceptions import (
    ConcurrentStateError,
    EntityNotFoundError,
    InvariantViolationError,
)
from pig.domain.transitions import require_project_transition, require_source_transition
from pig.infrastructure.database import models


def _project_from_model(row: models.ProjectModel) -> entities.Project:
    return entities.Project(
        id=row.id,
        name=row.name,
        description=row.description,
        status=row.status,
        workspace_locator=row.workspace_locator,
        model_version=row.model_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        workspace_revision=row.workspace_revision,
    )


def _source_from_model(
    row: models.SourceModel, root_node_id: Optional[str]
) -> entities.Source:
    return entities.Source(
        id=row.id,
        project_id=row.project_id,
        snapshot_id=row.snapshot_id,
        kind=row.kind,
        display_name=row.display_name,
        status=row.status,
        created_at=row.created_at,
        root_node_id=root_node_id,
    )


def _node_from_model(row: models.NodeModel) -> entities.Node:
    return entities.Node(
        id=row.id,
        project_id=row.project_id,
        source_id=row.source_id,
        kind=row.kind,
        format=row.format,
        original_name=row.original_name,
        display_name=row.display_name,
        logical_path=row.logical_path,
        depth=row.depth,
        media_type=row.media_type,
        declared_size=row.declared_size,
        status=row.status,
        detection_method=row.detection_method,
        detection_confidence=row.detection_confidence,
        detection_details=dict(row.detection_details),
        discovery_key=row.discovery_key,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _artifact_from_model(row: models.ArtifactModel) -> entities.Artifact:
    return entities.Artifact(
        id=row.id,
        project_id=row.project_id,
        node_id=row.node_id,
        role=row.role,
        scope=row.scope,
        locator=row.locator,
        size=row.size,
        sha256=row.sha256,
        integrity_status=row.integrity_status,
        observed_at=row.observed_at,
        created_at=row.created_at,
    )


def _relationship_from_model(
    row: models.NodeRelationshipModel,
) -> entities.NodeRelationship:
    return entities.NodeRelationship(
        id=row.id,
        project_id=row.project_id,
        parent_node_id=row.parent_node_id,
        child_node_id=row.child_node_id,
        type=row.type,
        ordinal=row.ordinal,
        discovery_key=row.discovery_key,
        created_by_job_id=row.created_by_job_id,
        created_at=row.created_at,
    )


def _entry_locator_from_model(
    row: models.SourceEntryLocatorModel,
) -> entities.SourceEntryLocator:
    return entities.SourceEntryLocator(
        relationship_id=row.relationship_id,
        project_id=row.project_id,
        child_node_id=row.child_node_id,
        kind=row.kind,
        snapshot_entry_id=row.snapshot_entry_id,
        member_ordinal=row.member_ordinal,
        expected_name=row.expected_name,
        member_role=row.member_role,
        created_at=row.created_at,
    )


def _lineage_from_model(
    row: models.LineageRecordModel,
) -> entities.LineageRecord:
    return entities.LineageRecord(
        project_id=row.project_id,
        ancestor_node_id=row.ancestor_node_id,
        descendant_node_id=row.descendant_node_id,
        distance=row.distance,
    )


def _metadata_from_model(row: models.NodeMetadataModel) -> entities.NodeMetadata:
    return entities.NodeMetadata(
        id=row.id,
        project_id=row.project_id,
        node_id=row.node_id,
        namespace=row.namespace,
        key=row.key,
        value_type=row.value_type,
        value_text=row.value_text,
        value_integer=row.value_integer,
        value_real=row.value_real,
        value_boolean=row.value_boolean,
        value_datetime=row.value_datetime,
        value_json=row.value_json,
        provenance=row.provenance,
        observed_at=row.observed_at,
        created_at=row.created_at,
    )


def _job_from_model(row: models.ProcessingJobModel) -> entities.ProcessingJob:
    return entities.ProcessingJob(
        id=row.id,
        project_id=row.project_id,
        import_session_id=row.import_session_id,
        type=row.type,
        status=row.status,
        requested_by=row.requested_by,
        policy_snapshot=dict(row.policy_snapshot),
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        warning_count=row.warning_count,
        error_count=row.error_count,
    )


def _attempt_from_model(
    row: models.ProcessingAttemptModel,
) -> entities.ProcessingAttempt:
    error = None
    if row.error_code is not None:
        error = entities.ProcessingError(
            code=row.error_code,
            category=row.error_category,
            stage=row.error_stage,
            message=row.error_message,
            retryable=row.error_retryable,
            technical_reference=row.technical_reference,
        )
    return entities.ProcessingAttempt(
        id=row.id,
        project_id=row.project_id,
        job_id=row.job_id,
        node_id=row.node_id,
        attempt_number=row.attempt_number,
        status=row.status,
        stage=row.stage,
        handler_name=row.handler_name,
        handler_version=row.handler_version,
        backend_name=row.backend_name,
        backend_version=row.backend_version,
        backend_sha256=row.backend_sha256,
        queued_at=row.queued_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error=error,
    )


def _event_from_model(row: models.ProcessingEventModel) -> entities.ProcessingEvent:
    return entities.ProcessingEvent(
        id=row.id,
        event_type=row.event_type,
        project_id=row.project_id,
        source_id=row.source_id,
        node_id=row.node_id,
        job_id=row.job_id,
        attempt_id=row.attempt_id,
        import_session_id=row.import_session_id,
        snapshot_id=row.snapshot_id,
        workspace_item_id=row.workspace_item_id,
        working_artifact_id=row.working_artifact_id,
        actor=row.actor,
        occurred_at=row.occurred_at,
        severity=row.severity,
        previous_status=row.previous_status,
        new_status=row.new_status,
        error_code=row.error_code,
        details=dict(row.details),
        correlation_id=row.correlation_id,
    )


class SqlAlchemyProjectRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, project: entities.Project) -> None:
        row = models.ProjectModel(
                id=project.id,
                singleton_key=1,
                name=project.name,
                description=project.description,
                status=project.status,
                workspace_locator=project.workspace_locator,
                model_version=project.model_version,
                created_at=project.created_at,
                updated_at=project.updated_at,
                workspace_revision=project.workspace_revision,
        )
        self._session.add(row)
        self._session.flush([row])

    def get(self, project_id: str) -> Optional[entities.Project]:
        row = self._session.get(models.ProjectModel, project_id)
        return None if row is None else _project_from_model(row)

    def get_singleton(self) -> Optional[entities.Project]:
        row = self._session.scalar(
            select(models.ProjectModel).where(models.ProjectModel.singleton_key == 1)
        )
        return None if row is None else _project_from_model(row)

    def update_status(
        self,
        project_id: str,
        expected_status: enums.ProjectStatus,
        new_status: enums.ProjectStatus,
        updated_at: datetime,
    ) -> entities.Project:
        row = self._session.get(models.ProjectModel, project_id)
        if row is None:
            raise EntityNotFoundError(f"project not found: {project_id}")
        if row.status != expected_status:
            raise ConcurrentStateError(
                "project status changed concurrently: "
                f"expected {expected_status.value}, found {row.status.value}"
            )
        require_project_transition(expected_status, new_status)
        row.status = new_status
        row.updated_at = updated_at
        self._session.flush([row])
        return _project_from_model(row)

    def advance_workspace_revision(
        self,
        project_id: str,
        expected_revision: int,
        *,
        updated_at: datetime,
    ) -> entities.Project:
        result = self._session.execute(
            update(models.ProjectModel)
            .where(
                models.ProjectModel.id == project_id,
                models.ProjectModel.workspace_revision == expected_revision,
            )
            .values(
                workspace_revision=expected_revision + 1,
                updated_at=updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            existing = self._session.get(models.ProjectModel, project_id)
            if existing is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            raise ConcurrentStateError(
                "workspace revision changed concurrently: "
                f"expected {expected_revision}, found {existing.workspace_revision}"
            )
        self._session.expire_all()
        row = self._session.get(models.ProjectModel, project_id)
        if row is None:  # pragma: no cover - guarded by the conditional update
            raise EntityNotFoundError(f"project not found: {project_id}")
        return _project_from_model(row)


class SqlAlchemyCatalogRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_source(self, source: entities.Source) -> None:
        row = models.SourceModel(
                id=source.id,
                project_id=source.project_id,
                snapshot_id=source.snapshot_id,
                kind=source.kind,
                display_name=source.display_name,
                status=source.status,
                created_at=source.created_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def get_source(self, source_id: str) -> Optional[entities.Source]:
        row = self._session.get(models.SourceModel, source_id)
        if row is None:
            return None
        root = self._session.get(models.SourceRootModel, source_id)
        return _source_from_model(row, None if root is None else root.node_id)

    def sources_for_project(self, project_id: str) -> Sequence[entities.Source]:
        rows = self._session.scalars(
            select(models.SourceModel)
            .where(models.SourceModel.project_id == project_id)
            .order_by(models.SourceModel.created_at, models.SourceModel.id)
        ).all()
        roots = {
            row.source_id: row.node_id
            for row in self._session.scalars(
                select(models.SourceRootModel).where(
                    models.SourceRootModel.project_id == project_id
                )
            ).all()
        }
        return [_source_from_model(row, roots.get(row.id)) for row in rows]

    def source_for_snapshot(self, snapshot_id: str) -> Optional[entities.Source]:
        row = self._session.scalar(
            select(models.SourceModel).where(
                models.SourceModel.snapshot_id == snapshot_id
            )
        )
        if row is None:
            return None
        root = self._session.get(models.SourceRootModel, row.id)
        return _source_from_model(row, None if root is None else root.node_id)

    def update_source_status(
        self,
        source_id: str,
        expected_status: enums.SourceStatus,
        new_status: enums.SourceStatus,
        verified_at: Optional[datetime],
    ) -> entities.Source:
        row = self._session.get(models.SourceModel, source_id)
        if row is None:
            raise EntityNotFoundError(f"source not found: {source_id}")
        if row.status != expected_status:
            raise ConcurrentStateError(
                "source status changed concurrently: "
                f"expected {expected_status.value}, found {row.status.value}"
            )
        require_source_transition(expected_status, new_status)
        row.status = new_status
        self._session.flush([row])
        root = self._session.get(models.SourceRootModel, source_id)
        return _source_from_model(row, None if root is None else root.node_id)

    def _set_source_root(self, source_id: str, node_id: str) -> None:
        source = self._session.get(models.SourceModel, source_id)
        node = self._session.get(models.NodeModel, node_id)
        if source is None:
            raise EntityNotFoundError(f"source not found: {source_id}")
        if node is None:
            raise EntityNotFoundError(f"node not found: {node_id}")
        if node.project_id != source.project_id or node.source_id != source.id:
            raise InvariantViolationError("source root must belong to the same source")
        if node.depth != 0:
            raise InvariantViolationError("source root must have depth 0")
        existing = self._session.get(models.SourceRootModel, source_id)
        if existing is not None:
            if existing.node_id != node_id:
                raise InvariantViolationError("source root is immutable once assigned")
            return
        row = models.SourceRootModel(
                source_id=source.id,
                project_id=source.project_id,
                node_id=node.id,
        )
        self._session.add(row)
        self._session.flush([row])

    def _add_node(self, node: entities.Node) -> None:
        row = models.NodeModel(
                id=node.id,
                project_id=node.project_id,
                source_id=node.source_id,
                kind=node.kind,
                format=node.format,
                original_name=node.original_name,
                display_name=node.display_name,
                logical_path=node.logical_path,
                depth=node.depth,
                media_type=node.media_type,
                declared_size=node.declared_size,
                status=node.status,
                detection_method=node.detection_method,
                detection_confidence=node.detection_confidence,
                detection_details=dict(node.detection_details),
                discovery_key=node.discovery_key,
                created_at=node.created_at,
                updated_at=node.updated_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def register_root(self, node: entities.Node) -> None:
        if node.depth != 0:
            raise InvariantViolationError("source root must have depth 0")
        source = self._session.get(models.SourceModel, node.source_id)
        if source is None:
            raise EntityNotFoundError(f"source not found: {node.source_id}")
        if source.project_id != node.project_id:
            raise InvariantViolationError("source root must belong to its project")
        self._add_node(node)
        self._set_source_root(source.id, node.id)
        self._add_lineage(
            [
                entities.LineageRecord(
                    project_id=node.project_id,
                    ancestor_node_id=node.id,
                    descendant_node_id=node.id,
                    distance=0,
                )
            ]
        )

    def register_child(
        self, node: entities.Node, relationship: entities.NodeRelationship
    ) -> None:
        if relationship.child_node_id != node.id:
            raise InvariantViolationError("relationship child must be the registered node")
        if relationship.project_id != node.project_id:
            raise InvariantViolationError("relationship and child must share a project")
        parent = self._session.get(models.NodeModel, relationship.parent_node_id)
        if parent is None:
            raise EntityNotFoundError(f"parent node not found: {relationship.parent_node_id}")
        if parent.source_id != node.source_id:
            raise InvariantViolationError("structural relationship cannot cross sources")
        allowed_relationships = {
            enums.NodeFormat.FOLDER: {enums.RelationshipType.FOLDER_CONTAINS},
            enums.NodeFormat.ZIP: {enums.RelationshipType.ARCHIVE_ENTRY},
            enums.NodeFormat.RAR: {enums.RelationshipType.ARCHIVE_ENTRY},
            enums.NodeFormat.SEVEN_Z: {enums.RelationshipType.ARCHIVE_ENTRY},
            enums.NodeFormat.MSG: {
                enums.RelationshipType.EMAIL_ATTACHMENT,
                enums.RelationshipType.EMBEDDED_MESSAGE,
            },
            enums.NodeFormat.EML: {
                enums.RelationshipType.EMAIL_ATTACHMENT,
                enums.RelationshipType.EMBEDDED_MESSAGE,
            },
        }
        if parent.kind != enums.NodeKind.CONTAINER:
            raise InvariantViolationError("structural parent must be a container")
        if relationship.type not in allowed_relationships.get(parent.format, set()):
            raise InvariantViolationError(
                "relationship type is incompatible with the parent format"
            )
        parent_lineage = self._session.scalars(
            select(models.LineageRecordModel).where(
                models.LineageRecordModel.project_id == node.project_id,
                models.LineageRecordModel.descendant_node_id == parent.id,
            )
        ).all()
        if not any(
            item.ancestor_node_id == parent.id and item.distance == 0
            for item in parent_lineage
        ):
            raise InvariantViolationError("parent lineage is incomplete")

        self._add_node(node)
        self._add_relationship(relationship)
        records = [
            entities.LineageRecord(
                project_id=node.project_id,
                ancestor_node_id=node.id,
                descendant_node_id=node.id,
                distance=0,
            )
        ]
        records.extend(
            entities.LineageRecord(
                project_id=node.project_id,
                ancestor_node_id=item.ancestor_node_id,
                descendant_node_id=node.id,
                distance=item.distance + 1,
            )
            for item in parent_lineage
        )
        self._add_lineage(records)

    def get_node(self, node_id: str) -> Optional[entities.Node]:
        row = self._session.get(models.NodeModel, node_id)
        return None if row is None else _node_from_model(row)

    def node_count_for_project(self, project_id: str) -> int:
        return int(
            self._session.scalar(
                select(func.count(models.NodeModel.id)).where(
                    models.NodeModel.project_id == project_id
                )
            )
            or 0
        )

    def nodes_for_project(
        self,
        project_id: str,
        status: Optional[enums.NodeProcessingStatus] = None,
    ) -> Sequence[entities.Node]:
        statement = select(models.NodeModel).where(
            models.NodeModel.project_id == project_id
        )
        if status is not None:
            statement = statement.where(models.NodeModel.status == status)
        rows = self._session.scalars(
            statement.order_by(
                models.NodeModel.depth,
                models.NodeModel.created_at,
                models.NodeModel.id,
            )
        ).all()
        return [_node_from_model(row) for row in rows]

    def search_nodes(
        self,
        project_id: str,
        *,
        query: Optional[str],
        source_id: Optional[str],
        kinds: Sequence[enums.NodeKind],
        formats: Sequence[enums.NodeFormat],
        statuses: Sequence[enums.NodeProcessingStatus],
        limit: int,
        offset: int,
    ) -> tuple[Sequence[entities.Node], int]:
        conditions = [models.NodeModel.project_id == project_id]
        if query is not None:
            metadata_match = (
                select(models.NodeMetadataModel.id)
                .where(
                    models.NodeMetadataModel.node_id == models.NodeModel.id,
                    models.NodeMetadataModel.value_type
                    == enums.MetadataValueType.TEXT,
                    models.NodeMetadataModel.value_text.icontains(
                        query, autoescape=True
                    ),
                )
                .exists()
            )
            conditions.append(
                or_(
                    models.NodeModel.original_name.icontains(
                        query, autoescape=True
                    ),
                    models.NodeModel.display_name.icontains(
                        query, autoescape=True
                    ),
                    models.NodeModel.logical_path.icontains(
                        query, autoescape=True
                    ),
                    metadata_match,
                )
            )
        if source_id is not None:
            conditions.append(models.NodeModel.source_id == source_id)
        if kinds:
            conditions.append(models.NodeModel.kind.in_(tuple(kinds)))
        if formats:
            conditions.append(models.NodeModel.format.in_(tuple(formats)))
        if statuses:
            conditions.append(models.NodeModel.status.in_(tuple(statuses)))
        total = int(
            self._session.scalar(
                select(func.count(models.NodeModel.id)).where(*conditions)
            )
            or 0
        )
        rows = self._session.scalars(
            select(models.NodeModel)
            .where(*conditions)
            .order_by(models.NodeModel.logical_path, models.NodeModel.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return ([_node_from_model(row) for row in rows], total)

    def update_node_detection(
        self,
        node_id: str,
        *,
        kind: enums.NodeKind,
        format: enums.NodeFormat,
        method: str,
        confidence: float,
        details: dict[str, object],
        updated_at: datetime,
    ) -> entities.Node:
        row = self._session.get(models.NodeModel, node_id)
        if row is None:
            raise EntityNotFoundError(f"node not found: {node_id}")
        row.kind = kind
        row.format = format
        row.detection_method = method
        row.detection_confidence = confidence
        row.detection_details = dict(details)
        row.updated_at = updated_at
        self._session.flush([row])
        return _node_from_model(row)

    def update_node_status(
        self,
        node_id: str,
        expected_status: enums.NodeProcessingStatus,
        new_status: enums.NodeProcessingStatus,
        updated_at: datetime,
    ) -> entities.Node:
        row = self._session.get(models.NodeModel, node_id)
        if row is None:
            raise EntityNotFoundError(f"node not found: {node_id}")
        if row.status != expected_status:
            raise ConcurrentStateError(
                "node status changed concurrently: "
                f"expected {expected_status.value}, found {row.status.value}"
            )
        row.status = new_status
        row.updated_at = updated_at
        self._session.flush([row])
        return _node_from_model(row)

    def add_artifact(self, artifact: entities.Artifact) -> None:
        row = models.ArtifactModel(
                id=artifact.id,
                project_id=artifact.project_id,
                node_id=artifact.node_id,
                role=artifact.role,
                scope=artifact.scope,
                locator=artifact.locator,
                size=artifact.size,
                sha256=artifact.sha256,
                integrity_status=artifact.integrity_status,
                observed_at=artifact.observed_at,
                created_at=artifact.created_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def artifacts_for_node(self, node_id: str) -> Sequence[entities.Artifact]:
        rows = self._session.scalars(
            select(models.ArtifactModel)
            .where(models.ArtifactModel.node_id == node_id)
            .order_by(models.ArtifactModel.created_at, models.ArtifactModel.id)
        ).all()
        return [_artifact_from_model(row) for row in rows]

    def artifacts_for_project(
        self, project_id: str
    ) -> Sequence[entities.Artifact]:
        rows = self._session.scalars(
            select(models.ArtifactModel)
            .where(models.ArtifactModel.project_id == project_id)
            .order_by(
                models.ArtifactModel.node_id,
                models.ArtifactModel.created_at,
                models.ArtifactModel.id,
            )
        ).all()
        return [_artifact_from_model(row) for row in rows]

    def update_artifact_integrity(
        self,
        artifact_id: str,
        expected_status: enums.ArtifactIntegrityStatus,
        new_status: enums.ArtifactIntegrityStatus,
        observed_at: Optional[datetime],
    ) -> entities.Artifact:
        row = self._session.get(models.ArtifactModel, artifact_id)
        if row is None:
            raise EntityNotFoundError(f"artifact not found: {artifact_id}")
        if row.integrity_status != expected_status:
            raise ConcurrentStateError(
                "artifact integrity changed concurrently: "
                f"expected {expected_status.value}, found {row.integrity_status.value}"
            )
        row.integrity_status = new_status
        if observed_at is not None:
            row.observed_at = observed_at
        self._session.flush([row])
        return _artifact_from_model(row)

    def _add_relationship(self, relationship: entities.NodeRelationship) -> None:
        parent = self._session.get(models.NodeModel, relationship.parent_node_id)
        child = self._session.get(models.NodeModel, relationship.child_node_id)
        if parent is None or child is None:
            raise EntityNotFoundError("relationship nodes must exist")
        if parent.project_id != relationship.project_id or child.project_id != relationship.project_id:
            raise InvariantViolationError("relationship nodes must belong to its project")
        if parent.source_id != child.source_id:
            raise InvariantViolationError("structural relationship cannot cross sources")
        if child.depth != parent.depth + 1:
            raise InvariantViolationError("child depth must equal parent depth plus one")
        would_cycle = self._session.scalar(
            select(models.LineageRecordModel.ancestor_node_id).where(
                models.LineageRecordModel.project_id == relationship.project_id,
                models.LineageRecordModel.ancestor_node_id == child.id,
                models.LineageRecordModel.descendant_node_id == parent.id,
            )
        )
        if would_cycle is not None:
            raise InvariantViolationError("relationship would create a structural cycle")
        row = models.NodeRelationshipModel(
                id=relationship.id,
                project_id=relationship.project_id,
                source_id=parent.source_id,
                parent_node_id=relationship.parent_node_id,
                child_node_id=relationship.child_node_id,
                type=relationship.type,
                ordinal=relationship.ordinal,
                discovery_key=relationship.discovery_key,
                created_by_job_id=relationship.created_by_job_id,
                created_at=relationship.created_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def children_of(self, parent_node_id: str) -> Sequence[entities.Node]:
        rows = self._session.scalars(
            select(models.NodeModel)
            .join(
                models.NodeRelationshipModel,
                models.NodeRelationshipModel.child_node_id == models.NodeModel.id,
            )
            .where(models.NodeRelationshipModel.parent_node_id == parent_node_id)
            .order_by(
                models.NodeRelationshipModel.ordinal,
                models.NodeRelationshipModel.id,
            )
        ).all()
        return [_node_from_model(row) for row in rows]

    def relationship_for_child(
        self, child_node_id: str
    ) -> Optional[entities.NodeRelationship]:
        row = self._session.scalar(
            select(models.NodeRelationshipModel).where(
                models.NodeRelationshipModel.child_node_id == child_node_id
            )
        )
        if row is None:
            return None
        return _relationship_from_model(row)

    def relationships_for_project(
        self, project_id: str
    ) -> Sequence[entities.NodeRelationship]:
        rows = self._session.scalars(
            select(models.NodeRelationshipModel)
            .where(models.NodeRelationshipModel.project_id == project_id)
            .order_by(
                models.NodeRelationshipModel.parent_node_id,
                models.NodeRelationshipModel.ordinal,
                models.NodeRelationshipModel.id,
            )
        ).all()
        return [_relationship_from_model(row) for row in rows]

    def add_entry_locator(self, locator: entities.SourceEntryLocator) -> None:
        relationship = self._session.get(
            models.NodeRelationshipModel, locator.relationship_id
        )
        if relationship is None:
            raise EntityNotFoundError(
                f"relationship not found: {locator.relationship_id}"
            )
        if (
            relationship.project_id != locator.project_id
            or relationship.child_node_id != locator.child_node_id
        ):
            raise InvariantViolationError(
                "entry locator must identify its relationship child"
            )
        if locator.kind == enums.MaterializationLocatorKind.SNAPSHOT_ENTRY:
            entry = self._session.get(
                models.OriginalSnapshotEntryModel, locator.snapshot_entry_id
            )
            if entry is None:
                raise EntityNotFoundError(
                    f"snapshot entry not found: {locator.snapshot_entry_id}"
                )
            if entry.project_id != locator.project_id:
                raise InvariantViolationError(
                    "snapshot entry locator cannot cross projects"
                )
            if any(
                value is not None
                for value in (
                    locator.member_ordinal,
                    locator.expected_name,
                    locator.member_role,
                )
            ):
                raise InvariantViolationError(
                    "snapshot entry locator cannot include container-member fields"
                )
        elif (
            locator.snapshot_entry_id is not None
            or locator.member_ordinal is None
            or locator.member_ordinal < 0
            or not locator.expected_name
            or not locator.member_role
        ):
            raise InvariantViolationError(
                "container locator requires ordinal, expected name, and member role"
            )
        row = models.SourceEntryLocatorModel(
            relationship_id=locator.relationship_id,
            project_id=locator.project_id,
            child_node_id=locator.child_node_id,
            kind=locator.kind,
            snapshot_entry_id=locator.snapshot_entry_id,
            member_ordinal=locator.member_ordinal,
            expected_name=locator.expected_name,
            member_role=locator.member_role,
            created_at=locator.created_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def entry_locator_for_relationship(
        self, relationship_id: str
    ) -> Optional[entities.SourceEntryLocator]:
        row = self._session.get(models.SourceEntryLocatorModel, relationship_id)
        return None if row is None else _entry_locator_from_model(row)

    def entry_locator_for_child(
        self, child_node_id: str
    ) -> Optional[entities.SourceEntryLocator]:
        row = self._session.scalar(
            select(models.SourceEntryLocatorModel).where(
                models.SourceEntryLocatorModel.child_node_id == child_node_id
            )
        )
        return None if row is None else _entry_locator_from_model(row)

    def _add_lineage(self, records: Iterable[entities.LineageRecord]) -> None:
        rows: list[models.LineageRecordModel] = []
        for record in records:
            ancestor = self._session.get(models.NodeModel, record.ancestor_node_id)
            descendant = self._session.get(models.NodeModel, record.descendant_node_id)
            if ancestor is None or descendant is None:
                raise EntityNotFoundError("lineage nodes must exist")
            if ancestor.project_id != record.project_id or descendant.project_id != record.project_id:
                raise InvariantViolationError("lineage nodes must belong to its project")
            if ancestor.source_id != descendant.source_id:
                raise InvariantViolationError("lineage cannot cross sources")
            row = models.LineageRecordModel(
                    project_id=record.project_id,
                    source_id=ancestor.source_id,
                    ancestor_node_id=record.ancestor_node_id,
                    descendant_node_id=record.descendant_node_id,
                    distance=record.distance,
            )
            self._session.add(row)
            rows.append(row)
        if rows:
            self._session.flush(rows)

    def lineage_for(self, descendant_node_id: str) -> Sequence[entities.LineageRecord]:
        rows = self._session.scalars(
            select(models.LineageRecordModel)
            .where(models.LineageRecordModel.descendant_node_id == descendant_node_id)
            .order_by(
                models.LineageRecordModel.distance.desc(),
                models.LineageRecordModel.ancestor_node_id,
            )
        ).all()
        return [_lineage_from_model(row) for row in rows]

    def lineage_for_project(
        self, project_id: str
    ) -> Sequence[entities.LineageRecord]:
        rows = self._session.scalars(
            select(models.LineageRecordModel)
            .where(models.LineageRecordModel.project_id == project_id)
            .order_by(
                models.LineageRecordModel.descendant_node_id,
                models.LineageRecordModel.distance.desc(),
                models.LineageRecordModel.ancestor_node_id,
            )
        ).all()
        return [_lineage_from_model(row) for row in rows]

    def add_metadata(self, metadata: entities.NodeMetadata) -> None:
        row = models.NodeMetadataModel(
                id=metadata.id,
                project_id=metadata.project_id,
                node_id=metadata.node_id,
                namespace=metadata.namespace,
                key=metadata.key,
                value_type=metadata.value_type,
                value_text=metadata.value_text,
                value_integer=metadata.value_integer,
                value_real=metadata.value_real,
                value_boolean=metadata.value_boolean,
                value_datetime=metadata.value_datetime,
                value_json=metadata.value_json,
                provenance=metadata.provenance,
                observed_at=metadata.observed_at,
                created_at=metadata.created_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def metadata_for_node(self, node_id: str) -> Sequence[entities.NodeMetadata]:
        rows = self._session.scalars(
            select(models.NodeMetadataModel)
            .where(models.NodeMetadataModel.node_id == node_id)
            .order_by(
                models.NodeMetadataModel.namespace,
                models.NodeMetadataModel.key,
                models.NodeMetadataModel.id,
            )
        ).all()
        return [_metadata_from_model(row) for row in rows]

    def metadata_for_project(
        self, project_id: str
    ) -> Sequence[entities.NodeMetadata]:
        rows = self._session.scalars(
            select(models.NodeMetadataModel)
            .where(models.NodeMetadataModel.project_id == project_id)
            .order_by(
                models.NodeMetadataModel.node_id,
                models.NodeMetadataModel.namespace,
                models.NodeMetadataModel.key,
                models.NodeMetadataModel.id,
            )
        ).all()
        return [_metadata_from_model(row) for row in rows]


class SqlAlchemyProcessingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_job(self, job: entities.ProcessingJob) -> None:
        row = models.ProcessingJobModel(
                id=job.id,
                project_id=job.project_id,
                import_session_id=job.import_session_id,
                type=job.type,
                status=job.status,
                requested_by=job.requested_by,
                policy_snapshot=dict(job.policy_snapshot),
                created_at=job.created_at,
                started_at=job.started_at,
                finished_at=job.finished_at,
                warning_count=job.warning_count,
                error_count=job.error_count,
        )
        self._session.add(row)
        self._session.flush([row])

    def get_job(self, job_id: str) -> Optional[entities.ProcessingJob]:
        row = self._session.get(models.ProcessingJobModel, job_id)
        return None if row is None else _job_from_model(row)

    def jobs_for_project(
        self,
        project_id: str,
        statuses: Optional[Sequence[enums.JobStatus]] = None,
    ) -> Sequence[entities.ProcessingJob]:
        statement = select(models.ProcessingJobModel).where(
            models.ProcessingJobModel.project_id == project_id
        )
        if statuses:
            statement = statement.where(
                models.ProcessingJobModel.status.in_(tuple(statuses))
            )
        rows = self._session.scalars(
            statement.order_by(
                models.ProcessingJobModel.created_at,
                models.ProcessingJobModel.id,
            )
        ).all()
        return [_job_from_model(row) for row in rows]

    def job_for_import_session(
        self, import_session_id: str
    ) -> Optional[entities.ProcessingJob]:
        row = self._session.scalar(
            select(models.ProcessingJobModel).where(
                models.ProcessingJobModel.import_session_id == import_session_id
            )
        )
        return None if row is None else _job_from_model(row)

    def update_job_status(
        self,
        job_id: str,
        expected_status: enums.JobStatus,
        new_status: enums.JobStatus,
        *,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        warning_count: Optional[int] = None,
        error_count: Optional[int] = None,
    ) -> entities.ProcessingJob:
        row = self._session.get(models.ProcessingJobModel, job_id)
        if row is None:
            raise EntityNotFoundError(f"job not found: {job_id}")
        if row.status != expected_status:
            raise ConcurrentStateError(
                "job status changed concurrently: "
                f"expected {expected_status.value}, found {row.status.value}"
            )
        row.status = new_status
        if started_at is not None:
            row.started_at = started_at
        if finished_at is not None:
            row.finished_at = finished_at
        if warning_count is not None:
            row.warning_count = warning_count
        if error_count is not None:
            row.error_count = error_count
        self._session.flush([row])
        return _job_from_model(row)

    def add_attempt(self, attempt: entities.ProcessingAttempt) -> None:
        error = attempt.error
        row = models.ProcessingAttemptModel(
                id=attempt.id,
                project_id=attempt.project_id,
                job_id=attempt.job_id,
                node_id=attempt.node_id,
                attempt_number=attempt.attempt_number,
                status=attempt.status,
                stage=attempt.stage,
                handler_name=attempt.handler_name,
                handler_version=attempt.handler_version,
                backend_name=attempt.backend_name,
                backend_version=attempt.backend_version,
                backend_sha256=attempt.backend_sha256,
                queued_at=attempt.queued_at,
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
                error_code=None if error is None else error.code,
                error_category=None if error is None else error.category,
                error_stage=None if error is None else error.stage,
                error_message=None if error is None else error.message,
                error_retryable=None if error is None else error.retryable,
                technical_reference=None if error is None else error.technical_reference,
        )
        self._session.add(row)
        self._session.flush([row])

    def get_attempt(self, attempt_id: str) -> Optional[entities.ProcessingAttempt]:
        row = self._session.get(models.ProcessingAttemptModel, attempt_id)
        return None if row is None else _attempt_from_model(row)

    def attempts_for_project(
        self,
        project_id: str,
        statuses: Optional[Sequence[enums.AttemptStatus]] = None,
    ) -> Sequence[entities.ProcessingAttempt]:
        statement = select(models.ProcessingAttemptModel).where(
            models.ProcessingAttemptModel.project_id == project_id
        )
        if statuses:
            statement = statement.where(
                models.ProcessingAttemptModel.status.in_(tuple(statuses))
            )
        rows = self._session.scalars(
            statement.order_by(
                models.ProcessingAttemptModel.queued_at,
                models.ProcessingAttemptModel.id,
            )
        ).all()
        return [_attempt_from_model(row) for row in rows]

    def next_attempt_number(self, node_id: str) -> int:
        maximum = self._session.scalar(
            select(func.max(models.ProcessingAttemptModel.attempt_number)).where(
                models.ProcessingAttemptModel.node_id == node_id
            )
        )
        return int(maximum or 0) + 1

    def update_attempt_status(
        self,
        attempt_id: str,
        expected_status: enums.AttemptStatus,
        new_status: enums.AttemptStatus,
        *,
        handler_name: Optional[str] = None,
        handler_version: Optional[str] = None,
        backend_name: Optional[str] = None,
        backend_version: Optional[str] = None,
        backend_sha256: Optional[str] = None,
        stage: Optional[enums.ProcessingStage] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        error: Optional[entities.ProcessingError] = None,
    ) -> entities.ProcessingAttempt:
        row = self._session.get(models.ProcessingAttemptModel, attempt_id)
        if row is None:
            raise EntityNotFoundError(f"attempt not found: {attempt_id}")
        if row.status != expected_status:
            raise ConcurrentStateError(
                "attempt status changed concurrently: "
                f"expected {expected_status.value}, found {row.status.value}"
            )
        row.status = new_status
        if handler_name is not None:
            row.handler_name = handler_name
        if handler_version is not None:
            row.handler_version = handler_version
        if backend_name is not None:
            row.backend_name = backend_name
        if backend_version is not None:
            row.backend_version = backend_version
        if backend_sha256 is not None:
            row.backend_sha256 = backend_sha256
        if stage is not None:
            row.stage = stage
        if started_at is not None:
            row.started_at = started_at
        if finished_at is not None:
            row.finished_at = finished_at
        if error is not None:
            row.error_code = error.code
            row.error_category = error.category
            row.error_stage = error.stage
            row.error_message = error.message
            row.error_retryable = error.retryable
            row.technical_reference = error.technical_reference
        self._session.flush([row])
        return _attempt_from_model(row)

    def append_event(self, event: entities.ProcessingEvent) -> None:
        row = models.ProcessingEventModel(
                id=event.id,
                event_type=event.event_type,
                project_id=event.project_id,
                source_id=event.source_id,
                node_id=event.node_id,
                job_id=event.job_id,
                attempt_id=event.attempt_id,
                import_session_id=event.import_session_id,
                snapshot_id=event.snapshot_id,
                workspace_item_id=event.workspace_item_id,
                working_artifact_id=event.working_artifact_id,
                actor=event.actor,
                occurred_at=event.occurred_at,
                severity=event.severity,
                previous_status=event.previous_status,
                new_status=event.new_status,
                error_code=event.error_code,
                details=dict(event.details),
                correlation_id=event.correlation_id,
        )
        self._session.add(row)
        self._session.flush([row])

    def events_for_project(self, project_id: str) -> Sequence[entities.ProcessingEvent]:
        rows = self._session.scalars(
            select(models.ProcessingEventModel)
            .where(models.ProcessingEventModel.project_id == project_id)
            .order_by(
                models.ProcessingEventModel.occurred_at,
                models.ProcessingEventModel.id,
            )
        ).all()
        return [_event_from_model(row) for row in rows]
