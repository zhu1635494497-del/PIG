from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

from pig.application.contracts import (
    ImportItemResult,
    ImportProjectItemsRequest,
    ImportProjectItemsResult,
    VerifyOriginalSnapshotRequest,
    VerifyOriginalSnapshotResult,
)
from pig.application.errors import ApplicationError
from pig.application.ports import OriginalSnapshotStore, ProjectDatabaseProvider
from pig.domain.entities import (
    ImportSession,
    ImportSessionItem,
    Node,
    OriginalArtifact,
    OriginalSnapshot,
    OriginalSnapshotEntry,
    ProcessingEvent,
    Source,
)
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    ErrorCode,
    EventSeverity,
    EventType,
    ImportItemStatus,
    ImportSessionStatus,
    NodeFormat,
    NodeKind,
    NodeProcessingStatus,
    OriginalSnapshotStatus,
    ProjectStatus,
    SourceKind,
    SourceStatus,
    WorkspaceItemKind,
)
from pig.domain.exceptions import EntityNotFoundError
from pig.domain.model_version import WORKBENCH_MODEL_VERSION
from pig.domain.paths import logical_segment


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


_LOGGER = logging.getLogger(__name__)


class SnapshotImportService:
    """W2 action: capture immutable inputs and register only their root Source Node."""

    def __init__(
        self,
        *,
        database: ProjectDatabaseProvider,
        store: OriginalSnapshotStore,
        clock: Clock = _utc_now,
        id_generator: IdGenerator = _new_id,
    ) -> None:
        self._database = database
        self._store = store
        self._clock = clock
        self._new_id = id_generator

    def import_items(
        self, request: ImportProjectItemsRequest
    ) -> ImportProjectItemsResult:
        project_id = self._required(request.project_id, "project_id")
        actor = self._required(request.actor, "actor")
        database_path = self._absolute(request.database_path, "database_path")
        input_paths = tuple(self._absolute(path, "input_paths") for path in request.input_paths)
        if not input_paths:
            raise ApplicationError("INVALID_REQUEST", "input_paths must not be empty")
        if len(input_paths) > request.policy.max_input_count:
            raise ApplicationError(
                ErrorCode.MAX_IMPORT_ENTRY_COUNT_EXCEEDED.value,
                "input count exceeds the configured limit",
                {"maximum": request.policy.max_input_count},
            )
        canonical = [str(path.resolve(strict=False)).casefold() for path in input_paths]
        if len(canonical) != len(set(canonical)):
            raise ApplicationError(
                ErrorCode.DUPLICATE_INPUT.value,
                "the same top-level input was requested more than once",
            )

        project_path = database_path.resolve(strict=False).parent
        correlation_id = self._required(
            request.idempotency_key or self._new_id(), "idempotency_key", maximum=36
        )
        with self._database.unit_of_work(database_path) as uow:
            project = self._project(uow, project_id, database_path)
            existing = uow.imports.get_session_by_correlation(
                project_id, correlation_id
            )
            if existing is not None:
                persisted_items = uow.imports.items_for_session(existing.id)
                if (
                    tuple(item.input_locator for item in persisted_items)
                    != tuple(str(path) for path in input_paths)
                    or dict(existing.policy_snapshot) != request.policy.snapshot()
                    or existing.actor != actor
                    or existing.target_workspace_parent_id
                    != request.target_workspace_parent_id
                    or existing.expected_workspace_revision
                    != request.expected_workspace_revision
                ):
                    raise ApplicationError(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency_key was already used for a different import request",
                    )
                return self._existing_result(uow, existing)
            if request.expected_workspace_revision is not None:
                if request.expected_workspace_revision < 0:
                    raise ApplicationError(
                        "INVALID_REQUEST",
                        "expected_workspace_revision must be nonnegative",
                    )
                if project.workspace_revision != request.expected_workspace_revision:
                    raise ApplicationError(
                        "WORKSPACE_REVISION_CONFLICT",
                        "Workspace changed after the caller last loaded it",
                        {
                            "expected": request.expected_workspace_revision,
                            "actual": project.workspace_revision,
                        },
                    )
            if request.target_workspace_parent_id is not None:
                if request.expected_workspace_revision is None:
                    raise ApplicationError(
                        "INVALID_REQUEST",
                        "a targeted Workspace add requires expected_workspace_revision",
                    )
                target = uow.workspace.get_item(request.target_workspace_parent_id)
                if (
                    target is None
                    or target.project_id != project_id
                    or target.item_kind != WorkspaceItemKind.FOLDER
                    or not uow.workspace.is_effectively_active(target.id)
                ):
                    raise ApplicationError(
                        "INVALID_WORKSPACE_TARGET",
                        "target_workspace_parent_id must identify an active ordinary folder",
                    )
            if project.status not in {
                ProjectStatus.CREATED,
                ProjectStatus.READY,
                ProjectStatus.READY_WITH_WARNINGS,
                ProjectStatus.FAILED,
            }:
                raise ApplicationError(
                    "PROJECT_NOT_IMPORTABLE",
                    "Project is not in a state that accepts a new import",
                    {"status": project.status.value},
                )
            now = self._clock()
            session_id = self._new_id()
            session = ImportSession(
                id=session_id,
                project_id=project_id,
                status=ImportSessionStatus.QUEUED,
                requested_item_count=len(input_paths),
                accepted_item_count=0,
                failed_item_count=0,
                requested_at=now,
                actor=actor,
                correlation_id=correlation_id,
                policy_snapshot=request.policy.snapshot(),
                target_workspace_parent_id=request.target_workspace_parent_id,
                expected_workspace_revision=request.expected_workspace_revision,
            )
            uow.imports.add_session(session)
            for ordinal, path in enumerate(input_paths):
                uow.imports.add_session_item(
                    ImportSessionItem(
                        id=self._new_id(),
                        project_id=project_id,
                        import_session_id=session_id,
                        ordinal=ordinal,
                        input_locator=str(path),
                        status=ImportItemStatus.PENDING,
                        created_at=now,
                        updated_at=now,
                    )
                )
            uow.projects.update_status(project_id, project.status, ProjectStatus.IMPORTING, now)
            self._event(
                uow,
                EventType.IMPORT_REQUESTED,
                project_id,
                actor,
                correlation_id,
                import_session_id=session_id,
                new_status=ImportSessionStatus.QUEUED.value,
                details={
                    "requested_item_count": len(input_paths),
                    "target_workspace_parent_id": request.target_workspace_parent_id,
                    "expected_workspace_revision": request.expected_workspace_revision,
                },
            )
            uow.commit()

        with self._database.unit_of_work(database_path) as uow:
            uow.imports.update_session_status(
                session_id,
                ImportSessionStatus.QUEUED,
                ImportSessionStatus.SNAPSHOTTING,
                started_at=self._clock(),
            )
            self._event(
                uow,
                EventType.IMPORT_STARTED,
                project_id,
                actor,
                correlation_id,
                import_session_id=session_id,
                previous_status=ImportSessionStatus.QUEUED.value,
                new_status=ImportSessionStatus.SNAPSHOTTING.value,
            )
            uow.commit()

        accepted = 0
        failed = 0
        session_size = 0
        results: list[ImportItemResult] = []
        for ordinal, path in enumerate(input_paths):
            with self._database.unit_of_work(database_path) as uow:
                item = uow.imports.items_for_session(session_id)[ordinal]
            try:
                source_input = self._store.preflight(project_path, path)
            except ApplicationError as exc:
                failed += 1
                self._fail_item(
                    database_path, item, actor, correlation_id, exc
                )
                results.append(
                    ImportItemResult(
                        input_path=path,
                        snapshot_id=None,
                        captured=False,
                        error_code=exc.code,
                        error_message=exc.message,
                    )
                )
                continue
            except Exception:
                _LOGGER.exception("unexpected snapshot preflight failure")
                failed += 1
                failure = ApplicationError(
                    ErrorCode.INTERNAL_ERROR.value,
                    "snapshot capture failed unexpectedly",
                    {"technical_reference": self._new_id()},
                )
                self._fail_item(
                    database_path, item, actor, correlation_id, failure
                )
                results.append(
                    ImportItemResult(
                        input_path=path,
                        snapshot_id=None,
                        captured=False,
                        error_code=failure.code,
                        error_message=failure.message,
                    )
                )
                continue

            snapshot_id = self._new_id()
            created_at = self._clock()
            with self._database.unit_of_work(database_path) as uow:
                uow.imports.add_snapshot(
                    OriginalSnapshot(
                        id=snapshot_id,
                        project_id=project_id,
                        import_session_id=session_id,
                        input_kind=source_input.kind,
                        original_display_name=source_input.display_name,
                        external_locator_at_import=source_input.locator,
                        status=OriginalSnapshotStatus.COPYING,
                        created_at=created_at,
                    )
                )
                uow.imports.update_session_item(
                    item.id,
                    ImportItemStatus.PENDING,
                    ImportItemStatus.CAPTURING,
                    updated_at=created_at,
                    snapshot_id=snapshot_id,
                )
                self._event(
                    uow,
                    EventType.SNAPSHOT_COPY_STARTED,
                    project_id,
                    actor,
                    correlation_id,
                    import_session_id=session_id,
                    snapshot_id=snapshot_id,
                    new_status=OriginalSnapshotStatus.COPYING.value,
                    details={"input_ordinal": ordinal},
                )
                uow.commit()

            try:
                set_project_context = getattr(
                    self._store, "set_project_context", None
                )
                if set_project_context is not None:
                    set_project_context(project_id)
                write_context = self._store.begin(
                    project_path, session_id, snapshot_id
                )
                with write_context as write:
                    captured = write.capture(
                        source_input,
                        policy=request.policy,
                        prior_session_size=session_size,
                    )
                    write.publish()
                    source_id, node_id = self._persist_capture(
                        database_path=database_path,
                        project_id=project_id,
                        session_id=session_id,
                        item_id=item.id,
                        snapshot_id=snapshot_id,
                        source_input=source_input,
                        captured=captured,
                        actor=actor,
                        correlation_id=correlation_id,
                    )
                    write.complete()
                accepted += 1
                session_size += captured.total_size
                results.append(
                    ImportItemResult(
                        input_path=path,
                        snapshot_id=snapshot_id,
                        captured=True,
                        source_id=source_id,
                        root_node_id=node_id,
                    )
                )
            except (KeyboardInterrupt, SystemExit):
                self._interrupt(
                    database_path, project_id, session_id, item.id, snapshot_id,
                    actor, correlation_id,
                )
                raise
            except ApplicationError as exc:
                failed += 1
                self._fail_snapshot(
                    database_path, item.id, snapshot_id, project_id,
                    actor, correlation_id, exc,
                )
                results.append(
                    ImportItemResult(
                        input_path=path,
                        snapshot_id=snapshot_id,
                        captured=False,
                        error_code=exc.code,
                        error_message=exc.message,
                    )
                )
            except Exception:
                _LOGGER.exception("unexpected snapshot capture failure")
                failed += 1
                failure = ApplicationError(
                    ErrorCode.INTERNAL_ERROR.value,
                    "snapshot capture failed unexpectedly",
                    {"technical_reference": self._new_id()},
                )
                self._fail_snapshot(
                    database_path, item.id, snapshot_id, project_id,
                    actor, correlation_id, failure,
                )
                results.append(
                    ImportItemResult(
                        input_path=path,
                        snapshot_id=snapshot_id,
                        captured=False,
                        error_code=failure.code,
                        error_message=failure.message,
                    )
                )

        with self._database.unit_of_work(database_path) as uow:
            if accepted:
                final_status = ImportSessionStatus.INSPECTING
                event_type = EventType.IMPORT_SNAPSHOT_CAPTURE_FINISHED
                severity = EventSeverity.WARNING if failed else EventSeverity.INFO
                project_new_status = None
                finished_at = None
            else:
                final_status = ImportSessionStatus.FAILED
                event_type = EventType.IMPORT_FAILED
                severity = EventSeverity.ERROR
                project_new_status = ProjectStatus.FAILED
                finished_at = self._clock()
            uow.imports.update_session_status(
                session_id,
                ImportSessionStatus.SNAPSHOTTING,
                final_status,
                accepted_item_count=accepted,
                failed_item_count=failed,
                finished_at=finished_at,
            )
            if project_new_status is not None:
                uow.projects.update_status(
                    project_id,
                    ProjectStatus.IMPORTING,
                    project_new_status,
                    self._clock(),
                )
            self._event(
                uow,
                event_type,
                project_id,
                actor,
                correlation_id,
                import_session_id=session_id,
                severity=severity,
                previous_status=ImportSessionStatus.SNAPSHOTTING.value,
                new_status=final_status.value,
                details={"accepted_item_count": accepted, "failed_item_count": failed},
            )
            uow.commit()
        return ImportProjectItemsResult(
            project_id=project_id,
            import_session_id=session_id,
            session_status=final_status,
            requested_item_count=len(input_paths),
            accepted_item_count=accepted,
            failed_item_count=failed,
            items=tuple(results),
        )

    def verify(
        self, request: VerifyOriginalSnapshotRequest
    ) -> VerifyOriginalSnapshotResult:
        project_id = self._required(request.project_id, "project_id")
        actor = self._required(request.actor, "actor")
        database_path = self._absolute(request.database_path, "database_path")
        if request.chunk_size <= 0:
            raise ApplicationError("INVALID_REQUEST", "chunk_size must be positive")
        correlation_id = self._new_id()
        project_path = database_path.resolve(strict=False).parent
        with self._database.unit_of_work(database_path) as uow:
            self._project(uow, project_id, database_path)
            snapshot = uow.imports.get_snapshot(request.snapshot_id)
            if snapshot is None or snapshot.project_id != project_id:
                raise EntityNotFoundError(f"snapshot not found: {request.snapshot_id}")
            if snapshot.status not in {
                OriginalSnapshotStatus.READY,
                OriginalSnapshotStatus.MISSING,
                OriginalSnapshotStatus.MISMATCH,
                OriginalSnapshotStatus.UNREADABLE,
            }:
                raise ApplicationError(
                    "SNAPSHOT_NOT_VERIFIABLE",
                    "snapshot is not in a verifiable state",
                    {"status": snapshot.status.value},
                )
            source = uow.catalog.source_for_snapshot(snapshot.id)
            if source is None:
                raise ApplicationError(
                    ErrorCode.INTERNAL_ERROR.value,
                    "ready snapshot has no Source",
                )
            uow.imports.update_snapshot_status(
                snapshot.id, snapshot.status, OriginalSnapshotStatus.VERIFYING
            )
            uow.catalog.update_source_status(
                source.id, source.status, SourceStatus.VERIFYING, None
            )
            artifacts = tuple(uow.imports.original_artifacts_for_snapshot(snapshot.id))
            for artifact in artifacts:
                uow.imports.update_original_artifact_integrity(
                    artifact.id,
                    artifact.integrity_status,
                    ArtifactIntegrityStatus.VERIFYING,
                )
            self._event(
                uow, EventType.SNAPSHOT_VERIFICATION_STARTED, project_id, actor,
                correlation_id, snapshot_id=snapshot.id,
                previous_status=snapshot.status.value,
                new_status=OriginalSnapshotStatus.VERIFYING.value,
            )
            self._event(
                uow, EventType.SOURCE_VERIFICATION_STARTED, project_id, actor,
                correlation_id, snapshot_id=snapshot.id, source_id=source.id,
                previous_status=source.status.value,
                new_status=SourceStatus.VERIFYING.value,
            )
            uow.commit()
        failure: Optional[ApplicationError] = None
        artifact_results: dict[str, ArtifactIntegrityStatus] = {}
        for artifact in artifacts:
            try:
                self._store.verify_artifact(
                    project_path, artifact, chunk_size=request.chunk_size
                )
                artifact_results[artifact.id] = ArtifactIntegrityStatus.VERIFIED
            except ApplicationError as exc:
                if failure is None:
                    failure = exc
                artifact_results[artifact.id] = {
                    ErrorCode.ARTIFACT_MISSING.value: ArtifactIntegrityStatus.MISSING,
                    ErrorCode.ARTIFACT_HASH_MISMATCH.value: ArtifactIntegrityStatus.MISMATCH,
                }.get(exc.code, ArtifactIntegrityStatus.UNREADABLE)
        if failure is None:
            status = OriginalSnapshotStatus.READY
            event_type = EventType.SNAPSHOT_READY
            severity = EventSeverity.INFO
            error_code = None
            source_status = SourceStatus.AVAILABLE
            source_event_type = EventType.SOURCE_VERIFIED
        else:
            status = {
                ErrorCode.ARTIFACT_MISSING.value: OriginalSnapshotStatus.MISSING,
                ErrorCode.ARTIFACT_HASH_MISMATCH.value: OriginalSnapshotStatus.MISMATCH,
            }.get(failure.code, OriginalSnapshotStatus.UNREADABLE)
            event_type = EventType.SNAPSHOT_INTEGRITY_FAILED
            severity = EventSeverity.ERROR
            error_code = self._error_enum(failure.code)
            source_status = {
                OriginalSnapshotStatus.MISSING: SourceStatus.MISSING,
                OriginalSnapshotStatus.MISMATCH: SourceStatus.CHANGED,
            }.get(status, SourceStatus.UNREADABLE)
            source_event_type = {
                SourceStatus.MISSING: EventType.SOURCE_MISSING_DETECTED,
                SourceStatus.CHANGED: EventType.SOURCE_CHANGED_DETECTED,
            }.get(source_status, EventType.SOURCE_UNREADABLE_DETECTED)
        with self._database.unit_of_work(database_path) as uow:
            source = uow.catalog.source_for_snapshot(request.snapshot_id)
            if source is None:
                raise ApplicationError(
                    ErrorCode.INTERNAL_ERROR.value,
                    "verifying snapshot has no Source",
                )
            for artifact in artifacts:
                uow.imports.update_original_artifact_integrity(
                    artifact.id,
                    ArtifactIntegrityStatus.VERIFYING,
                    artifact_results[artifact.id],
                )
            uow.imports.update_snapshot_status(
                request.snapshot_id,
                OriginalSnapshotStatus.VERIFYING,
                status,
                verified_at=self._clock() if status == OriginalSnapshotStatus.READY else None,
            )
            uow.catalog.update_source_status(
                source.id,
                SourceStatus.VERIFYING,
                source_status,
                self._clock() if source_status == SourceStatus.AVAILABLE else None,
            )
            self._event(
                uow, event_type, project_id, actor, correlation_id,
                snapshot_id=request.snapshot_id,
                severity=severity,
                previous_status=OriginalSnapshotStatus.VERIFYING.value,
                new_status=status.value,
                error_code=error_code,
                details={} if failure is None else {"message": failure.message},
            )
            self._event(
                uow, source_event_type, project_id, actor, correlation_id,
                snapshot_id=request.snapshot_id, source_id=source.id,
                severity=severity,
                previous_status=SourceStatus.VERIFYING.value,
                new_status=source_status.value,
                error_code=error_code,
                details={} if failure is None else {"message": failure.message},
            )
            uow.commit()
        return VerifyOriginalSnapshotResult(
            project_id=project_id,
            snapshot_id=request.snapshot_id,
            status=status,
            verified_artifact_count=sum(
                result == ArtifactIntegrityStatus.VERIFIED
                for result in artifact_results.values()
            ),
        )

    def _persist_capture(
        self, *, database_path: Path, project_id: str, session_id: str,
        item_id: str, snapshot_id: str, source_input, captured,
        actor: str, correlation_id: str,
    ) -> tuple[str, str]:
        now = self._clock()
        source_id = self._new_id()
        node_id = self._new_id()
        with self._database.unit_of_work(database_path) as uow:
            uow.imports.update_snapshot_status(
                snapshot_id,
                OriginalSnapshotStatus.COPYING,
                OriginalSnapshotStatus.VERIFYING,
            )
            for value in captured.artifacts:
                uow.imports.add_original_artifact(
                    OriginalArtifact(
                        id=value.id,
                        project_id=project_id,
                        snapshot_id=snapshot_id,
                        storage_key=value.storage_key,
                        size=value.size,
                        sha256=value.sha256,
                        observed_modified_at=value.observed_modified_at,
                        integrity_status=ArtifactIntegrityStatus.VERIFIED,
                        created_at=now,
                    )
                )
            for value in captured.entries:
                uow.imports.add_snapshot_entry(
                    OriginalSnapshotEntry(
                        id=value.id,
                        project_id=project_id,
                        snapshot_id=snapshot_id,
                        parent_entry_id=value.parent_entry_id,
                        artifact_id=value.artifact_id,
                        kind=value.kind,
                        original_name=value.original_name,
                        ordinal=value.ordinal,
                        created_at=value.created_at,
                    )
                )
            source = Source(
                id=source_id,
                project_id=project_id,
                snapshot_id=snapshot_id,
                kind=source_input.kind,
                display_name=source_input.display_name,
                status=SourceStatus.AVAILABLE,
                created_at=now,
            )
            root_entry = next(
                entry for entry in captured.entries if entry.id == captured.root_entry_id
            )
            root_artifact = next(
                (value for value in captured.artifacts if value.id == root_entry.artifact_id),
                None,
            )
            root = Node(
                id=node_id,
                project_id=project_id,
                source_id=source_id,
                kind=NodeKind.CONTAINER if source_input.kind == SourceKind.FOLDER else NodeKind.FILE,
                format=NodeFormat.FOLDER if source_input.kind == SourceKind.FOLDER else NodeFormat.UNKNOWN,
                original_name=source_input.display_name,
                display_name=source_input.display_name,
                logical_path=f"/{logical_segment(source_input.display_name)}",
                depth=0,
                status=NodeProcessingStatus.DISCOVERED,
                discovery_key=f"snapshot:{snapshot_id}",
                declared_size=None if root_artifact is None else root_artifact.size,
                created_at=now,
                updated_at=now,
            )
            uow.catalog.add_source(source)
            uow.catalog.register_root(root)
            uow.imports.bind_snapshot_entry_to_source_node(root_entry.id, node_id)
            if root_artifact is not None:
                uow.imports.bind_original_artifact_to_source_node(root_artifact.id, node_id)
            uow.imports.update_snapshot_status(
                snapshot_id,
                OriginalSnapshotStatus.VERIFYING,
                OriginalSnapshotStatus.READY,
                verified_at=now,
            )
            uow.imports.update_session_item(
                item_id,
                ImportItemStatus.CAPTURING,
                ImportItemStatus.CAPTURED,
                updated_at=now,
            )
            self._event(
                uow, EventType.SNAPSHOT_READY, project_id, actor, correlation_id,
                import_session_id=session_id, snapshot_id=snapshot_id,
                previous_status=OriginalSnapshotStatus.VERIFYING.value,
                new_status=OriginalSnapshotStatus.READY.value,
                details={"entry_count": len(captured.entries), "artifact_count": len(captured.artifacts)},
            )
            self._event(
                uow, EventType.SOURCE_REGISTERED, project_id, actor, correlation_id,
                import_session_id=session_id, snapshot_id=snapshot_id,
                source_id=source_id, new_status=SourceStatus.AVAILABLE.value,
            )
            self._event(
                uow, EventType.NODE_DISCOVERED, project_id, actor, correlation_id,
                import_session_id=session_id, snapshot_id=snapshot_id,
                source_id=source_id, node_id=node_id,
                new_status=NodeProcessingStatus.DISCOVERED.value,
                details={"scope": "SOURCE_ROOT_ONLY", "inspection_deferred_to": "W3"},
            )
            uow.commit()
        return source_id, node_id

    def _fail_item(self, database_path, item, actor, correlation_id, exc) -> None:
        with self._database.unit_of_work(database_path) as uow:
            uow.imports.update_session_item(
                item.id, ImportItemStatus.PENDING, ImportItemStatus.FAILED,
                updated_at=self._clock(), error_code=exc.code, error_message=exc.message,
            )
            self._event(
                uow, EventType.SNAPSHOT_INTEGRITY_FAILED, item.project_id, actor,
                correlation_id, import_session_id=item.import_session_id,
                severity=EventSeverity.ERROR, error_code=self._error_enum(exc.code),
                details={"input_ordinal": item.ordinal, "message": exc.message},
            )
            uow.commit()

    def _fail_snapshot(
        self, database_path, item_id, snapshot_id, project_id,
        actor, correlation_id, exc,
    ) -> None:
        with self._database.unit_of_work(database_path) as uow:
            uow.imports.update_snapshot_status(
                snapshot_id, OriginalSnapshotStatus.COPYING, OriginalSnapshotStatus.FAILED
            )
            uow.imports.update_session_item(
                item_id, ImportItemStatus.CAPTURING, ImportItemStatus.FAILED,
                updated_at=self._clock(), error_code=exc.code, error_message=exc.message,
            )
            self._event(
                uow, EventType.SNAPSHOT_INTEGRITY_FAILED, project_id, actor,
                correlation_id, snapshot_id=snapshot_id,
                severity=EventSeverity.ERROR,
                previous_status=OriginalSnapshotStatus.COPYING.value,
                new_status=OriginalSnapshotStatus.FAILED.value,
                error_code=self._error_enum(exc.code), details={"message": exc.message},
            )
            uow.commit()

    def _interrupt(
        self, database_path, project_id, session_id, item_id, snapshot_id,
        actor, correlation_id,
    ) -> None:
        with self._database.unit_of_work(database_path) as uow:
            uow.imports.update_snapshot_status(
                snapshot_id, OriginalSnapshotStatus.COPYING,
                OriginalSnapshotStatus.INTERRUPTED,
            )
            uow.imports.update_session_item(
                item_id, ImportItemStatus.CAPTURING, ImportItemStatus.INTERRUPTED,
                updated_at=self._clock(), error_code="INTERRUPTED",
                error_message="snapshot capture was interrupted",
            )
            uow.imports.update_session_status(
                session_id, ImportSessionStatus.SNAPSHOTTING,
                ImportSessionStatus.INTERRUPTED, finished_at=self._clock(),
            )
            self._event(
                uow, EventType.IMPORT_INTERRUPTED, project_id, actor, correlation_id,
                import_session_id=session_id, snapshot_id=snapshot_id,
                severity=EventSeverity.WARNING,
                new_status=ImportSessionStatus.INTERRUPTED.value,
            )
            uow.commit()

    def _existing_result(self, uow, session: ImportSession) -> ImportProjectItemsResult:
        items = []
        for item in uow.imports.items_for_session(session.id):
            source = (
                None if item.snapshot_id is None
                else uow.catalog.source_for_snapshot(item.snapshot_id)
            )
            items.append(
                ImportItemResult(
                    input_path=Path(item.input_locator),
                    snapshot_id=item.snapshot_id,
                    captured=item.status == ImportItemStatus.CAPTURED,
                    source_id=None if source is None else source.id,
                    root_node_id=None if source is None else source.root_node_id,
                    error_code=item.error_code,
                    error_message=item.error_message,
                )
            )
        return ImportProjectItemsResult(
            project_id=session.project_id,
            import_session_id=session.id,
            session_status=session.status,
            requested_item_count=session.requested_item_count,
            accepted_item_count=session.accepted_item_count,
            failed_item_count=session.failed_item_count,
            items=tuple(items),
        )

    def _project(self, uow, project_id: str, database_path: Path):
        project = uow.projects.get(project_id)
        if project is None:
            raise EntityNotFoundError(f"project not found: {project_id}")
        if project.model_version != WORKBENCH_MODEL_VERSION:
            raise ApplicationError(
                "UNSUPPORTED_PROJECT_MODEL_VERSION", "unsupported Project data model"
            )
        if database_path.resolve(strict=False).parent.as_uri() != project.workspace_locator:
            raise ApplicationError(
                "PROJECT_DATABASE_MISMATCH", "database path is outside the Project workspace"
            )
        return project

    def _event(
        self, uow, event_type, project_id, actor, correlation_id, *,
        severity=EventSeverity.INFO, error_code=None, details=None, **links,
    ) -> None:
        uow.processing.append_event(
            ProcessingEvent(
                id=self._new_id(), event_type=event_type, project_id=project_id,
                actor=actor, occurred_at=self._clock(), severity=severity,
                correlation_id=correlation_id, error_code=error_code,
                details={} if details is None else details, **links,
            )
        )

    @staticmethod
    def _error_enum(code: str) -> ErrorCode:
        try:
            return ErrorCode(code)
        except ValueError:
            return ErrorCode.INTERNAL_ERROR

    @staticmethod
    def _required(value: str, field: str, maximum: int = 255) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > maximum:
            raise ApplicationError("INVALID_REQUEST", f"{field} is invalid")
        return normalized

    @staticmethod
    def _absolute(path: Path, field: str) -> Path:
        value = Path(path)
        if not value.is_absolute():
            raise ApplicationError("INVALID_REQUEST", f"{field} must be absolute")
        return value
