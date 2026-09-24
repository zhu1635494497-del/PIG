from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable
from uuid import uuid4

from pig.application.contracts import (
    InspectProjectRecoveryRequest,
    InspectProjectRecoveryResult,
    RecoverWorkbenchProjectRequest,
    RecoverWorkbenchProjectResult,
)
from pig.application.errors import ApplicationError
from pig.application.ports import (
    ProjectDatabaseProvider,
    RecoveryCandidate,
    WorkbenchRecoveryStore,
)
from pig.domain.entities import ProcessingEvent, RecoveryItem, RecoveryRun
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    EventSeverity,
    EventType,
    ImportItemStatus,
    ImportSessionStatus,
    OriginalSnapshotStatus,
    RecoveryItemStatus,
    RecoveryAction,
    RecoveryItemKind,
    RecoveryRunStatus,
    WorkspaceItemLifecycleStatus,
    WorkspaceMaterializationStatus,
)
from pig.domain.exceptions import EntityNotFoundError
from pig.domain.model_version import WORKBENCH_MODEL_VERSION


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkbenchRecoveryService:
    def __init__(
        self,
        *,
        database: ProjectDatabaseProvider,
        store: WorkbenchRecoveryStore,
        clock: Clock = _utc_now,
        id_generator: IdGenerator = lambda: str(uuid4()),
    ) -> None:
        self._database = database
        self._store = store
        self._clock = clock
        self._new_id = id_generator

    def inspect(
        self, request: InspectProjectRecoveryRequest
    ) -> InspectProjectRecoveryResult:
        project_id = self._required(request.project_id, "project_id")
        database_path = self._database_path(request.database_path)
        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            if project.model_version != WORKBENCH_MODEL_VERSION:
                raise ApplicationError(
                    "UNSUPPORTED_PROJECT_MODEL",
                    "Project model is not supported by Workbench Recovery",
                )
            snapshots = tuple(uow.imports.snapshots_for_project(project_id))
            purged_snapshot_ids = frozenset(
                value.id
                for value in snapshots
                if value.status == OriginalSnapshotStatus.PURGED
            )
            known_original_keys = frozenset(
                artifact.storage_key
                for snapshot in snapshots
                for artifact in uow.imports.original_artifacts_for_snapshot(snapshot.id)
                if artifact.integrity_status != ArtifactIntegrityStatus.PURGED
            )
            active_items = tuple(
                item
                for item in uow.workspace.items_for_project(
                    project_id, include_deleted=True
                )
                if item.lifecycle_status != WorkspaceItemLifecycleStatus.PURGED
            )
            working = tuple(
                artifact
                for item in active_items
                for artifact in (uow.workspace.working_artifact_for_item(item.id),)
                if artifact is not None
            )
            known_working_keys = frozenset(value.storage_key for value in working)
            known_version_keys = frozenset(
                revision.storage_key
                for artifact in working
                for revision in uow.workspace.working_revisions_for_artifact(artifact.id)
            )
            state_candidates = [
                RecoveryCandidate(
                    kind=RecoveryItemKind.SNAPSHOT_STAGING,
                    action=RecoveryAction.UNCHANGED,
                    storage_key=f".recovery-state/import-sessions/{session.id}",
                    operation_id=session.id,
                    reason="import session was active when the process stopped",
                    details={"state_entity": "IMPORT_SESSION", "id": session.id},
                )
                for session in uow.imports.sessions_for_project(project_id)
                if session.status == ImportSessionStatus.SNAPSHOTTING
            ]
            state_candidates.extend(
                RecoveryCandidate(
                    kind=RecoveryItemKind.MATERIALIZATION_STAGING,
                    action=RecoveryAction.UNCHANGED,
                    storage_key=f".recovery-state/workspace-items/{item.id}",
                    operation_id=item.id,
                    reason="workspace materialization was active when the process stopped",
                    details={"state_entity": "WORKSPACE_ITEM", "id": item.id},
                )
                for item in active_items
                if item.materialization_status
                == WorkspaceMaterializationStatus.MATERIALIZING
            )
        inspection = self._store.inspect(
            database_path.parent,
            project_id,
            known_original_keys=known_original_keys,
            known_working_keys=known_working_keys,
            known_version_keys=known_version_keys,
            purged_snapshot_ids=purged_snapshot_ids,
        )
        candidates = tuple(inspection.candidates) + tuple(state_candidates)
        token = self._candidate_token(candidates)
        return InspectProjectRecoveryResult(
            project_id=project_id,
            inspection_token=token,
            recovery_required=bool(candidates),
            candidates=candidates,
        )

    def assert_writable(self, project_id: str, database_path: Path) -> None:
        result = self.inspect(
            InspectProjectRecoveryRequest(
                project_id=project_id,
                database_path=database_path,
            )
        )
        if result.recovery_required:
            raise ApplicationError(
                "RECOVERY_REQUIRED",
                "Project contains an interrupted filesystem operation; recover it before writing",
                {
                    "candidate_count": len(result.candidates),
                    "inspection_token": result.inspection_token,
                },
            )

    def recover(
        self, request: RecoverWorkbenchProjectRequest
    ) -> RecoverWorkbenchProjectResult:
        project_id = self._required(request.project_id, "project_id")
        actor = self._required(request.actor, "actor")
        if not request.confirmed:
            raise ApplicationError(
                "RECOVERY_CONFIRMATION_REQUIRED",
                "Project Recovery requires explicit confirmation",
            )
        database_path = self._database_path(request.database_path)
        inspected = self.inspect(
            InspectProjectRecoveryRequest(
                project_id=project_id,
                database_path=database_path,
            )
        )
        if inspected.inspection_token != request.inspection_token:
            raise ApplicationError(
                "RECOVERY_PLAN_CHANGED",
                "Recovery candidates changed; inspect the Project again",
            )
        if not inspected.candidates:
            raise ApplicationError(
                "RECOVERY_NOT_REQUIRED", "Project has no recoverable residue"
            )

        self._database.migrate(database_path)
        now = self._clock()
        run_id = self._new_id()
        correlation_id = self._new_id()
        run = RecoveryRun(
            id=run_id,
            project_id=project_id,
            status=RecoveryRunStatus.DETECTED,
            actor=actor,
            correlation_id=correlation_id,
            detected_count=len(inspected.candidates),
            recovered_count=0,
            failed_count=0,
            created_at=now,
        )
        item_pairs: list[tuple[RecoveryItem, object]] = []
        with self._database.unit_of_work(database_path) as uow:
            self._terminalize_interrupted_recovery_runs(
                uow,
                project_id=project_id,
                actor=actor,
                correlation_id=correlation_id,
                occurred_at=now,
            )
            uow.recovery.add_run(run)
            for candidate in inspected.candidates:
                item = RecoveryItem(
                    id=self._new_id(),
                    recovery_run_id=run_id,
                    project_id=project_id,
                    kind=candidate.kind,
                    action=candidate.action,
                    status=RecoveryItemStatus.DISCOVERED,
                    storage_key=candidate.storage_key,
                    operation_id=candidate.operation_id,
                    reason=candidate.reason,
                    created_at=now,
                )
                uow.recovery.add_item(item)
                item = uow.recovery.update_item_status(
                    item.id,
                    RecoveryItemStatus.DISCOVERED,
                    RecoveryItemStatus.PLANNED,
                    updated_at=now,
                )
                item_pairs.append((item, candidate))
            uow.recovery.update_run_status(
                run_id,
                RecoveryRunStatus.DETECTED,
                RecoveryRunStatus.AWAITING_CONFIRMATION,
            )
            run = uow.recovery.update_run_status(
                run_id,
                RecoveryRunStatus.AWAITING_CONFIRMATION,
                RecoveryRunStatus.RUNNING,
                started_at=now,
            )
            uow.processing.append_event(
                self._event(
                    EventType.RECOVERY_STARTED,
                    project_id,
                    actor,
                    correlation_id,
                    details={
                        "recovery_run_id": run_id,
                        "candidate_count": len(item_pairs),
                        "inspection_token": request.inspection_token,
                    },
                    new_status=RecoveryRunStatus.RUNNING.value,
                )
            )
            uow.commit()

        recovered = 0
        failed = 0
        for item, candidate in item_pairs:
            occurred_at = self._clock()
            try:
                disposition = self._store.execute(
                    database_path.parent,
                    run_id,
                    item.id,
                    candidate,  # type: ignore[arg-type]
                )
                terminal = RecoveryItemStatus(disposition.status)
                recovered += 1
                error_code = None
                error_message = None
                size = disposition.size
                sha256 = disposition.sha256
                recovery_key = disposition.recovery_storage_key
            except BaseException as exc:
                terminal = RecoveryItemStatus.FAILED
                failed += 1
                error_code = (
                    exc.code if isinstance(exc, ApplicationError) else "RECOVERY_FAILED"
                )
                error_message = (
                    exc.message
                    if isinstance(exc, ApplicationError)
                    else "Recovery item failed; see Debug Log"
                )
                size = None
                sha256 = None
                recovery_key = None
            with self._database.unit_of_work(database_path) as uow:
                self._reconcile_state_candidate(uow, candidate, occurred_at)
                uow.recovery.update_item_status(
                    item.id,
                    RecoveryItemStatus.PLANNED,
                    terminal,
                    updated_at=occurred_at,
                    size=size,
                    sha256=sha256,
                    recovery_storage_key=recovery_key,
                    error_code=error_code,
                    error_message=error_message,
                )
                event_type = (
                    EventType.ORPHAN_QUARANTINED
                    if terminal == RecoveryItemStatus.QUARANTINED
                    else (
                        EventType.RECOVERY_FAILED
                        if terminal == RecoveryItemStatus.FAILED
                        else EventType.RECOVERY_FINISHED
                    )
                )
                uow.processing.append_event(
                    self._event(
                        event_type,
                        project_id,
                        actor,
                        correlation_id,
                        severity=(
                            EventSeverity.ERROR
                            if terminal == RecoveryItemStatus.FAILED
                            else EventSeverity.INFO
                        ),
                        details={
                            "scope": "ITEM",
                            "recovery_run_id": run_id,
                            "recovery_item_id": item.id,
                            "kind": item.kind.value,
                            "action": item.action.value,
                            "storage_key": item.storage_key,
                            "recovery_storage_key": recovery_key,
                            "size": size,
                            "sha256": sha256,
                            "error_message": error_message,
                        },
                        error_code=error_code,
                        new_status=terminal.value,
                    )
                )
                uow.commit()

        remaining = self.inspect(
            InspectProjectRecoveryRequest(
                project_id=project_id,
                database_path=database_path,
            )
        )
        if failed == 0 and not remaining.candidates:
            terminal_run = RecoveryRunStatus.SUCCESS
        elif recovered > 0:
            terminal_run = RecoveryRunStatus.PARTIAL_SUCCESS
        else:
            terminal_run = RecoveryRunStatus.FAILED
        finished_at = self._clock()
        with self._database.unit_of_work(database_path) as uow:
            run = uow.recovery.update_run_status(
                run_id,
                RecoveryRunStatus.RUNNING,
                terminal_run,
                finished_at=finished_at,
                recovered_count=recovered,
                failed_count=failed,
            )
            uow.processing.append_event(
                self._event(
                    (
                        EventType.RECOVERY_FINISHED
                        if terminal_run == RecoveryRunStatus.SUCCESS
                        else EventType.RECOVERY_FAILED
                    ),
                    project_id,
                    actor,
                    correlation_id,
                    severity=(
                        EventSeverity.INFO
                        if terminal_run == RecoveryRunStatus.SUCCESS
                        else EventSeverity.ERROR
                    ),
                    details={
                        "scope": "RUN",
                        "recovery_run_id": run_id,
                        "recovered_count": recovered,
                        "failed_count": failed,
                        "remaining_candidate_count": len(remaining.candidates),
                    },
                    new_status=terminal_run.value,
                )
            )
            items = tuple(uow.recovery.items_for_run(run_id))
            uow.commit()
        return RecoverWorkbenchProjectResult(
            project_id=project_id,
            recovery_run=run,
            recovery_items=items,
            remaining_candidate_count=len(remaining.candidates),
        )

    def _terminalize_interrupted_recovery_runs(
        self,
        uow,
        *,
        project_id: str,
        actor: str,
        correlation_id: str,
        occurred_at: datetime,
    ) -> None:
        nonterminal_runs = {
            RecoveryRunStatus.DETECTED,
            RecoveryRunStatus.AWAITING_CONFIRMATION,
            RecoveryRunStatus.RUNNING,
        }
        nonterminal_items = {
            RecoveryItemStatus.DISCOVERED,
            RecoveryItemStatus.PLANNED,
        }
        for previous in uow.recovery.runs_for_project(project_id):
            if previous.status not in nonterminal_runs:
                continue
            interrupted_items = 0
            for item in uow.recovery.items_for_run(previous.id):
                if item.status not in nonterminal_items:
                    continue
                uow.recovery.update_item_status(
                    item.id,
                    item.status,
                    RecoveryItemStatus.FAILED,
                    updated_at=occurred_at,
                    error_code="RECOVERY_INTERRUPTED",
                    error_message="Previous recovery stopped before the item completed",
                )
                interrupted_items += 1
            uow.recovery.update_run_status(
                previous.id,
                previous.status,
                RecoveryRunStatus.FAILED,
                finished_at=occurred_at,
                failed_count=max(previous.failed_count, interrupted_items),
            )
            uow.processing.append_event(
                self._event(
                    EventType.RECOVERY_FAILED,
                    project_id,
                    actor,
                    correlation_id,
                    severity=EventSeverity.ERROR,
                    details={
                        "scope": "RUN",
                        "recovery_run_id": previous.id,
                        "reason": "RECOVERY_INTERRUPTED",
                        "interrupted_item_count": interrupted_items,
                    },
                    error_code="RECOVERY_INTERRUPTED",
                    new_status=RecoveryRunStatus.FAILED.value,
                )
            )

    def _event(
        self,
        event_type: EventType,
        project_id: str,
        actor: str,
        correlation_id: str,
        *,
        details: dict[str, object],
        severity: EventSeverity = EventSeverity.INFO,
        error_code=None,
        new_status: str | None = None,
    ) -> ProcessingEvent:
        return ProcessingEvent(
            id=self._new_id(),
            event_type=event_type,
            project_id=project_id,
            actor=actor,
            occurred_at=self._clock(),
            severity=severity,
            correlation_id=correlation_id,
            details=details,
            error_code=error_code,
            new_status=new_status,
        )

    @staticmethod
    def _candidate_token(candidates) -> str:
        payload = [
            {
                "kind": value.kind.value,
                "action": value.action.value,
                "storage_key": value.storage_key,
                "operation_id": value.operation_id,
                "reason": value.reason,
                "details": value.details or {},
            }
            for value in candidates
        ]
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _reconcile_state_candidate(uow, candidate, occurred_at: datetime) -> None:
        details = candidate.details or {}
        entity = details.get("state_entity")
        identity = details.get("id")
        if not isinstance(identity, str):
            return
        if entity == "IMPORT_SESSION":
            session = uow.imports.get_session(identity)
            if session is None or session.status not in {
                ImportSessionStatus.QUEUED,
                ImportSessionStatus.SNAPSHOTTING,
                ImportSessionStatus.INSPECTING,
            }:
                return
            for item in uow.imports.items_for_session(session.id):
                if item.status in {ImportItemStatus.PENDING, ImportItemStatus.CAPTURING}:
                    uow.imports.update_session_item(
                        item.id,
                        item.status,
                        ImportItemStatus.INTERRUPTED,
                        updated_at=occurred_at,
                    )
                if item.snapshot_id is not None:
                    snapshot = uow.imports.get_snapshot(item.snapshot_id)
                    if snapshot is not None and snapshot.status in {
                        OriginalSnapshotStatus.COPYING,
                        OriginalSnapshotStatus.VERIFYING,
                    }:
                        uow.imports.update_snapshot_status(
                            snapshot.id,
                            snapshot.status,
                            OriginalSnapshotStatus.INTERRUPTED,
                        )
            uow.imports.update_session_status(
                session.id,
                session.status,
                ImportSessionStatus.INTERRUPTED,
                finished_at=occurred_at,
            )
        elif entity == "WORKSPACE_ITEM":
            item = uow.workspace.get_item(identity)
            if (
                item is not None
                and item.materialization_status
                == WorkspaceMaterializationStatus.MATERIALIZING
            ):
                uow.workspace.update_materialization_status(
                    item.id,
                    WorkspaceMaterializationStatus.MATERIALIZING,
                    WorkspaceMaterializationStatus.INTERRUPTED,
                    updated_at=occurred_at,
                )

    @staticmethod
    def _required(value: str, field: str) -> str:
        result = value.strip()
        if not result:
            raise ApplicationError("INVALID_REQUEST", f"{field} is required")
        return result

    @staticmethod
    def _database_path(value: Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            raise ApplicationError(
                "INVALID_REQUEST", "database_path must be absolute"
            )
        return path.resolve(strict=True)
