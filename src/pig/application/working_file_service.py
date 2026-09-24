from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable
from uuid import uuid4

from pig.application.contracts import (
    MaterializeWorkspaceItemRequest,
    OpenWorkspaceItemRequest,
    OpenWorkspaceItemResult,
    RefreshWorkingArtifactRequest,
    RefreshWorkingArtifactResult,
    RollbackWorkingArtifactRequest,
    RollbackWorkingArtifactResult,
    RestoreWorkingArtifactRequest,
    RestoreWorkingArtifactResult,
)
from pig.application.errors import ApplicationError
from pig.application.ports import (
    FileOpener,
    ProjectDatabaseProvider,
    WorkingArtifactStore,
    WorkingVersionStore,
)
from pig.domain.entities import ProcessingEvent, WorkingArtifact, WorkingRevision
from pig.domain.enums import (
    ErrorCode,
    EventSeverity,
    EventType,
    NodeFormat,
    NodeKind,
    NodeProcessingStatus,
    WorkingContentStatus,
    WorkingRefreshReason,
    WorkingRevisionRole,
    WorkspaceItemKind,
)
from pig.domain.exceptions import EntityNotFoundError
from pig.domain.model_version import WORKBENCH_MODEL_VERSION
from pig.domain.open_policy import OpenPolicy
from pig.infrastructure.filesystem.staging_manifest import finalize_staging_manifest


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


