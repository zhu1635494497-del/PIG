from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable
from uuid import uuid4

from pig.application.contracts import (
    ExportWorkspaceItemsRequest,
    ExportWorkspaceItemsResult,
    MaterializeWorkspaceItemRequest,
    RefreshWorkingArtifactRequest,
)
from pig.application.errors import ApplicationError
from pig.application.ports import (
    ProjectDatabaseProvider,
    WorkspaceExportDirectory,
    WorkspaceExportEntry,
    WorkspaceExportStore,
)
from pig.domain.entities import ProcessingEvent
from pig.domain.enums import (
    ErrorCode,
    EventSeverity,
    EventType,
    WorkingContentStatus,
    WorkingRefreshReason,
    WorkspaceItemKind,
    WorkspaceExportKind,
)
from pig.domain.exceptions import EntityNotFoundError, InvariantViolationError
from pig.domain.model_version import WORKBENCH_MODEL_VERSION
from pig.domain.paths import safe_filesystem_segment


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


class WorkspaceExportService:
    """Export current Workspace file bytes without rewriting source Containers."""

    def __init__(
        self,
        *,
        database: ProjectDatabaseProvider,
        structure_service,
        working_file_service,
        store: WorkspaceExportStore,
        clock: Clock = _utc_now,
        id_generator: IdGenerator = _new_id,
    ) -> None:
        self._database = database
        self._structure = structure_service
        self._working_files = working_file_service
        self._store = store
        self._clock = clock
        self._new_id = id_generator

    def export(self, request: ExportWorkspaceItemsRequest) -> ExportWorkspaceItemsResult:
        project_id = request.project_id.strip()
        actor = request.actor.strip()
        database_path = Path(request.database_path).expanduser().resolve(strict=False)
        destination = Path(request.destination_path).expanduser().resolve(strict=False)
        item_ids = tuple(dict.fromkeys(request.workspace_item_ids))
        if (
            not project_id
            or not actor
            or not database_path.is_absolute()
            or not destination.is_absolute()
            or not item_ids
            or any(not value.strip() for value in item_ids)
        ):
            raise ApplicationError("INVALID_REQUEST", "complete export identity is required")
        operation_id = self._new_id()
        project_path = database_path.parent.resolve(strict=False)
        try:
            destination.relative_to(project_path)
        except ValueError:
            pass
        else:
            raise ApplicationError(
                ErrorCode.EXPORT_DESTINATION_INVALID.value,
                "exports must be written outside the managed Project directory",
            )

        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            self._project(project, database_path)
            all_items = tuple(
                uow.workspace.items_for_project(project_id, include_deleted=True)
            )
            by_id = {item.id: item for item in all_items}
            placements = {
                item.id: uow.workspace.get_placement(item.id) for item in all_items
            }
            selected = []
            for item_id in item_ids:
                item = by_id.get(item_id)
                if item is None:
                    raise EntityNotFoundError(f"workspace item not found: {item_id}")
                if not uow.workspace.is_effectively_active(item.id):
                    raise ApplicationError(
                        "EXPORT_ITEM_DENIED",
                        "only effectively active Workspace items can be exported",
                        {"workspace_item_id": item.id},
                    )
                selected.append(item)
            if len(selected) == 1 and selected[0].item_kind == WorkspaceItemKind.FILE:
                export_kind = WorkspaceExportKind.FILE
                export_items = tuple(selected)
                export_directories = ()
            elif len(selected) == 1 and selected[0].item_kind == WorkspaceItemKind.FOLDER:
                export_kind = WorkspaceExportKind.DIRECTORY
                directory_root_id = selected[0].id
                subtree = self._active_subtree(
                    selected[0].id, by_id, placements, uow.workspace
                )
                export_items = tuple(
                    value for value in subtree if value.item_kind == WorkspaceItemKind.FILE
                )
                export_directories = tuple(
                    value
                    for value in subtree
                    if value.item_kind != WorkspaceItemKind.FILE
                    and value.id != directory_root_id
                )
            else:
                export_kind = WorkspaceExportKind.ZIP
                expanded = []
                seen: set[str] = set()
                for value in selected:
                    if value.item_kind == WorkspaceItemKind.CONTAINER_VIEW:
                        raise ApplicationError(
                            "EXPORT_ITEM_DENIED",
                            "select an ordinary folder or terminal files for export",
                        )
                    candidates = (
                        (value,)
                        if value.item_kind == WorkspaceItemKind.FILE
                        else self._active_subtree(
                            value.id, by_id, placements, uow.workspace
                        )
                    )
                    for candidate in candidates:
                        if candidate.id not in seen:
                            seen.add(candidate.id)
                            expanded.append(candidate)
                export_items = tuple(
                    value for value in expanded if value.item_kind == WorkspaceItemKind.FILE
                )
                export_directories = tuple(
                    value for value in expanded if value.item_kind != WorkspaceItemKind.FILE
                )
            if any(value.origin_source_node_id is None for value in export_items):
                raise ApplicationError(
                    "EXPORT_ITEM_DENIED",
                    "every exported file must be source-backed",
                )
            if export_kind == WorkspaceExportKind.DIRECTORY:
                relative_paths = {
                    item.id: self._relative_from_root(
                        item.id, directory_root_id, by_id, placements
                    )
                    for item in (*export_items, *export_directories)
                }
            else:
                relative_paths = {
                    item.id: self._relative_path(item.id, by_id, placements)
                    for item in (*export_items, *export_directories)
                }
            self._event(
                uow,
                EventType.WORKSPACE_EXPORT_REQUESTED,
                project_id,
                actor,
                operation_id,
                details={
                    "item_count": len(item_ids),
                    "export_kind": export_kind.value,
                    "destination": str(destination),
                },
            )
            uow.commit()

        folded: dict[str, str] = {}
        for item_id, value in relative_paths.items():
            key = value.casefold()
            if key in folded:
                failure = ApplicationError(
                    ErrorCode.EXPORT_PATH_COLLISION.value,
                    "selected Workspace files collide in the export package",
                    {"first": folded[key], "second": item_id, "path": value},
                )
                self._failed(database_path, project_id, actor, operation_id, failure)
                raise failure
            folded[key] = item_id

        if export_kind == WorkspaceExportKind.ZIP and destination.suffix.lower() != ".zip":
            failure = ApplicationError(
                ErrorCode.EXPORT_DESTINATION_INVALID.value,
                "multi-file exports require a .zip destination",
            )
            self._failed(database_path, project_id, actor, operation_id, failure)
            raise failure
        try:
            entries = []
            for item in export_items:
                with self._database.unit_of_work(database_path) as uow:
                    artifact = uow.workspace.working_artifact_for_item(item.id)
                if artifact is None:
                    materialized = self._structure.materialize(
                        MaterializeWorkspaceItemRequest(
                            project_id=project_id,
                            database_path=database_path,
                            workspace_item_id=item.id,
                            actor=actor,
                            policy=request.policy,
                        )
                    )
                    artifact = materialized.working_artifact
                    path = materialized.path
                else:
                    refreshed = self._working_files.refresh(
                        RefreshWorkingArtifactRequest(
                            project_id=project_id,
                            database_path=database_path,
                            workspace_item_id=item.id,
                            actor=actor,
                            reason=WorkingRefreshReason.EXPLICIT,
                        )
                    )
                    artifact = refreshed.working_artifact
                    path = refreshed.path
                if artifact.content_status in {
                    WorkingContentStatus.MISSING,
                    WorkingContentStatus.UNREADABLE,
                }:
                    raise ApplicationError(
                        ErrorCode.EXPORT_FAILED.value,
                        "a selected Working File is unavailable",
                        {"workspace_item_id": item.id},
                    )
                entries.append(
                    WorkspaceExportEntry(
                        workspace_item_id=item.id,
                        relative_path=relative_paths[item.id],
                        source_path=path,
                        size=artifact.current_size,
                        sha256=artifact.current_sha256,
                    )
                )
            stored = self._store.write(
                destination,
                operation_id,
                tuple(entries),
                tuple(
                    WorkspaceExportDirectory(relative_path=relative_paths[value.id])
                    for value in export_directories
                ),
                export_kind=export_kind,
                allow_replace=request.confirmed_replace,
                maximum_total_size=request.policy.max_total_expanded_size,
                chunk_size=request.policy.io_chunk_size,
            )
        except BaseException as exc:
            self._failed(database_path, project_id, actor, operation_id, exc)
            raise

        with self._database.unit_of_work(database_path) as uow:
            self._event(
                uow,
                EventType.WORKSPACE_EXPORT_COMPLETED,
                project_id,
                actor,
                operation_id,
                details={
                    "destination": str(stored.path),
                    "export_kind": export_kind.value,
                    "entry_count": stored.entry_count,
                    "size": stored.size,
                    "sha256": stored.sha256,
                },
            )
            uow.commit()
        return ExportWorkspaceItemsResult(
            project_id=project_id,
            workspace_item_ids=item_ids,
            destination_path=stored.path,
            export_kind=export_kind,
            entry_count=stored.entry_count,
            size=stored.size,
            sha256=stored.sha256,
        )

    @staticmethod
    def _active_subtree(root_id, by_id, placements, repository):
        children: dict[str | None, list] = {}
        for item_id, placement in placements.items():
            if placement is not None:
                children.setdefault(placement.parent_workspace_item_id, []).append(item_id)
        result = []
        queue = [root_id]
        while queue:
            current = queue.pop(0)
            item = by_id.get(current)
            if item is None or not repository.is_effectively_active(current):
                continue
            result.append(item)
            queue.extend(children.get(current, ()))
        return tuple(result)

    @staticmethod
    def _relative_path(item_id, by_id, placements) -> str:
        parts: list[str] = []
        current = item_id
        visited: set[str] = set()
        while current is not None:
            if current in visited:
                raise InvariantViolationError("workspace placement contains a cycle")
            visited.add(current)
            item = by_id.get(current)
            placement = placements.get(current)
            if item is None or placement is None:
                raise InvariantViolationError("workspace placement parent is missing")
            parts.append(safe_filesystem_segment(item.display_name))
            current = placement.parent_workspace_item_id
        return str(PurePosixPath(*reversed(parts)))

    @staticmethod
    def _relative_from_root(item_id, root_id, by_id, placements) -> str:
        parts: list[str] = []
        current = item_id
        visited: set[str] = set()
        while current != root_id:
            if current is None or current in visited:
                raise InvariantViolationError("item is outside the selected export folder")
            visited.add(current)
            item = by_id.get(current)
            placement = placements.get(current)
            if item is None or placement is None:
                raise InvariantViolationError("workspace placement parent is missing")
            parts.append(safe_filesystem_segment(item.display_name))
            current = placement.parent_workspace_item_id
        if not parts:
            raise InvariantViolationError("folder export root is not a content entry")
        return str(PurePosixPath(*reversed(parts)))

    def _failed(self, database_path, project_id, actor, operation_id, failure) -> None:
        try:
            code = (
                ErrorCode(failure.code)
                if isinstance(failure, ApplicationError)
                and failure.code in ErrorCode._value2member_map_
                else ErrorCode.EXPORT_FAILED
            )
            with self._database.unit_of_work(database_path) as uow:
                self._event(
                    uow,
                    EventType.WORKSPACE_EXPORT_FAILED,
                    project_id,
                    actor,
                    operation_id,
                    severity=EventSeverity.ERROR,
                    error_code=code,
                    details={
                        "failure_code": getattr(
                            failure, "code", type(failure).__name__
                        )
                    },
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
        severity=EventSeverity.INFO,
        error_code=None,
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
                correlation_id=correlation_id,
                error_code=error_code,
                details={} if details is None else details,
            )
        )

    @staticmethod
    def _project(project, database_path: Path) -> None:
        if project.model_version != WORKBENCH_MODEL_VERSION:
            raise ApplicationError(
                "UNSUPPORTED_PROJECT_MODEL_VERSION", "unsupported Project data model"
            )
        if database_path.parent.as_uri() != project.workspace_locator:
            raise ApplicationError(
                "PROJECT_DATABASE_MISMATCH", "database path is outside the Project workspace"
            )
