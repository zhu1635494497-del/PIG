from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pig.domain import entities, enums
from pig.domain.exceptions import (
    ConcurrentStateError,
    EntityNotFoundError,
    InvariantViolationError,
)
from pig.domain.transitions import (
    require_import_item_transition,
    require_import_session_transition,
    require_original_artifact_integrity_transition,
    require_original_snapshot_transition,
    require_working_content_transition,
    require_workspace_lifecycle_transition,
    require_workspace_materialization_transition,
)
from pig.infrastructure.database import models


def _session_from_model(row: models.ImportSessionModel) -> entities.ImportSession:
    return entities.ImportSession(
        id=row.id,
        project_id=row.project_id,
        status=row.status,
        requested_item_count=row.requested_item_count,
        accepted_item_count=row.accepted_item_count,
        failed_item_count=row.failed_item_count,
        requested_at=row.requested_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        actor=row.actor,
        correlation_id=row.correlation_id,
        policy_snapshot=dict(row.policy_snapshot),
        target_workspace_parent_id=row.target_workspace_parent_id,
        expected_workspace_revision=row.expected_workspace_revision,
    )


def _session_item_from_model(
    row: models.ImportSessionItemModel,
) -> entities.ImportSessionItem:
    return entities.ImportSessionItem(
        id=row.id,
        project_id=row.project_id,
        import_session_id=row.import_session_id,
        ordinal=row.ordinal,
        input_locator=row.input_locator,
        status=row.status,
        snapshot_id=row.snapshot_id,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _snapshot_from_model(
    row: models.OriginalSnapshotModel,
) -> entities.OriginalSnapshot:
    return entities.OriginalSnapshot(
        id=row.id,
        project_id=row.project_id,
        import_session_id=row.import_session_id,
        input_kind=row.input_kind,
        original_display_name=row.original_display_name,
        external_locator_at_import=row.external_locator_at_import,
        status=row.status,
        created_at=row.created_at,
        verified_at=row.verified_at,
    )


def _original_artifact_from_model(
    row: models.OriginalArtifactModel,
) -> entities.OriginalArtifact:
    return entities.OriginalArtifact(
        id=row.id,
        project_id=row.project_id,
        snapshot_id=row.snapshot_id,
        source_node_id=row.source_node_id,
        storage_key=row.storage_key,
        size=row.size,
        sha256=row.sha256,
        observed_modified_at=row.observed_modified_at,
        integrity_status=row.integrity_status,
        created_at=row.created_at,
    )


def _snapshot_entry_from_model(
    row: models.OriginalSnapshotEntryModel,
) -> entities.OriginalSnapshotEntry:
    return entities.OriginalSnapshotEntry(
        id=row.id,
        project_id=row.project_id,
        snapshot_id=row.snapshot_id,
        parent_entry_id=row.parent_entry_id,
        artifact_id=row.artifact_id,
        source_node_id=row.source_node_id,
        kind=row.kind,
        original_name=row.original_name,
        ordinal=row.ordinal,
        created_at=row.created_at,
    )


def _workspace_item_from_model(
    row: models.WorkspaceItemModel,
) -> entities.WorkspaceItem:
    return entities.WorkspaceItem(
        id=row.id,
        project_id=row.project_id,
        origin_source_node_id=row.origin_source_node_id,
        item_kind=row.item_kind,
        display_name=row.display_name,
        lifecycle_status=row.lifecycle_status,
        materialization_status=row.materialization_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )


def _placement_from_model(
    row: models.WorkspacePlacementModel,
) -> entities.WorkspacePlacement:
    return entities.WorkspacePlacement(
        workspace_item_id=row.workspace_item_id,
        project_id=row.project_id,
        parent_workspace_item_id=row.parent_workspace_item_id,
        ordinal=row.ordinal,
        previous_parent_id=row.previous_parent_id,
        previous_ordinal=row.previous_ordinal,
        updated_at=row.updated_at,
    )


def _working_artifact_from_model(
    row: models.WorkingArtifactModel,
) -> entities.WorkingArtifact:
    return entities.WorkingArtifact(
        id=row.id,
        project_id=row.project_id,
        workspace_item_id=row.workspace_item_id,
        storage_key=row.storage_key,
        baseline_size=row.baseline_size,
        baseline_sha256=row.baseline_sha256,
        current_size=row.current_size,
        current_sha256=row.current_sha256,
        content_status=row.content_status,
        materialized_at=row.materialized_at,
        last_checked_at=row.last_checked_at,
        updated_at=row.updated_at,
    )


def _working_revision_from_model(
    row: models.WorkingRevisionModel,
) -> entities.WorkingRevision:
    return entities.WorkingRevision(
        id=row.id,
        project_id=row.project_id,
        working_artifact_id=row.working_artifact_id,
        role=row.role,
        storage_key=row.storage_key,
        size=row.size,
        sha256=row.sha256,
        file_modified_at=row.file_modified_at,
        detected_at=row.detected_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _recovery_run_from_model(
    row: models.RecoveryRunModel,
) -> entities.RecoveryRun:
    return entities.RecoveryRun(
        id=row.id,
        project_id=row.project_id,
        status=row.status,
        actor=row.actor,
        correlation_id=row.correlation_id,
        detected_count=row.detected_count,
        recovered_count=row.recovered_count,
        failed_count=row.failed_count,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _recovery_item_from_model(
    row: models.RecoveryItemModel,
) -> entities.RecoveryItem:
    return entities.RecoveryItem(
        id=row.id,
        recovery_run_id=row.recovery_run_id,
        project_id=row.project_id,
        kind=row.kind,
        action=row.action,
        status=row.status,
        storage_key=row.storage_key,
        operation_id=row.operation_id,
        size=row.size,
        sha256=row.sha256,
        reason=row.reason,
        recovery_storage_key=row.recovery_storage_key,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_RUN_TRANSITIONS = {
    enums.RecoveryRunStatus.DETECTED: {
        enums.RecoveryRunStatus.AWAITING_CONFIRMATION,
        enums.RecoveryRunStatus.FAILED,
    },
    enums.RecoveryRunStatus.AWAITING_CONFIRMATION: {
        enums.RecoveryRunStatus.RUNNING,
        enums.RecoveryRunStatus.FAILED,
    },
    enums.RecoveryRunStatus.RUNNING: {
        enums.RecoveryRunStatus.SUCCESS,
        enums.RecoveryRunStatus.PARTIAL_SUCCESS,
        enums.RecoveryRunStatus.FAILED,
    },
}


_ITEM_TRANSITIONS = {
    enums.RecoveryItemStatus.DISCOVERED: {
        enums.RecoveryItemStatus.PLANNED,
        enums.RecoveryItemStatus.FAILED,
    },
    enums.RecoveryItemStatus.PLANNED: {
        enums.RecoveryItemStatus.RESTORED,
        enums.RecoveryItemStatus.QUARANTINED,
        enums.RecoveryItemStatus.REMOVED_REPRODUCIBLE,
        enums.RecoveryItemStatus.UNCHANGED,
        enums.RecoveryItemStatus.FAILED,
    },
}


class SqlAlchemyRecoveryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_run(self, run: entities.RecoveryRun) -> None:
        row = models.RecoveryRunModel(
            id=run.id,
            project_id=run.project_id,
            status=run.status,
            actor=run.actor,
            correlation_id=run.correlation_id,
            detected_count=run.detected_count,
            recovered_count=run.recovered_count,
            failed_count=run.failed_count,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def get_run(self, run_id: str) -> Optional[entities.RecoveryRun]:
        row = self._session.get(models.RecoveryRunModel, run_id)
        return None if row is None else _recovery_run_from_model(row)

    def runs_for_project(self, project_id: str) -> Sequence[entities.RecoveryRun]:
        rows = self._session.scalars(
            select(models.RecoveryRunModel)
            .where(models.RecoveryRunModel.project_id == project_id)
            .order_by(models.RecoveryRunModel.created_at, models.RecoveryRunModel.id)
        ).all()
        return tuple(_recovery_run_from_model(row) for row in rows)

    def update_run_status(
        self,
        run_id: str,
        expected_status: enums.RecoveryRunStatus,
        new_status: enums.RecoveryRunStatus,
        *,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        recovered_count: Optional[int] = None,
        failed_count: Optional[int] = None,
    ) -> entities.RecoveryRun:
        row = self._session.get(models.RecoveryRunModel, run_id)
        if row is None:
            raise EntityNotFoundError(f"recovery run not found: {run_id}")
        if row.status != expected_status:
            raise ConcurrentStateError(
                "recovery run changed concurrently: "
                f"expected {expected_status.value}, found {row.status.value}"
            )
        if new_status not in _RUN_TRANSITIONS.get(expected_status, set()):
            raise InvariantViolationError(
                f"invalid recovery run transition: {expected_status.value} -> "
                f"{new_status.value}"
            )
        row.status = new_status
        if started_at is not None:
            row.started_at = started_at
        if finished_at is not None:
            row.finished_at = finished_at
        if recovered_count is not None:
            row.recovered_count = recovered_count
        if failed_count is not None:
            row.failed_count = failed_count
        self._session.flush([row])
        return _recovery_run_from_model(row)

    def add_item(self, item: entities.RecoveryItem) -> None:
        row = models.RecoveryItemModel(
            id=item.id,
            recovery_run_id=item.recovery_run_id,
            project_id=item.project_id,
            kind=item.kind,
            action=item.action,
            status=item.status,
            storage_key=item.storage_key,
            operation_id=item.operation_id,
            size=item.size,
            sha256=item.sha256,
            reason=item.reason,
            recovery_storage_key=item.recovery_storage_key,
            error_code=item.error_code,
            error_message=item.error_message,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def items_for_run(self, run_id: str) -> Sequence[entities.RecoveryItem]:
        rows = self._session.scalars(
            select(models.RecoveryItemModel)
            .where(models.RecoveryItemModel.recovery_run_id == run_id)
            .order_by(models.RecoveryItemModel.created_at, models.RecoveryItemModel.id)
        ).all()
        return tuple(_recovery_item_from_model(row) for row in rows)

    def update_item_status(
        self,
        item_id: str,
        expected_status: enums.RecoveryItemStatus,
        new_status: enums.RecoveryItemStatus,
        *,
        updated_at: datetime,
        size: Optional[int] = None,
        sha256: Optional[str] = None,
        recovery_storage_key: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> entities.RecoveryItem:
        row = self._session.get(models.RecoveryItemModel, item_id)
        if row is None:
            raise EntityNotFoundError(f"recovery item not found: {item_id}")
        if row.status != expected_status:
            raise ConcurrentStateError(
                "recovery item changed concurrently: "
                f"expected {expected_status.value}, found {row.status.value}"
            )
        if new_status not in _ITEM_TRANSITIONS.get(expected_status, set()):
            raise InvariantViolationError(
                f"invalid recovery item transition: {expected_status.value} -> "
                f"{new_status.value}"
            )
        row.status = new_status
        row.updated_at = updated_at
        row.size = size
        row.sha256 = sha256
        row.recovery_storage_key = recovery_storage_key
        row.error_code = error_code
        row.error_message = error_message
        self._session.flush([row])
        return _recovery_item_from_model(row)


class SqlAlchemyImportRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_session(self, session: entities.ImportSession) -> None:
        row = models.ImportSessionModel(
            id=session.id,
            project_id=session.project_id,
            status=session.status,
            requested_item_count=session.requested_item_count,
            accepted_item_count=session.accepted_item_count,
            failed_item_count=session.failed_item_count,
            requested_at=session.requested_at,
            started_at=session.started_at,
            finished_at=session.finished_at,
            actor=session.actor,
            correlation_id=session.correlation_id,
            policy_snapshot=dict(session.policy_snapshot),
            target_workspace_parent_id=session.target_workspace_parent_id,
            expected_workspace_revision=session.expected_workspace_revision,
        )
        self._session.add(row)
        self._session.flush([row])

    def get_session(self, session_id: str) -> Optional[entities.ImportSession]:
        row = self._session.get(models.ImportSessionModel, session_id)
        return None if row is None else _session_from_model(row)

    def sessions_for_project(
        self, project_id: str
    ) -> Sequence[entities.ImportSession]:
        rows = self._session.scalars(
            select(models.ImportSessionModel)
            .where(models.ImportSessionModel.project_id == project_id)
            .order_by(
                models.ImportSessionModel.requested_at,
                models.ImportSessionModel.id,
            )
        ).all()
        return [_session_from_model(row) for row in rows]

    def get_session_by_correlation(
        self, project_id: str, correlation_id: str
    ) -> Optional[entities.ImportSession]:
        row = self._session.scalar(
            select(models.ImportSessionModel).where(
                models.ImportSessionModel.project_id == project_id,
                models.ImportSessionModel.correlation_id == correlation_id,
            )
        )
        return None if row is None else _session_from_model(row)

    def add_session_item(self, item: entities.ImportSessionItem) -> None:
        session = self._session.get(models.ImportSessionModel, item.import_session_id)
        if session is None:
            raise EntityNotFoundError(
                f"import session not found: {item.import_session_id}"
            )
        if session.project_id != item.project_id:
            raise InvariantViolationError(
                "import item and session must belong to the same project"
            )
        row = models.ImportSessionItemModel(
            id=item.id,
            project_id=item.project_id,
            import_session_id=item.import_session_id,
            ordinal=item.ordinal,
            input_locator=item.input_locator,
            status=item.status,
            snapshot_id=item.snapshot_id,
            error_code=item.error_code,
            error_message=item.error_message,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def items_for_session(
        self, import_session_id: str
    ) -> Sequence[entities.ImportSessionItem]:
        rows = self._session.scalars(
            select(models.ImportSessionItemModel)
            .where(
                models.ImportSessionItemModel.import_session_id == import_session_id
            )
            .order_by(models.ImportSessionItemModel.ordinal)
        ).all()
        return [_session_item_from_model(row) for row in rows]

    def update_session_item(
        self,
        item_id: str,
        expected_status: enums.ImportItemStatus,
        new_status: enums.ImportItemStatus,
        *,
        updated_at: datetime,
        snapshot_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> entities.ImportSessionItem:
        row = self._session.get(models.ImportSessionItemModel, item_id)
        if row is None:
            raise EntityNotFoundError(f"import item not found: {item_id}")
        if row.status != expected_status:
            raise ConcurrentStateError(
                "import item status changed concurrently: "
                f"expected {expected_status.value}, found {row.status.value}"
            )
        require_import_item_transition(expected_status, new_status)
        if new_status == enums.ImportItemStatus.FAILED and (
            not error_code or not error_message
        ):
            raise InvariantViolationError("failed import item requires error details")
        if snapshot_id is not None:
            snapshot = self._session.get(models.OriginalSnapshotModel, snapshot_id)
            if snapshot is None or snapshot.project_id != row.project_id:
                raise InvariantViolationError(
                    "import item snapshot must belong to the same project"
                )
            row.snapshot_id = snapshot_id
        row.status = new_status
        row.error_code = error_code
        row.error_message = error_message
        row.updated_at = updated_at
        self._session.flush([row])
        return _session_item_from_model(row)

    def update_session_status(
        self,
        session_id: str,
        expected_status: enums.ImportSessionStatus,
        new_status: enums.ImportSessionStatus,
        *,
        accepted_item_count: Optional[int] = None,
        failed_item_count: Optional[int] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> entities.ImportSession:
        row = self._session.get(models.ImportSessionModel, session_id)
        if row is None:
            raise EntityNotFoundError(f"import session not found: {session_id}")
        if row.status != expected_status:
            raise ConcurrentStateError(
                "import session status changed concurrently: "
                f"expected {expected_status.value}, found {row.status.value}"
            )
        require_import_session_transition(expected_status, new_status)
        row.status = new_status
        if accepted_item_count is not None:
            row.accepted_item_count = accepted_item_count
        if failed_item_count is not None:
            row.failed_item_count = failed_item_count
        if started_at is not None:
            row.started_at = started_at
        if finished_at is not None:
            row.finished_at = finished_at
        self._session.flush([row])
        return _session_from_model(row)

    def add_snapshot(self, snapshot: entities.OriginalSnapshot) -> None:
        session = self._session.get(
            models.ImportSessionModel, snapshot.import_session_id
        )
        if session is None:
            raise EntityNotFoundError(
                f"import session not found: {snapshot.import_session_id}"
            )
        if session.project_id != snapshot.project_id:
            raise InvariantViolationError(
                "snapshot and import session must belong to the same project"
            )
        row = models.OriginalSnapshotModel(
            id=snapshot.id,
            project_id=snapshot.project_id,
            import_session_id=snapshot.import_session_id,
            input_kind=snapshot.input_kind,
            original_display_name=snapshot.original_display_name,
            external_locator_at_import=snapshot.external_locator_at_import,
            status=snapshot.status,
            created_at=snapshot.created_at,
            verified_at=snapshot.verified_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def get_snapshot(
        self, snapshot_id: str
    ) -> Optional[entities.OriginalSnapshot]:
        row = self._session.get(models.OriginalSnapshotModel, snapshot_id)
        return None if row is None else _snapshot_from_model(row)

    def snapshots_for_project(
        self, project_id: str
    ) -> Sequence[entities.OriginalSnapshot]:
        rows = self._session.scalars(
            select(models.OriginalSnapshotModel)
            .where(models.OriginalSnapshotModel.project_id == project_id)
            .order_by(
                models.OriginalSnapshotModel.created_at,
                models.OriginalSnapshotModel.id,
            )
        ).all()
        return [_snapshot_from_model(row) for row in rows]

    def update_snapshot_status(
        self,
        snapshot_id: str,
        expected_status: enums.OriginalSnapshotStatus,
        new_status: enums.OriginalSnapshotStatus,
        *,
        verified_at: Optional[datetime] = None,
    ) -> entities.OriginalSnapshot:
        row = self._session.get(models.OriginalSnapshotModel, snapshot_id)
        if row is None:
            raise EntityNotFoundError(f"snapshot not found: {snapshot_id}")
        if row.status != expected_status:
            raise ConcurrentStateError(
                "snapshot status changed concurrently: "
                f"expected {expected_status.value}, found {row.status.value}"
            )
        require_original_snapshot_transition(expected_status, new_status)
        row.status = new_status
        if verified_at is not None:
            row.verified_at = verified_at
        self._session.flush([row])
        return _snapshot_from_model(row)

    def add_original_artifact(self, artifact: entities.OriginalArtifact) -> None:
        snapshot = self._session.get(
            models.OriginalSnapshotModel, artifact.snapshot_id
        )
        if snapshot is None:
            raise EntityNotFoundError(f"snapshot not found: {artifact.snapshot_id}")
        if snapshot.project_id != artifact.project_id:
            raise InvariantViolationError(
                "original artifact and snapshot must belong to the same project"
            )
        if artifact.source_node_id is not None:
            node = self._session.get(models.NodeModel, artifact.source_node_id)
            if node is None:
                raise EntityNotFoundError(
                    f"source node not found: {artifact.source_node_id}"
                )
            if node.project_id != artifact.project_id:
                raise InvariantViolationError(
                    "original artifact and source node must belong to the same project"
                )
        row = models.OriginalArtifactModel(
            id=artifact.id,
            project_id=artifact.project_id,
            snapshot_id=artifact.snapshot_id,
            source_node_id=artifact.source_node_id,
            storage_key=artifact.storage_key,
            size=artifact.size,
            sha256=artifact.sha256,
            observed_modified_at=artifact.observed_modified_at,
            integrity_status=artifact.integrity_status,
            created_at=artifact.created_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def get_original_artifact(
        self, artifact_id: str
    ) -> Optional[entities.OriginalArtifact]:
        row = self._session.get(models.OriginalArtifactModel, artifact_id)
        return None if row is None else _original_artifact_from_model(row)

    def original_artifacts_for_snapshot(
        self, snapshot_id: str
    ) -> Sequence[entities.OriginalArtifact]:
        rows = self._session.scalars(
            select(models.OriginalArtifactModel)
            .where(models.OriginalArtifactModel.snapshot_id == snapshot_id)
            .order_by(
                models.OriginalArtifactModel.created_at,
                models.OriginalArtifactModel.id,
            )
        ).all()
        return [_original_artifact_from_model(row) for row in rows]

    def update_original_artifact_integrity(
        self,
        artifact_id: str,
        expected_status: enums.ArtifactIntegrityStatus,
        new_status: enums.ArtifactIntegrityStatus,
    ) -> entities.OriginalArtifact:
        row = self._session.get(models.OriginalArtifactModel, artifact_id)
        if row is None:
            raise EntityNotFoundError(f"original artifact not found: {artifact_id}")
        if row.integrity_status != expected_status:
            raise ConcurrentStateError(
                "original artifact integrity changed concurrently: "
                f"expected {expected_status.value}, "
                f"found {row.integrity_status.value}"
            )
        require_original_artifact_integrity_transition(
            expected_status, new_status
        )
        row.integrity_status = new_status
        self._session.flush([row])
        return _original_artifact_from_model(row)

    def bind_original_artifact_to_source_node(
        self, artifact_id: str, source_node_id: str
    ) -> entities.OriginalArtifact:
        row = self._session.get(models.OriginalArtifactModel, artifact_id)
        if row is None:
            raise EntityNotFoundError(f"original artifact not found: {artifact_id}")
        if row.source_node_id is not None:
            raise ConcurrentStateError(
                "original artifact source node binding is already assigned"
            )
        node = self._session.get(models.NodeModel, source_node_id)
        if node is None:
            raise EntityNotFoundError(f"source node not found: {source_node_id}")
        if node.project_id != row.project_id:
            raise InvariantViolationError(
                "original artifact and source node must belong to the same project"
            )
        row.source_node_id = source_node_id
        self._session.flush([row])
        return _original_artifact_from_model(row)

    def add_snapshot_entry(self, entry: entities.OriginalSnapshotEntry) -> None:
        snapshot = self._session.get(models.OriginalSnapshotModel, entry.snapshot_id)
        if snapshot is None:
            raise EntityNotFoundError(f"snapshot not found: {entry.snapshot_id}")
        if snapshot.project_id != entry.project_id:
            raise InvariantViolationError(
                "snapshot entry and snapshot must belong to the same project"
            )
        if entry.parent_entry_id is not None:
            parent = self._session.get(
                models.OriginalSnapshotEntryModel, entry.parent_entry_id
            )
            if parent is None:
                raise EntityNotFoundError(
                    f"snapshot parent entry not found: {entry.parent_entry_id}"
                )
            if (
                parent.project_id != entry.project_id
                or parent.snapshot_id != entry.snapshot_id
                or parent.kind != enums.OriginalSnapshotEntryKind.FOLDER
            ):
                raise InvariantViolationError(
                    "snapshot entry parent must be a folder in the same snapshot"
                )
        if entry.artifact_id is not None:
            artifact = self._session.get(
                models.OriginalArtifactModel, entry.artifact_id
            )
            if artifact is None:
                raise EntityNotFoundError(
                    f"original artifact not found: {entry.artifact_id}"
                )
            if (
                artifact.project_id != entry.project_id
                or artifact.snapshot_id != entry.snapshot_id
            ):
                raise InvariantViolationError(
                    "snapshot entry artifact must belong to the same snapshot"
                )
        row = models.OriginalSnapshotEntryModel(
            id=entry.id,
            project_id=entry.project_id,
            snapshot_id=entry.snapshot_id,
            parent_entry_id=entry.parent_entry_id,
            artifact_id=entry.artifact_id,
            source_node_id=entry.source_node_id,
            kind=entry.kind,
            original_name=entry.original_name,
            ordinal=entry.ordinal,
            created_at=entry.created_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def get_snapshot_entry(
        self, entry_id: str
    ) -> Optional[entities.OriginalSnapshotEntry]:
        row = self._session.get(models.OriginalSnapshotEntryModel, entry_id)
        return None if row is None else _snapshot_entry_from_model(row)

    def entries_for_snapshot(
        self, snapshot_id: str
    ) -> Sequence[entities.OriginalSnapshotEntry]:
        rows = self._session.scalars(
            select(models.OriginalSnapshotEntryModel)
            .where(models.OriginalSnapshotEntryModel.snapshot_id == snapshot_id)
            .order_by(
                models.OriginalSnapshotEntryModel.created_at,
                models.OriginalSnapshotEntryModel.id,
            )
        ).all()
        return [_snapshot_entry_from_model(row) for row in rows]

    def bind_snapshot_entry_to_source_node(
        self, entry_id: str, source_node_id: str
    ) -> entities.OriginalSnapshotEntry:
        row = self._session.get(models.OriginalSnapshotEntryModel, entry_id)
        if row is None:
            raise EntityNotFoundError(f"snapshot entry not found: {entry_id}")
        if row.source_node_id is not None:
            raise ConcurrentStateError(
                "snapshot entry source node binding is already assigned"
            )
        node = self._session.get(models.NodeModel, source_node_id)
        if node is None:
            raise EntityNotFoundError(f"source node not found: {source_node_id}")
        if node.project_id != row.project_id:
            raise InvariantViolationError(
                "snapshot entry and source node must belong to the same project"
            )
        row.source_node_id = source_node_id
        self._session.flush([row])
        return _snapshot_entry_from_model(row)


class SqlAlchemyWorkspaceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _require_parent(
        self,
        project_id: str,
        parent_id: Optional[str],
        *,
        allow_container_view: bool = False,
    ) -> Optional[models.WorkspaceItemModel]:
        if parent_id is None:
            return None
        parent = self._session.get(models.WorkspaceItemModel, parent_id)
        if parent is None:
            raise EntityNotFoundError(f"workspace parent not found: {parent_id}")
        if parent.project_id != project_id:
            raise InvariantViolationError("workspace placement cannot cross projects")
        if parent.lifecycle_status != enums.WorkspaceItemLifecycleStatus.ACTIVE:
            raise InvariantViolationError("workspace parent must be active")
        if not self.is_effectively_active(parent_id):
            raise InvariantViolationError(
                "workspace parent cannot have a deleted ancestor"
            )
        allowed_kinds = {enums.WorkspaceItemKind.FOLDER}
        if allow_container_view:
            allowed_kinds.add(enums.WorkspaceItemKind.CONTAINER_VIEW)
        if parent.item_kind not in allowed_kinds:
            raise InvariantViolationError(
                "workspace parent must be an ordinary folder"
            )
        return parent

    def _item_row(self, item_id: str) -> models.WorkspaceItemModel:
        row = self._session.get(models.WorkspaceItemModel, item_id)
        if row is None:
            raise EntityNotFoundError(f"workspace item not found: {item_id}")
        return row

    def _placement_row(self, item_id: str) -> models.WorkspacePlacementModel:
        row = self._session.get(models.WorkspacePlacementModel, item_id)
        if row is None:
            raise EntityNotFoundError(f"workspace placement not found: {item_id}")
        return row

    def _active_sibling_rows(
        self, project_id: str, parent_id: Optional[str]
    ) -> list[models.WorkspacePlacementModel]:
        parent_clause = (
            models.WorkspacePlacementModel.parent_workspace_item_id.is_(None)
            if parent_id is None
            else models.WorkspacePlacementModel.parent_workspace_item_id == parent_id
        )
        return list(
            self._session.scalars(
                select(models.WorkspacePlacementModel)
                .join(
                    models.WorkspaceItemModel,
                    models.WorkspaceItemModel.id
                    == models.WorkspacePlacementModel.workspace_item_id,
                )
                .where(
                    models.WorkspacePlacementModel.project_id == project_id,
                    parent_clause,
                    models.WorkspaceItemModel.lifecycle_status
                    == enums.WorkspaceItemLifecycleStatus.ACTIVE,
                )
                .order_by(
                    models.WorkspacePlacementModel.ordinal,
                    models.WorkspacePlacementModel.workspace_item_id,
                )
            ).all()
        )

    @staticmethod
    def _resequence(
        rows: Sequence[models.WorkspacePlacementModel], updated_at: datetime
    ) -> None:
        for ordinal, row in enumerate(rows):
            row.ordinal = ordinal
            row.updated_at = updated_at

    def _would_cycle(self, item_id: str, parent_id: Optional[str]) -> bool:
        if parent_id is None:
            return False
        found = self._session.scalar(
            text(
                "WITH RECURSIVE subtree(id) AS ("
                " SELECT :item_id"
                " UNION ALL"
                " SELECT p.workspace_item_id"
                " FROM workspace_placements p JOIN subtree s"
                " ON p.parent_workspace_item_id = s.id"
                ") SELECT 1 FROM subtree WHERE id = :parent_id LIMIT 1"
            ),
            {"item_id": item_id, "parent_id": parent_id},
        )
        return found is not None

    def add_item(
        self,
        item: entities.WorkspaceItem,
        placement: entities.WorkspacePlacement,
        *,
        allow_container_parent: bool = False,
    ) -> None:
        if (
            placement.workspace_item_id != item.id
            or placement.project_id != item.project_id
        ):
            raise InvariantViolationError(
                "workspace item and placement identity must match"
            )
        self._require_parent(
            item.project_id,
            placement.parent_workspace_item_id,
            allow_container_view=allow_container_parent,
        )
        if item.item_kind != enums.WorkspaceItemKind.FILE and (
            item.materialization_status
            != enums.WorkspaceMaterializationStatus.VIRTUAL
        ):
            raise InvariantViolationError(
                "folders and container views must remain virtual in V1"
            )
        item_row = models.WorkspaceItemModel(
            id=item.id,
            project_id=item.project_id,
            origin_source_node_id=item.origin_source_node_id,
            item_kind=item.item_kind,
            display_name=item.display_name,
            lifecycle_status=item.lifecycle_status,
            materialization_status=item.materialization_status,
            created_at=item.created_at,
            updated_at=item.updated_at,
            deleted_at=item.deleted_at,
        )
        placement_row = models.WorkspacePlacementModel(
            workspace_item_id=placement.workspace_item_id,
            project_id=placement.project_id,
            parent_workspace_item_id=placement.parent_workspace_item_id,
            ordinal=placement.ordinal,
            previous_parent_id=placement.previous_parent_id,
            previous_ordinal=placement.previous_ordinal,
            updated_at=placement.updated_at,
        )
        self._session.add(item_row)
        self._session.flush([item_row])
        self._session.add(placement_row)
        self._session.flush([placement_row])

    def get_item(self, item_id: str) -> Optional[entities.WorkspaceItem]:
        row = self._session.get(models.WorkspaceItemModel, item_id)
        return None if row is None else _workspace_item_from_model(row)

    def items_for_project(
        self, project_id: str, *, include_deleted: bool = False
    ) -> Sequence[entities.WorkspaceItem]:
        statement = select(models.WorkspaceItemModel).where(
            models.WorkspaceItemModel.project_id == project_id
        )
        if not include_deleted:
            statement = statement.where(
                models.WorkspaceItemModel.lifecycle_status
                == enums.WorkspaceItemLifecycleStatus.ACTIVE
            )
        else:
            statement = statement.where(
                models.WorkspaceItemModel.lifecycle_status
                != enums.WorkspaceItemLifecycleStatus.PURGED
            )
        rows = self._session.scalars(
            statement.order_by(
                models.WorkspaceItemModel.created_at,
                models.WorkspaceItemModel.id,
            )
        ).all()
        return [_workspace_item_from_model(row) for row in rows]

    def get_placement(
        self, item_id: str
    ) -> Optional[entities.WorkspacePlacement]:
        row = self._session.get(models.WorkspacePlacementModel, item_id)
        return None if row is None else _placement_from_model(row)

    def children_for_parent(
        self,
        project_id: str,
        parent_id: Optional[str],
        *,
        include_deleted: bool = False,
    ) -> Sequence[tuple[entities.WorkspaceItem, entities.WorkspacePlacement]]:
        parent_clause = (
            models.WorkspacePlacementModel.parent_workspace_item_id.is_(None)
            if parent_id is None
            else models.WorkspacePlacementModel.parent_workspace_item_id == parent_id
        )
        statement = (
            select(models.WorkspaceItemModel, models.WorkspacePlacementModel)
            .join(
                models.WorkspacePlacementModel,
                models.WorkspacePlacementModel.workspace_item_id
                == models.WorkspaceItemModel.id,
            )
            .where(
                models.WorkspaceItemModel.project_id == project_id,
                parent_clause,
            )
        )
        if not include_deleted:
            statement = statement.where(
                models.WorkspaceItemModel.lifecycle_status
                == enums.WorkspaceItemLifecycleStatus.ACTIVE
            )
        else:
            statement = statement.where(
                models.WorkspaceItemModel.lifecycle_status
                != enums.WorkspaceItemLifecycleStatus.PURGED
            )
        rows = self._session.execute(
            statement.order_by(
                models.WorkspacePlacementModel.ordinal,
                models.WorkspaceItemModel.id,
            )
        ).all()
        return [
            (_workspace_item_from_model(item), _placement_from_model(placement))
            for item, placement in rows
        ]

    def is_effectively_active(self, item_id: str) -> bool:
        item = self._session.get(models.WorkspaceItemModel, item_id)
        if item is None:
            raise EntityNotFoundError(f"workspace item not found: {item_id}")
        visited: set[str] = set()
        current: Optional[models.WorkspaceItemModel] = item
        while current is not None:
            if current.id in visited:
                raise InvariantViolationError("workspace placement contains a cycle")
            visited.add(current.id)
            if current.lifecycle_status != enums.WorkspaceItemLifecycleStatus.ACTIVE:
                return False
            placement = self._session.get(models.WorkspacePlacementModel, current.id)
            if placement is None or placement.parent_workspace_item_id is None:
                return True
            current = self._session.get(
                models.WorkspaceItemModel, placement.parent_workspace_item_id
            )
            if current is None:
                raise InvariantViolationError("workspace placement parent is missing")
        return True

    def insert_item(
        self,
        item: entities.WorkspaceItem,
        *,
        parent_id: Optional[str],
        ordinal: int,
        updated_at: datetime,
    ) -> entities.WorkspacePlacement:
        self._require_parent(item.project_id, parent_id)
        siblings = self._active_sibling_rows(item.project_id, parent_id)
        if ordinal < 0 or ordinal > len(siblings):
            raise InvariantViolationError(
                "workspace ordinal must be a valid sibling insertion index"
            )
        for sibling_index, row in enumerate(siblings):
            desired = sibling_index if sibling_index < ordinal else sibling_index + 1
            row.ordinal = desired
            row.updated_at = updated_at
        placement = entities.WorkspacePlacement(
            workspace_item_id=item.id,
            project_id=item.project_id,
            parent_workspace_item_id=parent_id,
            ordinal=ordinal,
            updated_at=updated_at,
        )
        self.add_item(item, placement)
        return placement

    def move_item(
        self,
        item_id: str,
        *,
        new_parent_id: Optional[str],
        new_ordinal: int,
        updated_at: datetime,
    ) -> entities.WorkspacePlacement:
        item = self._item_row(item_id)
        placement = self._placement_row(item_id)
        if not self.is_effectively_active(item_id):
            raise InvariantViolationError(
                "workspace item with a deleted ancestor cannot be moved"
            )
        self._require_parent(item.project_id, new_parent_id)
        if self._would_cycle(item_id, new_parent_id):
            raise InvariantViolationError("workspace placement would create a cycle")

        old_parent_id = placement.parent_workspace_item_id
        if old_parent_id == new_parent_id:
            siblings = [
                row
                for row in self._active_sibling_rows(item.project_id, old_parent_id)
                if row.workspace_item_id != item_id
            ]
            if new_ordinal < 0 or new_ordinal > len(siblings):
                raise InvariantViolationError(
                    "workspace ordinal must be a valid sibling insertion index"
                )
            siblings.insert(new_ordinal, placement)
            self._resequence(siblings, updated_at)
        else:
            old_siblings = [
                row
                for row in self._active_sibling_rows(item.project_id, old_parent_id)
                if row.workspace_item_id != item_id
            ]
            new_siblings = self._active_sibling_rows(item.project_id, new_parent_id)
            if new_ordinal < 0 or new_ordinal > len(new_siblings):
                raise InvariantViolationError(
                    "workspace ordinal must be a valid sibling insertion index"
                )
            self._resequence(old_siblings, updated_at)
            new_siblings.insert(new_ordinal, placement)
            self._resequence(new_siblings, updated_at)
        placement.parent_workspace_item_id = new_parent_id
        placement.ordinal = new_ordinal
        placement.updated_at = updated_at
        item.updated_at = updated_at
        self._session.flush()
        return _placement_from_model(placement)

    def soft_delete_item(
        self,
        item_id: str,
        *,
        updated_at: datetime,
    ) -> tuple[entities.WorkspaceItem, entities.WorkspacePlacement]:
        item = self._item_row(item_id)
        placement = self._placement_row(item_id)
        if not self.is_effectively_active(item_id):
            raise InvariantViolationError(
                "workspace item is deleted or has a deleted ancestor"
            )
        placement.previous_parent_id = placement.parent_workspace_item_id
        placement.previous_ordinal = placement.ordinal
        siblings = [
            row
            for row in self._active_sibling_rows(
                item.project_id, placement.parent_workspace_item_id
            )
            if row.workspace_item_id != item_id
        ]
        self._resequence(siblings, updated_at)
        updated = self.update_lifecycle(
            item_id,
            enums.WorkspaceItemLifecycleStatus.ACTIVE,
            enums.WorkspaceItemLifecycleStatus.DELETED,
            updated_at=updated_at,
            deleted_at=updated_at,
        )
        placement.updated_at = updated_at
        self._session.flush()
        return updated, _placement_from_model(placement)

    def restore_item(
        self,
        item_id: str,
        *,
        updated_at: datetime,
    ) -> tuple[entities.WorkspaceItem, entities.WorkspacePlacement, bool]:
        item = self._item_row(item_id)
        placement = self._placement_row(item_id)
        if item.lifecycle_status != enums.WorkspaceItemLifecycleStatus.DELETED:
            raise InvariantViolationError("workspace item is not deleted")
        if placement.previous_ordinal is None:
            raise InvariantViolationError("workspace item has no restore placement")

        target_parent = placement.previous_parent_id
        fallback = False
        if target_parent is not None:
            try:
                self._require_parent(
                    item.project_id,
                    target_parent,
                    allow_container_view=True,
                )
            except (EntityNotFoundError, InvariantViolationError):
                target_parent = None
                fallback = True
        if self._would_cycle(item_id, target_parent):
            target_parent = None
            fallback = True

        siblings = self._active_sibling_rows(item.project_id, target_parent)
        target_ordinal = min(placement.previous_ordinal, len(siblings))
        siblings.insert(target_ordinal, placement)
        self._resequence(siblings, updated_at)
        placement.parent_workspace_item_id = target_parent
        placement.ordinal = target_ordinal
        placement.previous_parent_id = None
        placement.previous_ordinal = None
        placement.updated_at = updated_at
        updated = self.update_lifecycle(
            item_id,
            enums.WorkspaceItemLifecycleStatus.DELETED,
            enums.WorkspaceItemLifecycleStatus.ACTIVE,
            updated_at=updated_at,
            deleted_at=None,
        )
        self._session.flush()
        return updated, _placement_from_model(placement), fallback

    def purge_items(
        self,
        item_ids: Sequence[str],
        *,
        updated_at: datetime,
    ) -> Sequence[entities.WorkspaceItem]:
        identifiers = tuple(dict.fromkeys(item_ids))
        if not identifiers:
            raise InvariantViolationError("purge requires at least one workspace item")
        rows = list(
            self._session.scalars(
                select(models.WorkspaceItemModel).where(
                    models.WorkspaceItemModel.id.in_(identifiers)
                )
            ).all()
        )
        if len(rows) != len(identifiers):
            raise EntityNotFoundError("one or more workspace purge items are missing")
        project_ids = {row.project_id for row in rows}
        if len(project_ids) != 1:
            raise InvariantViolationError("workspace purge cannot cross projects")
        affected = set(identifiers)
        old_parents: set[Optional[str]] = set()
        for row in rows:
            if row.lifecycle_status == enums.WorkspaceItemLifecycleStatus.PURGED:
                raise InvariantViolationError("workspace item is already purged")
            require_workspace_lifecycle_transition(
                row.lifecycle_status, enums.WorkspaceItemLifecycleStatus.PURGED
            )
            placement = self._placement_row(row.id)
            old_parents.add(placement.parent_workspace_item_id)
            row.lifecycle_status = enums.WorkspaceItemLifecycleStatus.PURGED
            row.deleted_at = updated_at
            row.updated_at = updated_at
            placement.updated_at = updated_at
        for parent_id in old_parents:
            siblings = [
                value
                for value in self._active_sibling_rows(next(iter(project_ids)), parent_id)
                if value.workspace_item_id not in affected
            ]
            self._resequence(siblings, updated_at)
        self._session.flush()
        return tuple(_workspace_item_from_model(row) for row in rows)

    def update_lifecycle(
        self,
        item_id: str,
        expected_status: enums.WorkspaceItemLifecycleStatus,
        new_status: enums.WorkspaceItemLifecycleStatus,
        *,
        updated_at: datetime,
        deleted_at: Optional[datetime],
    ) -> entities.WorkspaceItem:
        row = self._session.get(models.WorkspaceItemModel, item_id)
        if row is None:
            raise EntityNotFoundError(f"workspace item not found: {item_id}")
        if row.lifecycle_status != expected_status:
            raise ConcurrentStateError(
                "workspace lifecycle changed concurrently: "
                f"expected {expected_status.value}, found {row.lifecycle_status.value}"
            )
        require_workspace_lifecycle_transition(expected_status, new_status)
        if (
            new_status in {
                enums.WorkspaceItemLifecycleStatus.DELETED,
                enums.WorkspaceItemLifecycleStatus.PURGED,
            }
            and deleted_at is None
        ) or (
            new_status == enums.WorkspaceItemLifecycleStatus.ACTIVE
            and deleted_at is not None
        ):
            raise InvariantViolationError(
                "deleted_at must match workspace lifecycle status"
            )
        row.lifecycle_status = new_status
        row.deleted_at = deleted_at
        row.updated_at = updated_at
        self._session.flush([row])
        return _workspace_item_from_model(row)

    def update_materialization_status(
        self,
        item_id: str,
        expected_status: enums.WorkspaceMaterializationStatus,
        new_status: enums.WorkspaceMaterializationStatus,
        *,
        updated_at: datetime,
    ) -> entities.WorkspaceItem:
        row = self._session.get(models.WorkspaceItemModel, item_id)
        if row is None:
            raise EntityNotFoundError(f"workspace item not found: {item_id}")
        if row.materialization_status != expected_status:
            raise ConcurrentStateError(
                "workspace materialization changed concurrently: "
                f"expected {expected_status.value}, "
                f"found {row.materialization_status.value}"
            )
        if row.item_kind != enums.WorkspaceItemKind.FILE:
            raise InvariantViolationError(
                "only workspace files can change materialization state"
            )
        require_workspace_materialization_transition(expected_status, new_status)
        row.materialization_status = new_status
        row.updated_at = updated_at
        self._session.flush([row])
        return _workspace_item_from_model(row)

    def add_working_artifact(self, artifact: entities.WorkingArtifact) -> None:
        item = self._session.get(models.WorkspaceItemModel, artifact.workspace_item_id)
        if item is None:
            raise EntityNotFoundError(
                f"workspace item not found: {artifact.workspace_item_id}"
            )
        if item.project_id != artifact.project_id:
            raise InvariantViolationError(
                "working artifact and workspace item must belong to the same project"
            )
        if item.item_kind != enums.WorkspaceItemKind.FILE:
            raise InvariantViolationError(
                "working artifacts can materialize only workspace files"
            )
        row = models.WorkingArtifactModel(
            id=artifact.id,
            project_id=artifact.project_id,
            workspace_item_id=artifact.workspace_item_id,
            storage_key=artifact.storage_key,
            baseline_size=artifact.baseline_size,
            baseline_sha256=artifact.baseline_sha256,
            current_size=artifact.current_size,
            current_sha256=artifact.current_sha256,
            content_status=artifact.content_status,
            materialized_at=artifact.materialized_at,
            last_checked_at=artifact.last_checked_at,
            updated_at=artifact.updated_at,
        )
        self._session.add(row)
        self._session.flush([row])

    def get_working_artifact(
        self, artifact_id: str
    ) -> Optional[entities.WorkingArtifact]:
        row = self._session.get(models.WorkingArtifactModel, artifact_id)
        return None if row is None else _working_artifact_from_model(row)

    def working_artifact_for_item(
        self, item_id: str
    ) -> Optional[entities.WorkingArtifact]:
        row = self._session.scalar(
            select(models.WorkingArtifactModel).where(
                models.WorkingArtifactModel.workspace_item_id == item_id
            )
        )
        return None if row is None else _working_artifact_from_model(row)

    def update_working_content(
        self,
        artifact_id: str,
        expected_status: enums.WorkingContentStatus,
        new_status: enums.WorkingContentStatus,
        *,
        expected_updated_at: datetime,
        current_size: Optional[int],
        current_sha256: Optional[str],
        last_checked_at: datetime,
        updated_at: datetime,
    ) -> entities.WorkingArtifact:
        row = self._session.get(models.WorkingArtifactModel, artifact_id)
        if row is None:
            raise EntityNotFoundError(f"working artifact not found: {artifact_id}")
        if row.content_status != expected_status:
            raise ConcurrentStateError(
                "working content status changed concurrently: "
                f"expected {expected_status.value}, found {row.content_status.value}"
            )
        if row.updated_at != expected_updated_at:
            raise ConcurrentStateError(
                "working content changed concurrently: updated_at no longer matches"
            )
        require_working_content_transition(expected_status, new_status)
        row.content_status = new_status
        if current_size is not None:
            row.current_size = current_size
        if current_sha256 is not None:
            row.current_sha256 = current_sha256
        row.last_checked_at = last_checked_at
        row.updated_at = updated_at
        self._session.flush([row])
        return _working_artifact_from_model(row)

    def set_working_revision(
        self, revision: entities.WorkingRevision
    ) -> entities.WorkingRevision:
        artifact = self._session.get(
            models.WorkingArtifactModel, revision.working_artifact_id
        )
        if artifact is None:
            raise EntityNotFoundError(
                f"working artifact not found: {revision.working_artifact_id}"
            )
        if artifact.project_id != revision.project_id:
            raise InvariantViolationError(
                "working revision and artifact must belong to the same project"
            )
        row = self._session.scalar(
            select(models.WorkingRevisionModel).where(
                models.WorkingRevisionModel.working_artifact_id
                == revision.working_artifact_id,
                models.WorkingRevisionModel.role == revision.role,
            )
        )
        if row is None:
            row = models.WorkingRevisionModel(
                id=revision.id,
                project_id=revision.project_id,
                working_artifact_id=revision.working_artifact_id,
                role=revision.role,
                storage_key=revision.storage_key,
                size=revision.size,
                sha256=revision.sha256,
                file_modified_at=revision.file_modified_at,
                detected_at=revision.detected_at,
                created_at=revision.created_at,
                updated_at=revision.updated_at,
            )
            self._session.add(row)
        else:
            row.storage_key = revision.storage_key
            row.size = revision.size
            row.sha256 = revision.sha256
            row.file_modified_at = revision.file_modified_at
            row.detected_at = revision.detected_at
            row.updated_at = revision.updated_at
        self._session.flush([row])
        return _working_revision_from_model(row)

    def working_revision_for_artifact(
        self,
        artifact_id: str,
        role: enums.WorkingRevisionRole,
    ) -> Optional[entities.WorkingRevision]:
        row = self._session.scalar(
            select(models.WorkingRevisionModel).where(
                models.WorkingRevisionModel.working_artifact_id == artifact_id,
                models.WorkingRevisionModel.role == role,
            )
        )
        return None if row is None else _working_revision_from_model(row)

    def working_revisions_for_artifact(
        self, artifact_id: str
    ) -> Sequence[entities.WorkingRevision]:
        rows = self._session.scalars(
            select(models.WorkingRevisionModel)
            .where(models.WorkingRevisionModel.working_artifact_id == artifact_id)
            .order_by(models.WorkingRevisionModel.role)
        ).all()
        return tuple(_working_revision_from_model(row) for row in rows)
