from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from pig.application.contracts import (
    ImportUndoImpact,
    PreviewImportUndoRequest,
    UndoImportedItemRequest,
    UndoImportedItemResult,
)
from pig.application.errors import ApplicationError
from pig.application.ports import ImportUndoStore, ProjectDatabaseProvider
from pig.domain.entities import ProcessingEvent
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    ErrorCode,
    EventSeverity,
    EventType,
    OriginalSnapshotStatus,
    SourceStatus,
    WorkingContentStatus,
    WorkspaceItemLifecycleStatus,
)
from pig.domain.exceptions import EntityNotFoundError
from pig.domain.model_version import WORKBENCH_MODEL_VERSION


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


@dataclass(frozen=True, slots=True)
class _UndoPlan:
    impact: ImportUndoImpact
    snapshot_status: OriginalSnapshotStatus
    source_status: SourceStatus
    artifact_statuses: tuple[tuple[str, ArtifactIntegrityStatus], ...]
    workspace_item_ids: tuple[str, ...]
    working_storage_keys: tuple[str, ...]
    revision_storage_keys: tuple[str, ...]


class ImportUndoService:
    """Undo one completed top-level imported input without touching its external source."""

    def __init__(
        self,
        *,
        database: ProjectDatabaseProvider,
        store: ImportUndoStore,
        clock: Clock = _utc_now,
        id_generator: IdGenerator = _new_id,
    ) -> None:
        self._database = database
        self._store = store
        self._clock = clock
        self._new_id = id_generator

    def preview(self, request: PreviewImportUndoRequest) -> ImportUndoImpact:
        project_id, database_path, item_id = self._identity(
            request.project_id, request.database_path, request.workspace_item_id
        )
        return self._plan(project_id, database_path, item_id).impact

    def undo(self, request: UndoImportedItemRequest) -> UndoImportedItemResult:
        project_id, database_path, item_id = self._identity(
            request.project_id, request.database_path, request.workspace_item_id
        )
        actor = request.actor.strip()
        if not actor:
            raise ApplicationError("INVALID_REQUEST", "actor is required")
        if not request.confirmed:
            raise ApplicationError(
                "IMPORT_ITEM_UNDO_CONFIRMATION_REQUIRED",
                "undoing an imported input requires confirmation",
            )
        plan = self._plan(project_id, database_path, item_id)
        operation_id = self._new_id()
        with self._database.unit_of_work(database_path) as uow:
            project = self._project(uow, project_id, database_path)
            if project.workspace_revision != request.expected_workspace_revision:
                raise ApplicationError(
                    "WORKSPACE_REVISION_CONFLICT",
                    "Workspace changed; reload before undoing the imported input",
                )
            self._event(
                uow,
                EventType.IMPORT_ITEM_UNDO_REQUESTED,
                project_id,
                actor,
                operation_id,
                source_id=plan.impact.source_id,
                snapshot_id=plan.impact.snapshot_id,
                workspace_item_id=item_id,
                details=self._impact_details(plan.impact),
            )
            uow.commit()

        try:
            with self._store.begin(
                database_path.parent,
                operation_id,
                plan.impact.snapshot_id,
                project_id=project_id,
                working_storage_keys=plan.working_storage_keys,
                revision_storage_keys=plan.revision_storage_keys,
            ) as storage:
                storage.stage()
                now = self._clock()
                with self._database.unit_of_work(database_path) as uow:
                    project = self._project(uow, project_id, database_path)
                    if project.workspace_revision != request.expected_workspace_revision:
                        raise ApplicationError(
                            "WORKSPACE_REVISION_CONFLICT",
                            "Workspace changed while the import undo was staged",
                        )
                    snapshot = uow.imports.get_snapshot(plan.impact.snapshot_id)
                    source = uow.catalog.get_source(plan.impact.source_id)
                    if snapshot is None or source is None:
                        raise EntityNotFoundError("import undo source facts disappeared")
                    uow.imports.update_snapshot_status(
                        snapshot.id,
                        snapshot.status,
                        OriginalSnapshotStatus.PURGED,
                    )
                    for artifact_id, expected in plan.artifact_statuses:
                        uow.imports.update_original_artifact_integrity(
                            artifact_id, expected, ArtifactIntegrityStatus.PURGED
                        )
                    uow.catalog.update_source_status(
                        source.id, source.status, SourceStatus.PURGED, None
                    )
                    uow.workspace.purge_items(
                        plan.workspace_item_ids, updated_at=now
                    )
                    updated_project = uow.projects.advance_workspace_revision(
                        project_id,
                        request.expected_workspace_revision,
                        updated_at=now,
                    )
                    self._event(
                        uow,
                        EventType.IMPORT_ITEM_UNDO_COMPLETED,
                        project_id,
                        actor,
                        operation_id,
                        source_id=source.id,
                        snapshot_id=snapshot.id,
                        workspace_item_id=item_id,
                        previous_status=snapshot.status.value,
                        new_status=OriginalSnapshotStatus.PURGED.value,
                        details={
                            **self._impact_details(plan.impact),
                            "removed_byte_count": storage.removed_size,
                            "workspace_revision": updated_project.workspace_revision,
                        },
                    )
                    uow.commit()
                storage.complete()
        except BaseException as exc:
            self._failed(database_path, project_id, actor, operation_id, plan, exc)
            raise

        return UndoImportedItemResult(
            project_id=project_id,
            workspace_item_id=item_id,
            snapshot_id=plan.impact.snapshot_id,
            source_id=plan.impact.source_id,
            workspace_revision=updated_project.workspace_revision,
            purged_workspace_item_count=plan.impact.workspace_item_count,
            removed_byte_count=storage.removed_size,
        )

    def _plan(self, project_id: str, database_path: Path, item_id: str) -> _UndoPlan:
        with self._database.unit_of_work(database_path) as uow:
            self._project(uow, project_id, database_path)
            selected = uow.workspace.get_item(item_id)
            if selected is None or selected.project_id != project_id:
                raise EntityNotFoundError(f"workspace item not found: {item_id}")
            if selected.lifecycle_status == WorkspaceItemLifecycleStatus.PURGED:
                raise ApplicationError(
                    ErrorCode.IMPORT_ITEM_NOT_UNDOABLE.value,
                    "the imported input is already purged",
                )
            if selected.origin_source_node_id is None:
                raise self._not_undoable("only a source-backed import root can be undone")
            node = uow.catalog.get_node(selected.origin_source_node_id)
            if node is None:
                raise self._not_undoable("the Workspace Item has no Source Node")
            source = uow.catalog.get_source(node.source_id)
            if source is None or source.project_id != project_id:
                raise self._not_undoable("the Workspace Item has no Source")
            if source.root_node_id != node.id:
                raise self._not_undoable(
                    "only the top-level imported input can be undone"
                )
            snapshot = uow.imports.get_snapshot(source.snapshot_id)
            if snapshot is None or snapshot.status == OriginalSnapshotStatus.PURGED:
                raise self._not_undoable("the imported input is unavailable or purged")
            session_items = uow.imports.items_for_session(snapshot.import_session_id)
            if not any(value.snapshot_id == snapshot.id for value in session_items):
                raise self._not_undoable("the Snapshot has no top-level Import Item")

            source_node_ids = {
                value.id
                for value in uow.catalog.nodes_for_project(project_id)
                if value.source_id == source.id
            }
            all_items = tuple(
                uow.workspace.items_for_project(project_id, include_deleted=True)
            )
            affected = tuple(
                value
                for value in all_items
                if value.origin_source_node_id in source_node_ids
            )
            affected_ids = {value.id for value in affected}
            if selected.id not in affected_ids:
                raise self._not_undoable("the import root is not represented in Workspace")
            placements = {
                value.id: uow.workspace.get_placement(value.id) for value in all_items
            }
            for value in all_items:
                if value.id in affected_ids:
                    continue
                current = placements[value.id]
                visited: set[str] = set()
                while current is not None and current.parent_workspace_item_id is not None:
                    parent_id = current.parent_workspace_item_id
                    if parent_id in affected_ids:
                        raise self._not_undoable(
                            "the imported tree contains Workspace content from another source"
                        )
                    if parent_id in visited:
                        break
                    visited.add(parent_id)
                    current = placements.get(parent_id)

            artifacts = tuple(uow.imports.original_artifacts_for_snapshot(snapshot.id))
            workings = tuple(
                value
                for item in affected
                if (value := uow.workspace.working_artifact_for_item(item.id)) is not None
            )
            revisions = tuple(
                revision
                for working in workings
                for revision in uow.workspace.working_revisions_for_artifact(working.id)
            )
            original_bytes = sum(value.size for value in artifacts)
            working_bytes = sum(value.current_size for value in workings) + sum(
                value.size for value in revisions
            )
            impact = ImportUndoImpact(
                project_id=project_id,
                workspace_item_id=item_id,
                snapshot_id=snapshot.id,
                source_id=source.id,
                display_name=snapshot.original_display_name,
                workspace_item_count=len(affected),
                working_file_count=len(workings),
                modified_working_file_count=sum(
                    value.content_status == WorkingContentStatus.MODIFIED
                    for value in workings
                ),
                original_byte_count=original_bytes,
                working_byte_count=working_bytes,
            )
            return _UndoPlan(
                impact=impact,
                snapshot_status=snapshot.status,
                source_status=source.status,
                artifact_statuses=tuple(
                    (value.id, value.integrity_status) for value in artifacts
                ),
                workspace_item_ids=tuple(value.id for value in affected),
                working_storage_keys=tuple(value.storage_key for value in workings),
                revision_storage_keys=tuple(value.storage_key for value in revisions),
            )

    def _failed(self, database_path, project_id, actor, operation_id, plan, exc) -> None:
        try:
            with self._database.unit_of_work(database_path) as uow:
                self._event(
                    uow,
                    EventType.IMPORT_ITEM_UNDO_FAILED,
                    project_id,
                    actor,
                    operation_id,
                    source_id=plan.impact.source_id,
                    snapshot_id=plan.impact.snapshot_id,
                    workspace_item_id=plan.impact.workspace_item_id,
                    severity=EventSeverity.ERROR,
                    error_code=ErrorCode.IMPORT_ITEM_UNDO_FAILED,
                    details={"failure_code": getattr(exc, "code", type(exc).__name__)},
                )
                uow.commit()
        except BaseException:
            return

    def _event(
        self,
        uow,
        event_type,
        project_id,
        actor,
        correlation_id,
        *,
        source_id=None,
        snapshot_id=None,
        workspace_item_id=None,
        severity=EventSeverity.INFO,
        error_code=None,
        previous_status=None,
        new_status=None,
        details=None,
    ) -> None:
        uow.processing.append_event(
            ProcessingEvent(
                id=self._new_id(),
                event_type=event_type,
                project_id=project_id,
                actor=actor,
                occurred_at=self._clock(),
                severity=severity,
                source_id=source_id,
                snapshot_id=snapshot_id,
                workspace_item_id=workspace_item_id,
                correlation_id=correlation_id,
                error_code=error_code,
                previous_status=previous_status,
                new_status=new_status,
                details={} if details is None else details,
            )
        )

    @staticmethod
    def _impact_details(value: ImportUndoImpact) -> dict[str, object]:
        return {
            "display_name": value.display_name,
            "workspace_item_count": value.workspace_item_count,
            "working_file_count": value.working_file_count,
            "modified_working_file_count": value.modified_working_file_count,
            "original_byte_count": value.original_byte_count,
            "working_byte_count": value.working_byte_count,
        }

    @staticmethod
    def _not_undoable(message: str) -> ApplicationError:
        return ApplicationError(ErrorCode.IMPORT_ITEM_NOT_UNDOABLE.value, message)

    @staticmethod
    def _identity(project_id: str, database_path: Path, item_id: str):
        project = project_id.strip()
        item = item_id.strip()
        path = Path(database_path).expanduser().resolve(strict=False)
        if not project or not item or not path.is_absolute():
            raise ApplicationError("INVALID_REQUEST", "complete undo identity is required")
        return project, path, item

    @staticmethod
    def _project(uow, project_id: str, database_path: Path):
        project = uow.projects.get(project_id)
        if project is None:
            raise EntityNotFoundError(f"project not found: {project_id}")
        if project.model_version != WORKBENCH_MODEL_VERSION:
            raise ApplicationError(
                "UNSUPPORTED_PROJECT_MODEL_VERSION", "unsupported Project data model"
            )
        if database_path.parent.as_uri() != project.workspace_locator:
            raise ApplicationError(
                "PROJECT_DATABASE_MISMATCH", "database path is outside the Project workspace"
            )
        return project
