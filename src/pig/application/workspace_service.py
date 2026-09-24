from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

from pig.application.contracts import (
    CreateWorkspaceFolderRequest,
    MoveWorkspaceItemRequest,
    RestoreWorkspaceItemRequest,
    SoftDeleteWorkspaceItemRequest,
    WorkspaceMutationResult,
)
from pig.application.errors import ApplicationError
from pig.application.ports import ProjectDatabaseProvider
from pig.domain.entities import ProcessingEvent, WorkspaceItem
from pig.domain.enums import (
    EventSeverity,
    EventType,
    ProjectStatus,
    WorkspaceItemKind,
    WorkspaceItemLifecycleStatus,
    WorkspaceMaterializationStatus,
)
from pig.domain.exceptions import (
    ConcurrentStateError,
    EntityNotFoundError,
    InvariantViolationError,
)
from pig.domain.model_version import WORKBENCH_MODEL_VERSION


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


_EDITABLE_PROJECT_STATUSES = {
    ProjectStatus.CREATED,
    ProjectStatus.READY,
    ProjectStatus.READY_WITH_WARNINGS,
    ProjectStatus.FAILED,
}


class WorkspaceActionService:
    """W5 typed actions for the mutable logical Workspace Tree."""

    def __init__(
        self,
        *,
        database: ProjectDatabaseProvider,
        clock: Clock = _utc_now,
        id_generator: IdGenerator = _new_id,
    ) -> None:
        self._database = database
        self._clock = clock
        self._new_id = id_generator

    def create_folder(
        self, request: CreateWorkspaceFolderRequest
    ) -> WorkspaceMutationResult:
        project_id, actor, database_path = self._request_identity(
            request.project_id, request.actor, request.database_path
        )
        display_name = self._logical_segment(request.display_name)
        now = self._clock()
        correlation_id = self._new_id()
        with self._database.unit_of_work(database_path) as uow:
            project = self._editable_project(
                uow, project_id, database_path, request.expected_workspace_revision
            )
            siblings = uow.workspace.children_for_parent(
                project_id, request.parent_workspace_item_id
            )
            ordinal = len(siblings) if request.ordinal is None else request.ordinal
            item = WorkspaceItem(
                id=self._new_id(),
                project_id=project_id,
                item_kind=WorkspaceItemKind.FOLDER,
                display_name=display_name,
                lifecycle_status=WorkspaceItemLifecycleStatus.ACTIVE,
                materialization_status=WorkspaceMaterializationStatus.VIRTUAL,
                created_at=now,
                updated_at=now,
            )
            try:
                placement = uow.workspace.insert_item(
                    item,
                    parent_id=request.parent_workspace_item_id,
                    ordinal=ordinal,
                    updated_at=now,
                )
                updated_project = uow.projects.advance_workspace_revision(
                    project_id, project.workspace_revision, updated_at=now
                )
            except (EntityNotFoundError, InvariantViolationError) as exc:
                raise ApplicationError(
                    "INVALID_WORKSPACE_ACTION", str(exc)
                ) from exc
            except ConcurrentStateError as exc:
                raise self._revision_conflict(exc) from exc
            self._event(
                uow,
                EventType.WORKSPACE_ITEM_ADDED,
                project_id,
                actor,
                correlation_id,
                item.id,
                details={
                    "origin": "USER_CREATED_FOLDER",
                    "parent_workspace_item_id": placement.parent_workspace_item_id,
                    "ordinal": placement.ordinal,
                    "workspace_revision": updated_project.workspace_revision,
                },
            )
            uow.commit()
            return WorkspaceMutationResult(
                project_id=project_id,
                workspace_revision=updated_project.workspace_revision,
                item=item,
                placement=placement,
            )

    def move(self, request: MoveWorkspaceItemRequest) -> WorkspaceMutationResult:
        project_id, actor, database_path = self._request_identity(
            request.project_id, request.actor, request.database_path
        )
        item_id = self._required(request.workspace_item_id, "workspace_item_id")
        now = self._clock()
        correlation_id = self._new_id()
        with self._database.unit_of_work(database_path) as uow:
            project = self._editable_project(
                uow, project_id, database_path, request.expected_workspace_revision
            )
            item = uow.workspace.get_item(item_id)
            old = uow.workspace.get_placement(item_id)
            if item is None or old is None or item.project_id != project_id:
                raise ApplicationError(
                    "WORKSPACE_ITEM_NOT_FOUND", "Workspace Item was not found"
                )
            try:
                placement = uow.workspace.move_item(
                    item_id,
                    new_parent_id=request.new_parent_workspace_item_id,
                    new_ordinal=request.new_ordinal,
                    updated_at=now,
                )
                updated_project = uow.projects.advance_workspace_revision(
                    project_id, project.workspace_revision, updated_at=now
                )
            except (EntityNotFoundError, InvariantViolationError) as exc:
                raise ApplicationError(
                    "INVALID_WORKSPACE_ACTION", str(exc)
                ) from exc
            except ConcurrentStateError as exc:
                raise self._revision_conflict(exc) from exc
            current = uow.workspace.get_item(item_id)
            if current is None:  # pragma: no cover - guarded above
                raise ApplicationError("WORKSPACE_ITEM_NOT_FOUND", "Workspace Item vanished")
            self._event(
                uow,
                EventType.WORKSPACE_ITEM_MOVED,
                project_id,
                actor,
                correlation_id,
                item_id,
                details={
                    "old_parent_workspace_item_id": old.parent_workspace_item_id,
                    "old_ordinal": old.ordinal,
                    "new_parent_workspace_item_id": placement.parent_workspace_item_id,
                    "new_ordinal": placement.ordinal,
                    "workspace_revision": updated_project.workspace_revision,
                },
            )
            uow.commit()
            return WorkspaceMutationResult(
                project_id=project_id,
                workspace_revision=updated_project.workspace_revision,
                item=current,
                placement=placement,
            )

    def soft_delete(
        self, request: SoftDeleteWorkspaceItemRequest
    ) -> WorkspaceMutationResult:
        if not request.confirmed:
            raise ApplicationError(
                "DELETE_CONFIRMATION_REQUIRED",
                "soft delete requires explicit confirmation",
            )
        project_id, actor, database_path = self._request_identity(
            request.project_id, request.actor, request.database_path
        )
        item_id = self._required(request.workspace_item_id, "workspace_item_id")
        now = self._clock()
        correlation_id = self._new_id()
        with self._database.unit_of_work(database_path) as uow:
            project = self._editable_project(
                uow, project_id, database_path, request.expected_workspace_revision
            )
            try:
                item, placement = uow.workspace.soft_delete_item(
                    item_id, updated_at=now
                )
                if item.project_id != project_id:
                    raise InvariantViolationError(
                        "workspace item cannot be deleted across projects"
                    )
                updated_project = uow.projects.advance_workspace_revision(
                    project_id, project.workspace_revision, updated_at=now
                )
            except EntityNotFoundError as exc:
                raise ApplicationError(
                    "WORKSPACE_ITEM_NOT_FOUND", str(exc)
                ) from exc
            except InvariantViolationError as exc:
                raise ApplicationError(
                    "INVALID_WORKSPACE_ACTION", str(exc)
                ) from exc
            except ConcurrentStateError as exc:
                raise self._revision_conflict(exc) from exc
            self._event(
                uow,
                EventType.WORKSPACE_ITEM_DELETED,
                project_id,
                actor,
                correlation_id,
                item_id,
                previous_status=WorkspaceItemLifecycleStatus.ACTIVE.value,
                new_status=WorkspaceItemLifecycleStatus.DELETED.value,
                details={
                    "restore_parent_workspace_item_id": placement.previous_parent_id,
                    "restore_ordinal": placement.previous_ordinal,
                    "descendants_effectively_hidden": True,
                    "workspace_revision": updated_project.workspace_revision,
                },
            )
            uow.commit()
            return WorkspaceMutationResult(
                project_id=project_id,
                workspace_revision=updated_project.workspace_revision,
                item=item,
                placement=placement,
            )

    def restore(self, request: RestoreWorkspaceItemRequest) -> WorkspaceMutationResult:
        project_id, actor, database_path = self._request_identity(
            request.project_id, request.actor, request.database_path
        )
        item_id = self._required(request.workspace_item_id, "workspace_item_id")
        now = self._clock()
        correlation_id = self._new_id()
        with self._database.unit_of_work(database_path) as uow:
            project = self._editable_project(
                uow, project_id, database_path, request.expected_workspace_revision
            )
            try:
                item, placement, fallback = uow.workspace.restore_item(
                    item_id, updated_at=now
                )
                if item.project_id != project_id:
                    raise InvariantViolationError(
                        "workspace item cannot be restored across projects"
                    )
                updated_project = uow.projects.advance_workspace_revision(
                    project_id, project.workspace_revision, updated_at=now
                )
            except EntityNotFoundError as exc:
                raise ApplicationError(
                    "WORKSPACE_ITEM_NOT_FOUND", str(exc)
                ) from exc
            except InvariantViolationError as exc:
                raise ApplicationError(
                    "INVALID_WORKSPACE_ACTION", str(exc)
                ) from exc
            except ConcurrentStateError as exc:
                raise self._revision_conflict(exc) from exc
            self._event(
                uow,
                EventType.WORKSPACE_ITEM_RESTORED,
                project_id,
                actor,
                correlation_id,
                item_id,
                previous_status=WorkspaceItemLifecycleStatus.DELETED.value,
                new_status=WorkspaceItemLifecycleStatus.ACTIVE.value,
                details={
                    "parent_workspace_item_id": placement.parent_workspace_item_id,
                    "ordinal": placement.ordinal,
                    "restore_fallback": fallback,
                    "workspace_revision": updated_project.workspace_revision,
                },
            )
            uow.commit()
            return WorkspaceMutationResult(
                project_id=project_id,
                workspace_revision=updated_project.workspace_revision,
                item=item,
                placement=placement,
                restore_fallback=fallback,
            )

    def _editable_project(
        self, uow, project_id: str, database_path: Path, expected_revision: int
    ):
        if expected_revision < 0:
            raise ApplicationError(
                "INVALID_REQUEST", "expected_workspace_revision must be nonnegative"
            )
        project = uow.projects.get(project_id)
        if project is None:
            raise ApplicationError("PROJECT_NOT_FOUND", "Project was not found")
        if project.model_version != WORKBENCH_MODEL_VERSION:
            raise ApplicationError(
                "UNSUPPORTED_PROJECT_MODEL_VERSION", "unsupported Project data model"
            )
        if database_path.parent.as_uri() != project.workspace_locator:
            raise ApplicationError(
                "PROJECT_DATABASE_MISMATCH", "database path is outside the Project workspace"
            )
        if project.status not in _EDITABLE_PROJECT_STATUSES:
            raise ApplicationError(
                "PROJECT_NOT_WORKSPACE_EDITABLE",
                "Project is busy and does not accept Workspace changes",
                {"status": project.status.value},
            )
        if project.workspace_revision != expected_revision:
            raise ApplicationError(
                "WORKSPACE_REVISION_CONFLICT",
                "Workspace changed after the caller last loaded it",
                {"expected": expected_revision, "actual": project.workspace_revision},
            )
        return project

    @staticmethod
    def _logical_segment(value: str) -> str:
        name = value.strip()
        if not name or len(name) > 255:
            raise ApplicationError(
                "INVALID_WORKSPACE_NAME",
                "Workspace folder name must contain 1 to 255 characters",
            )
        if name in {".", ".."} or "/" in name or "\\" in name:
            raise ApplicationError(
                "INVALID_WORKSPACE_NAME",
                "Workspace folder name must be one logical path segment",
            )
        if any(ord(character) < 32 or ord(character) == 127 for character in name):
            raise ApplicationError(
                "INVALID_WORKSPACE_NAME",
                "Workspace folder name contains a control character",
            )
        return name

    @staticmethod
    def _required(value: str, field: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ApplicationError("INVALID_REQUEST", f"{field} must not be empty")
        return normalized

    def _request_identity(
        self, project_id: str, actor: str, database_path: Path
    ) -> tuple[str, str, Path]:
        project = self._required(project_id, "project_id")
        normalized_actor = self._required(actor, "actor")
        path = database_path.expanduser().resolve(strict=False)
        if not path.is_absolute():  # pragma: no cover - resolve produces absolute paths
            raise ApplicationError("INVALID_REQUEST", "database_path must be absolute")
        return project, normalized_actor, path

    @staticmethod
    def _revision_conflict(exc: ConcurrentStateError) -> ApplicationError:
        return ApplicationError("WORKSPACE_REVISION_CONFLICT", str(exc))

    def _event(
        self,
        uow,
        event_type: EventType,
        project_id: str,
        actor: str,
        correlation_id: str,
        workspace_item_id: str,
        *,
        previous_status: Optional[str] = None,
        new_status: Optional[str] = None,
        details: Optional[dict[str, object]] = None,
    ) -> None:
        uow.processing.append_event(
            ProcessingEvent(
                id=self._new_id(),
                event_type=event_type,
                project_id=project_id,
                workspace_item_id=workspace_item_id,
                actor=actor,
                occurred_at=self._clock(),
                severity=EventSeverity.INFO,
                correlation_id=correlation_id,
                previous_status=previous_status,
                new_status=new_status,
                details={} if details is None else details,
            )
        )