class WorkingFileService:
    """Refresh, open, and explicitly restore mutable Working Artifacts."""

    def __init__(
        self,
        *,
        database: ProjectDatabaseProvider,
        working_store: WorkingArtifactStore,
        version_store: WorkingVersionStore,
        structure_service,
        opener: FileOpener,
        policy: OpenPolicy = OpenPolicy(),
        clock: Clock = _utc_now,
        id_generator: IdGenerator = _new_id,
    ) -> None:
        self._database = database
        self._working_store = working_store
        self._version_store = version_store
        self._structure = structure_service
        self._opener = opener
        self._policy = policy
        self._clock = clock
        self._new_id = id_generator

    def refresh(
        self, request: RefreshWorkingArtifactRequest
    ) -> RefreshWorkingArtifactResult:
        project_id, actor, database_path = self._validated_request(
            request.project_id, request.actor, request.database_path
        )
        if not isinstance(request.reason, WorkingRefreshReason):
            raise ApplicationError("INVALID_REQUEST", "reason contains an invalid value")
        project_path = database_path.resolve(strict=False).parent
        with self._database.unit_of_work(database_path) as uow:
            self._project(uow, project_id, database_path)
            item, _node, _format = self._active_file(uow, project_id, request.workspace_item_id)
            artifact = uow.workspace.working_artifact_for_item(item.id)
            if artifact is None:
                raise ApplicationError(
                    "WORKING_ARTIFACT_NOT_FOUND",
                    "the workspace file has not been materialized",
                )
            current_checkpoint = uow.workspace.working_revision_for_artifact(
                artifact.id, WorkingRevisionRole.CURRENT_CHECKPOINT
            )
            existing_previous = uow.workspace.working_revision_for_artifact(
                artifact.id, WorkingRevisionRole.PREVIOUS
            )
            if current_checkpoint is None:
                raise ApplicationError(
                    ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                    "the current Working version checkpoint is missing",
                )

        observation = self._working_store.observe(
            project_path,
            artifact.storage_key,
            baseline_size=artifact.baseline_size,
            baseline_sha256=artifact.baseline_sha256,
            maximum=self._policy.maximum_working_file_size,
            chunk_size=self._policy.verification_chunk_size,
            stability_retries=self._policy.stability_retries,
        )
        checked_at = self._clock()
        changed = self._observation_changed(artifact, observation)
        content_changed = (
            observation.size is not None
            and observation.sha256 is not None
            and (
                artifact.current_size != observation.size
                or artifact.current_sha256 != observation.sha256
            )
        )
        rotation = None
        version_operation_id = None
        if content_changed:
            version_operation_id = self._new_id()
            rotation = self._version_store.capture(
                project_path,
                version_operation_id,
                artifact.id,
                artifact.storage_key,
                current_checkpoint.storage_key,
                project_id=project_id,
                expected_old_size=artifact.current_size,
                expected_old_sha256=artifact.current_sha256,
                expected_new_size=observation.size,
                expected_new_sha256=observation.sha256,
                maximum=self._policy.maximum_working_file_size,
                chunk_size=self._policy.verification_chunk_size,
                stability_retries=self._policy.stability_retries,
            )
        with self._database.unit_of_work(database_path) as uow:
            current = uow.workspace.working_artifact_for_item(request.workspace_item_id)
            if current is None:
                raise ApplicationError(
                    "WORKING_ARTIFACT_NOT_FOUND", "Working Artifact disappeared"
                )
            updated = uow.workspace.update_working_content(
                current.id,
                artifact.content_status,
                observation.status,
                expected_updated_at=artifact.updated_at,
                current_size=observation.size,
                current_sha256=observation.sha256,
                last_checked_at=checked_at,
                updated_at=checked_at,
            )
            if rotation is not None and rotation.previous is not None:
                previous = WorkingRevision(
                    id=(
                        self._new_id()
                        if existing_previous is None
                        else existing_previous.id
                    ),
                    project_id=project_id,
                    working_artifact_id=artifact.id,
                    role=WorkingRevisionRole.PREVIOUS,
                    storage_key=rotation.previous.storage_key,
                    size=rotation.previous.size,
                    sha256=rotation.previous.sha256,
                    file_modified_at=current_checkpoint.file_modified_at,
                    detected_at=current_checkpoint.detected_at,
                    created_at=(
                        checked_at
                        if existing_previous is None
                        else existing_previous.created_at
                    ),
                    updated_at=checked_at,
                )
                uow.workspace.set_working_revision(previous)
                uow.workspace.set_working_revision(
                    WorkingRevision(
                        id=current_checkpoint.id,
                        project_id=project_id,
                        working_artifact_id=artifact.id,
                        role=WorkingRevisionRole.CURRENT_CHECKPOINT,
                        storage_key=rotation.current.storage_key,
                        size=rotation.current.size,
                        sha256=rotation.current.sha256,
                        file_modified_at=rotation.current.file_modified_at,
                        detected_at=checked_at,
                        created_at=current_checkpoint.created_at,
                        updated_at=checked_at,
                    )
                )
                self._append_event(
                    uow,
                    EventType.WORKING_VERSION_CAPTURED,
                    project_id,
                    actor,
                    self._new_id(),
                    workspace_item_id=request.workspace_item_id,
                    working_artifact_id=artifact.id,
                    details={
                        "reason": request.reason.value,
                        "current_sha256": rotation.current.sha256,
                        "previous_sha256": rotation.previous.sha256,
                    },
                )
            event_type = self._content_event(artifact.content_status, observation.status)
            if changed and event_type is not None:
                self._append_event(
                    uow,
                    event_type,
                    project_id,
                    actor,
                    self._new_id(),
                    workspace_item_id=request.workspace_item_id,
                    working_artifact_id=artifact.id,
                    previous_status=artifact.content_status.value,
                    new_status=observation.status.value,
                    severity=(
                        EventSeverity.WARNING
                        if observation.status
                        in {WorkingContentStatus.MISSING, WorkingContentStatus.UNREADABLE}
                        else EventSeverity.INFO
                    ),
                    error_code=observation.error_code,
                    details={
                        "reason": request.reason.value,
                        "previous_size": artifact.current_size,
                        "previous_sha256": artifact.current_sha256,
                        "observed_size": observation.size,
                        "observed_sha256": observation.sha256,
                        "message": observation.error_message,
                    },
                )
            uow.commit()
        if version_operation_id is not None:
            finalize_staging_manifest(
                project_path, f"{version_operation_id}-version"
            )
        return RefreshWorkingArtifactResult(
            project_id=project_id,
            workspace_item_id=request.workspace_item_id,
            working_artifact=updated,
            path=observation.path,
            reason=request.reason,
            changed=changed,
        )

    def open(self, request: OpenWorkspaceItemRequest) -> OpenWorkspaceItemResult:
        project_id, actor, database_path = self._validated_request(
            request.project_id, request.actor, request.database_path
        )
        correlation_id = self._new_id()
        with self._database.unit_of_work(database_path) as uow:
            self._project(uow, project_id, database_path)
            self._append_event(
                uow,
                EventType.FILE_OPEN_REQUESTED,
                project_id,
                actor,
                correlation_id,
                workspace_item_id=request.workspace_item_id,
            )
            uow.commit()

        try:
            with self._database.unit_of_work(database_path) as uow:
                item, _node, node_format = self._active_file(
                    uow, project_id, request.workspace_item_id
                )
                if node_format not in self._policy.allowed_formats:
                    raise ApplicationError(
                        ErrorCode.OPEN_FORMAT_DENIED.value,
                        "the file format is not allowed by OpenPolicy",
                        {"format": node_format.value},
                    )
                existing = uow.workspace.working_artifact_for_item(item.id)

            materialized = existing is None
            if materialized:
                materialization = self._structure.materialize(
                    MaterializeWorkspaceItemRequest(
                        project_id=project_id,
                        database_path=database_path,
                        workspace_item_id=request.workspace_item_id,
                        actor=actor,
                        policy=request.policy,
                    )
                )
                artifact = materialization.working_artifact
                path = materialization.path
            else:
                refreshed = self.refresh(
                    RefreshWorkingArtifactRequest(
                        project_id=project_id,
                        database_path=database_path,
                        workspace_item_id=request.workspace_item_id,
                        actor=actor,
                        reason=WorkingRefreshReason.BEFORE_OPEN,
                    )
                )
                artifact = refreshed.working_artifact
                path = refreshed.path
            if artifact.content_status in {
                WorkingContentStatus.MISSING,
                WorkingContentStatus.UNREADABLE,
            }:
                code = (
                    ErrorCode.ARTIFACT_MISSING
                    if artifact.content_status == WorkingContentStatus.MISSING
                    else ErrorCode.ARTIFACT_UNREADABLE
                )
                raise ApplicationError(
                    code.value,
                    "Working Artifact must be restored before it can be opened",
                )
        except BaseException as exc:
            self._record_open_outcome(
                database_path,
                project_id,
                actor,
                correlation_id,
                request.workspace_item_id,
                EventType.FILE_OPEN_DENIED,
                exc,
            )
            raise

        try:
            self._opener.open(path)
        except BaseException as exc:
            self._record_open_outcome(
                database_path,
                project_id,
                actor,
                correlation_id,
                request.workspace_item_id,
                EventType.FILE_OPEN_FAILED,
                exc,
                artifact.id,
            )
            raise ApplicationError(
                ErrorCode.OPEN_HANDOFF_FAILED.value,
                "host file association could not open the Working Artifact",
            ) from exc

        handed_off_at = self._clock()
        with self._database.unit_of_work(database_path) as uow:
            self._append_event(
                uow,
                EventType.FILE_OPENED,
                project_id,
                actor,
                correlation_id,
                workspace_item_id=request.workspace_item_id,
                working_artifact_id=artifact.id,
                new_status=artifact.content_status.value,
                details={
                    "format": node_format.value,
                    "storage_key": artifact.storage_key,
                    "materialized": materialized,
                    "meaning": "host_handoff_started",
                },
            )
            uow.commit()
        return OpenWorkspaceItemResult(
            project_id=project_id,
            workspace_item_id=request.workspace_item_id,
            working_artifact=artifact,
            format=node_format,
            path=path,
            materialized=materialized,
            handed_off_at=handed_off_at,
        )

    def restore(
        self, request: RestoreWorkingArtifactRequest
    ) -> RestoreWorkingArtifactResult:
        project_id, actor, database_path = self._validated_request(
            request.project_id, request.actor, request.database_path
        )
        refreshed = self.refresh(
            RefreshWorkingArtifactRequest(
                project_id=project_id,
                database_path=database_path,
                workspace_item_id=request.workspace_item_id,
                actor=actor,
                reason=WorkingRefreshReason.EXPLICIT,
            )
        )
        artifact = refreshed.working_artifact
        if artifact.content_status == WorkingContentStatus.CLEAN:
            raise ApplicationError(
                "WORKING_ARTIFACT_ALREADY_CLEAN",
                "Working Artifact already matches its immutable baseline",
            )
        replacing = refreshed.path.exists() or refreshed.path.is_symlink()
        if replacing and not request.confirmed_replace:
            raise ApplicationError(
                "RESTORE_CONFIRMATION_REQUIRED",
                "replacing an existing Working Artifact requires confirmation",
            )
        restore_operation_id = self._new_id()
        stored = self._structure.restore_content(
            project_id=project_id,
            database_path=database_path,
            workspace_item_id=request.workspace_item_id,
            operation_id=restore_operation_id,
            actor=actor,
            policy=request.policy,
            allow_replace=request.confirmed_replace,
        )
        now = self._clock()
        rotation = None
        version_operation_id = None
        current_checkpoint = None
        existing_previous = None
        if stored.size != artifact.current_size or stored.sha256 != artifact.current_sha256:
            with self._database.unit_of_work(database_path) as uow:
                current_checkpoint = uow.workspace.working_revision_for_artifact(
                    artifact.id, WorkingRevisionRole.CURRENT_CHECKPOINT
                )
                existing_previous = uow.workspace.working_revision_for_artifact(
                    artifact.id, WorkingRevisionRole.PREVIOUS
                )
                if current_checkpoint is None:
                    raise ApplicationError(
                        ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                        "the current Working version checkpoint is missing",
                    )
            version_operation_id = self._new_id()
            rotation = self._version_store.capture(
                database_path.parent,
                version_operation_id,
                artifact.id,
                artifact.storage_key,
                current_checkpoint.storage_key,
                project_id=project_id,
                expected_old_size=artifact.current_size,
                expected_old_sha256=artifact.current_sha256,
                expected_new_size=stored.size,
                expected_new_sha256=stored.sha256,
                maximum=self._policy.maximum_working_file_size,
                chunk_size=self._policy.verification_chunk_size,
                stability_retries=self._policy.stability_retries,
            )
        with self._database.unit_of_work(database_path) as uow:
            current = uow.workspace.working_artifact_for_item(request.workspace_item_id)
            if current is None:
                raise ApplicationError(
                    "WORKING_ARTIFACT_NOT_FOUND", "Working Artifact disappeared"
                )
            updated = uow.workspace.update_working_content(
                current.id,
                artifact.content_status,
                WorkingContentStatus.CLEAN,
                expected_updated_at=artifact.updated_at,
                current_size=stored.size,
                current_sha256=stored.sha256,
                last_checked_at=now,
                updated_at=now,
            )
            if rotation is not None and current_checkpoint is not None:
                uow.workspace.set_working_revision(
                    WorkingRevision(
                        id=(
                            self._new_id()
                            if existing_previous is None
                            else existing_previous.id
                        ),
                        project_id=project_id,
                        working_artifact_id=artifact.id,
                        role=WorkingRevisionRole.PREVIOUS,
                        storage_key=rotation.previous.storage_key,
                        size=rotation.previous.size,
                        sha256=rotation.previous.sha256,
                        file_modified_at=current_checkpoint.file_modified_at,
                        detected_at=current_checkpoint.detected_at,
                        created_at=(
                            now
                            if existing_previous is None
                            else existing_previous.created_at
                        ),
                        updated_at=now,
                    )
                )
                uow.workspace.set_working_revision(
                    WorkingRevision(
                        id=current_checkpoint.id,
                        project_id=project_id,
                        working_artifact_id=artifact.id,
                        role=WorkingRevisionRole.CURRENT_CHECKPOINT,
                        storage_key=rotation.current.storage_key,
                        size=rotation.current.size,
                        sha256=rotation.current.sha256,
                        file_modified_at=rotation.current.file_modified_at,
                        detected_at=now,
                        created_at=current_checkpoint.created_at,
                        updated_at=now,
                    )
                )
                self._append_event(
                    uow,
                    EventType.WORKING_VERSION_CAPTURED,
                    project_id,
                    actor,
                    self._new_id(),
                    workspace_item_id=request.workspace_item_id,
                    working_artifact_id=artifact.id,
                    details={
                        "reason": "ORIGINAL_RESTORE",
                        "current_sha256": rotation.current.sha256,
                        "previous_sha256": rotation.previous.sha256,
                    },
                )
            self._append_event(
                uow,
                EventType.WORKING_FILE_RESTORED_CLEAN,
                project_id,
                actor,
                self._new_id(),
                workspace_item_id=request.workspace_item_id,
                working_artifact_id=artifact.id,
                previous_status=artifact.content_status.value,
                new_status=WorkingContentStatus.CLEAN.value,
                details={
                    "storage_key": artifact.storage_key,
                    "replaced": replacing,
                    "size": stored.size,
                    "sha256": stored.sha256,
                },
            )
            uow.commit()
        finalize_staging_manifest(
            database_path.parent, f"{restore_operation_id}-working"
        )
        if version_operation_id is not None:
            finalize_staging_manifest(
                database_path.parent, f"{version_operation_id}-version"
            )
        return RestoreWorkingArtifactResult(
            project_id=project_id,
            workspace_item_id=request.workspace_item_id,
            working_artifact=updated,
            path=stored.path,
            replaced=replacing,
        )

    def rollback(
        self, request: RollbackWorkingArtifactRequest
    ) -> RollbackWorkingArtifactResult:
        project_id, actor, database_path = self._validated_request(
            request.project_id, request.actor, request.database_path
        )
        if not request.confirmed_replace:
            raise ApplicationError(
                "ROLLBACK_CONFIRMATION_REQUIRED",
                "rolling back the current Working File requires confirmation",
            )
        refreshed = self.refresh(
            RefreshWorkingArtifactRequest(
                project_id=project_id,
                database_path=database_path,
                workspace_item_id=request.workspace_item_id,
                actor=actor,
                reason=WorkingRefreshReason.EXPLICIT,
            )
        )
        artifact = refreshed.working_artifact
        if artifact.content_status in {
            WorkingContentStatus.MISSING,
            WorkingContentStatus.UNREADABLE,
        }:
            raise ApplicationError(
                ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                "the current Working File must be readable before rollback",
            )
        with self._database.unit_of_work(database_path) as uow:
            current = uow.workspace.working_revision_for_artifact(
                artifact.id, WorkingRevisionRole.CURRENT_CHECKPOINT
            )
            previous = uow.workspace.working_revision_for_artifact(
                artifact.id, WorkingRevisionRole.PREVIOUS
            )
            if current is None or previous is None:
                raise ApplicationError(
                    ErrorCode.WORKING_VERSION_NOT_FOUND.value,
                    "no previous Working version is available",
                )
        operation_id = self._new_id()
        pair = self._version_store.rollback(
            database_path.parent,
            operation_id,
            artifact.id,
            artifact.storage_key,
            current.storage_key,
            previous.storage_key,
            project_id=project_id,
            expected_current_size=current.size,
            expected_current_sha256=current.sha256,
            expected_previous_size=previous.size,
            expected_previous_sha256=previous.sha256,
            maximum=self._policy.maximum_working_file_size,
            chunk_size=self._policy.verification_chunk_size,
            stability_retries=self._policy.stability_retries,
        )
        now = self._clock()
        new_status = (
            WorkingContentStatus.CLEAN
            if pair.current.size == artifact.baseline_size
            and pair.current.sha256 == artifact.baseline_sha256
            else WorkingContentStatus.MODIFIED
        )
        with self._database.unit_of_work(database_path) as uow:
            updated = uow.workspace.update_working_content(
                artifact.id,
                artifact.content_status,
                new_status,
                expected_updated_at=artifact.updated_at,
                current_size=pair.current.size,
                current_sha256=pair.current.sha256,
                last_checked_at=now,
                updated_at=now,
            )
            uow.workspace.set_working_revision(
                WorkingRevision(
                    id=current.id,
                    project_id=project_id,
                    working_artifact_id=artifact.id,
                    role=WorkingRevisionRole.CURRENT_CHECKPOINT,
                    storage_key=pair.current.storage_key,
                    size=pair.current.size,
                    sha256=pair.current.sha256,
                    file_modified_at=previous.file_modified_at,
                    detected_at=now,
                    created_at=current.created_at,
                    updated_at=now,
                )
            )
            new_previous = uow.workspace.set_working_revision(
                WorkingRevision(
                    id=previous.id,
                    project_id=project_id,
                    working_artifact_id=artifact.id,
                    role=WorkingRevisionRole.PREVIOUS,
                    storage_key=pair.previous.storage_key,
                    size=pair.previous.size,
                    sha256=pair.previous.sha256,
                    file_modified_at=current.file_modified_at,
                    detected_at=current.detected_at,
                    created_at=previous.created_at,
                    updated_at=now,
                )
            )
            self._append_event(
                uow,
                EventType.WORKING_FILE_ROLLED_BACK,
                project_id,
                actor,
                operation_id,
                workspace_item_id=request.workspace_item_id,
                working_artifact_id=artifact.id,
                previous_status=artifact.content_status.value,
                new_status=new_status.value,
                details={
                    "restored_sha256": pair.current.sha256,
                    "preserved_sha256": pair.previous.sha256,
                },
            )
            uow.commit()
        finalize_staging_manifest(
            database_path.parent, f"{operation_id}-version"
        )
        return RollbackWorkingArtifactResult(
            project_id=project_id,
            workspace_item_id=request.workspace_item_id,
            working_artifact=updated,
            previous_revision=new_previous,
            path=database_path.parent.joinpath(*PurePosixPath(artifact.storage_key).parts),
        )

    def _active_file(self, uow, project_id: str, item_id: str):
        item = uow.workspace.get_item(item_id)
        if item is None or item.project_id != project_id:
            raise EntityNotFoundError(f"workspace item not found: {item_id}")
        if item.item_kind != WorkspaceItemKind.FILE or item.origin_source_node_id is None:
            raise ApplicationError("OPEN_ITEM_DENIED", "only source-backed files can be opened")
        if not uow.workspace.is_effectively_active(item.id):
            raise ApplicationError("OPEN_ITEM_DENIED", "deleted workspace items cannot be opened")
        node = uow.catalog.get_node(item.origin_source_node_id)
        if (
            node is None
            or node.kind != NodeKind.FILE
            or node.status != NodeProcessingStatus.SUCCESS
        ):
            raise ApplicationError(
                "OPEN_ITEM_DENIED", "workspace item is not backed by a usable terminal file"
            )
        return item, node, node.format

    @staticmethod
    def _observation_changed(artifact: WorkingArtifact, observation) -> bool:
        if artifact.content_status != observation.status:
            return True
        if observation.size is None or observation.sha256 is None:
            return False
        return (
            artifact.current_size != observation.size
            or artifact.current_sha256 != observation.sha256
        )

    @staticmethod
    def _content_event(previous: WorkingContentStatus, current: WorkingContentStatus):
        if current == WorkingContentStatus.MODIFIED:
            return EventType.WORKING_FILE_MODIFIED
        if current == WorkingContentStatus.MISSING:
            return EventType.WORKING_FILE_MISSING
        if current == WorkingContentStatus.UNREADABLE:
            return EventType.WORKING_FILE_UNREADABLE
        if current == WorkingContentStatus.CLEAN and previous != WorkingContentStatus.CLEAN:
            return EventType.WORKING_FILE_RESTORED_CLEAN
        return None

    def _record_open_outcome(
        self,
        database_path: Path,
        project_id: str,
        actor: str,
        correlation_id: str,
        workspace_item_id: str,
        event_type: EventType,
        failure: BaseException,
        working_artifact_id: str | None = None,
    ) -> None:
        code = self._error_code(failure)
        with self._database.unit_of_work(database_path) as uow:
            self._append_event(
                uow,
                event_type,
                project_id,
                actor,
                correlation_id,
                workspace_item_id=workspace_item_id,
                working_artifact_id=working_artifact_id,
                severity=EventSeverity.WARNING if event_type == EventType.FILE_OPEN_DENIED else EventSeverity.ERROR,
                error_code=code,
                details={"failure_code": getattr(failure, "code", type(failure).__name__)},
            )
            uow.commit()

    @staticmethod
    def _error_code(failure: BaseException) -> ErrorCode:
        if isinstance(failure, ApplicationError):
            try:
                return ErrorCode(failure.code)
            except ValueError:
                return ErrorCode.OPEN_INTEGRITY_REQUIRED
        return ErrorCode.OPEN_HANDOFF_FAILED

    def _append_event(
        self,
        uow,
        event_type: EventType,
        project_id: str,
        actor: str,
        correlation_id: str,
        *,
        severity: EventSeverity = EventSeverity.INFO,
        error_code: ErrorCode | None = None,
        details=None,
        **links,
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
                **links,
            )
        )

    @staticmethod
    def _validated_request(project_id: str, actor: str, database_path: Path):
        project = project_id.strip()
        effective_actor = actor.strip()
        path = Path(database_path)
        if not project or not effective_actor or not path.is_absolute():
            raise ApplicationError("INVALID_REQUEST", "project_id, actor, and absolute database_path are required")
        return project, effective_actor, path

    @staticmethod
    def _project(uow, project_id: str, database_path: Path):
        project = uow.projects.get(project_id)
        if project is None:
            raise EntityNotFoundError(f"project not found: {project_id}")
        if project.model_version != WORKBENCH_MODEL_VERSION:
            raise ApplicationError("UNSUPPORTED_PROJECT_MODEL_VERSION", "unsupported Project data model")
        if database_path.resolve(strict=False).parent.as_uri() != project.workspace_locator:
            raise ApplicationError("PROJECT_DATABASE_MISMATCH", "database path is outside the Project workspace")
        return project
