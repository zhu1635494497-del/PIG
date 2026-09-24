from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

from pig.application.contracts import (
    ProcessNodeRequest,
    ProcessNodeResult,
    ProcessProjectRequest,
    ProcessProjectResult,
    RecoverProjectRequest,
    RecoverProjectResult,
)
from pig.application.errors import ApplicationError
from pig.application.node_executor import ExecuteNodeRequest, ExecuteNodeResult, NodeExecutor
from pig.application.ports import (
    ProjectDatabaseProvider,
    QuarantineRecord,
    SourceInspector,
    WorkspaceRecovery,
)
from pig.domain.entities import ProcessingEvent, ProcessingJob, Project
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    ArtifactScope,
    AttemptStatus,
    ErrorCode,
    EventSeverity,
    EventType,
    JobStatus,
    JobType,
    NodeProcessingStatus,
    ProjectStatus,
    SourceStatus,
)
from pig.domain.exceptions import EntityNotFoundError
from pig.domain.processing_policy import ProcessingPolicy
from pig.domain.transitions import (
    require_attempt_transition,
    require_job_transition,
    require_node_transition,
    require_project_transition,
    require_source_transition,
)
from pig.handlers.base import ArtifactStore, ContainerHandlerRegistry


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


_ACTIVE_NODE_STATUSES = {
    NodeProcessingStatus.PENDING,
    NodeProcessingStatus.PROCESSING,
}
_RECOVERY_BLOCKING_NODE_STATUSES = _ACTIVE_NODE_STATUSES | {
    NodeProcessingStatus.INTERRUPTED
}
_INCOMPLETE_NODE_STATUSES = _ACTIVE_NODE_STATUSES | {
    NodeProcessingStatus.DISCOVERED,
    NodeProcessingStatus.INTERRUPTED,
}
_USABLE_NODE_STATUSES = {
    NodeProcessingStatus.SUCCESS,
    NodeProcessingStatus.PARTIAL_SUCCESS,
}


@dataclass(frozen=True, slots=True)
class _QueueResult:
    processed_node_ids: tuple[str, ...]
    attempt_ids: tuple[str, ...]
    warning_count: int
    error_count: int
    total_expanded_size: int


@dataclass(frozen=True, slots=True)
class _ReconciledState:
    recovery_job_id: str
    correlation_id: str
    interrupted_job_ids: tuple[str, ...]
    cancelled_job_ids: tuple[str, ...]
    interrupted_attempt_ids: tuple[str, ...]
    cancelled_attempt_ids: tuple[str, ...]
    recovered_node_ids: tuple[str, ...]
    known_artifact_keys: frozenset[str]
    known_manifest_keys: frozenset[str]


class ProjectProcessingService:
    """Own Job orchestration while delegating one-Node work to NodeExecutor."""

    def __init__(
        self,
        *,
        database: ProjectDatabaseProvider,
        source_inspector: SourceInspector,
        handlers: ContainerHandlerRegistry,
        artifact_store: ArtifactStore,
        workspace_recovery: WorkspaceRecovery | None = None,
        clock: Clock = _utc_now,
        id_generator: IdGenerator = _new_id,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._database = database
        self._clock = clock
        self._new_id = id_generator
        self._workspace_recovery = workspace_recovery
        self._executor = NodeExecutor(
            database=database,
            source_inspector=source_inspector,
            handlers=handlers,
            artifact_store=artifact_store,
            clock=clock,
            id_generator=id_generator,
            logger=logger,
        )

    def execute(self, request: ProcessNodeRequest) -> ProcessNodeResult:
        project_id = self._required(request.project_id, "project_id")
        node_id = self._required(request.node_id, "node_id")
        actor = self._required(request.actor, "actor")
        database_path = self._absolute_database_path(request.database_path)
        project = self._load_project(database_path, project_id)
        self._assert_no_recovery_required(database_path, project_id)
        with self._database.unit_of_work(database_path) as uow:
            node = uow.catalog.get_node(node_id)
            if node is None or node.project_id != project_id:
                raise EntityNotFoundError(f"node not found: {node_id}")
            if node.status != NodeProcessingStatus.DISCOVERED:
                raise ApplicationError(
                    code="NODE_NOT_PROCESSABLE",
                    message="process_node accepts only a DISCOVERED Node",
                    details={"node_id": node.id, "status": node.status.value},
                )

        job_id, correlation_id = self._start_job(
            database_path, project, actor, request.policy
        )
        executed = self._execute_node(
            database_path=database_path,
            project_id=project_id,
            node_id=node_id,
            job_id=job_id,
            correlation_id=correlation_id,
            actor=actor,
            policy=request.policy,
        )
        job_status = self._single_node_job_status(executed.node_status)
        project_status = self._project_projection(database_path, project_id)
        self._finish_job_and_project(
            database_path=database_path,
            project_id=project_id,
            job_id=job_id,
            correlation_id=correlation_id,
            actor=actor,
            job_status=job_status,
            project_status=project_status,
            warning_count=executed.warning_count,
            error_count=executed.error_count,
        )
        return ProcessNodeResult(
            project_id=project_id,
            node_id=node_id,
            node_status=executed.node_status,
            job_id=job_id,
            job_status=job_status,
            attempt_id=executed.attempt_id,
            child_node_ids=tuple(executed.child_node_ids),
            warning_count=executed.warning_count,
            error_count=executed.error_count,
        )

    def execute_project(self, request: ProcessProjectRequest) -> ProcessProjectResult:
        project_id = self._required(request.project_id, "project_id")
        actor = self._required(request.actor, "actor")
        database_path = self._absolute_database_path(request.database_path)
        project = self._load_project(database_path, project_id)
        self._assert_no_recovery_required(database_path, project_id)
        with self._database.unit_of_work(database_path) as uow:
            all_nodes = tuple(uow.catalog.nodes_for_project(project_id))
        if not all_nodes:
            raise ApplicationError(
                code="PROJECT_HAS_NO_NODES",
                message="Project has no registered Source Nodes to process",
                details={"project_id": project_id},
            )

        job_id, correlation_id = self._start_job(
            database_path, project, actor, request.policy
        )
        queue_result = self._run_queue(
            database_path=database_path,
            project_id=project_id,
            job_id=job_id,
            correlation_id=correlation_id,
            actor=actor,
            policy=request.policy,
            initial_node_ids=tuple(
                node.id
                for node in all_nodes
                if node.status == NodeProcessingStatus.DISCOVERED
            ),
        )

        project_status = self._project_projection(database_path, project_id)
        job_status = self._project_job_status(
            project_status, queue_result.warning_count, queue_result.error_count
        )
        self._finish_job_and_project(
            database_path=database_path,
            project_id=project_id,
            job_id=job_id,
            correlation_id=correlation_id,
            actor=actor,
            job_status=job_status,
            project_status=project_status,
            warning_count=queue_result.warning_count,
            error_count=queue_result.error_count,
        )
        return ProcessProjectResult(
            project_id=project_id,
            job_id=job_id,
            job_status=job_status,
            project_status=project_status,
            processed_node_ids=queue_result.processed_node_ids,
            attempt_ids=queue_result.attempt_ids,
            warning_count=queue_result.warning_count,
            error_count=queue_result.error_count,
            total_expanded_size=queue_result.total_expanded_size,
        )

    def recover_project(
        self, request: RecoverProjectRequest
    ) -> RecoverProjectResult:
        if self._workspace_recovery is None:
            raise ApplicationError(
                code="RECOVERY_NOT_CONFIGURED",
                message="workspace recovery is not configured",
            )
        project_id = self._required(request.project_id, "project_id")
        actor = self._required(request.actor, "actor")
        database_path = self._absolute_database_path(request.database_path)
        project = self._load_project(database_path, project_id)
        if project.status == ProjectStatus.CREATED:
            raise ApplicationError(
                code="RECOVERY_NOT_APPLICABLE",
                message="a Project without registered Sources cannot be recovered",
            )

        reconciled = self._begin_recovery(
            database_path=database_path,
            project=project,
            actor=actor,
            policy=request.policy,
        )
        self._start_existing_job(
            database_path,
            project_id,
            reconciled.recovery_job_id,
            reconciled.correlation_id,
            actor,
        )
        try:
            report = self._workspace_recovery.reconcile(
                database_path.resolve(strict=True).parent,
                reconciled.recovery_job_id,
                known_artifact_keys=reconciled.known_artifact_keys,
                known_manifest_keys=reconciled.known_manifest_keys,
            )
            self._record_quarantine(
                database_path,
                project_id,
                reconciled.recovery_job_id,
                reconciled.correlation_id,
                actor,
                tuple(report.records),
            )
            with self._database.unit_of_work(database_path) as uow:
                candidates = tuple(uow.catalog.nodes_for_project(project_id))
            queue_result = self._run_queue(
                database_path=database_path,
                project_id=project_id,
                job_id=reconciled.recovery_job_id,
                correlation_id=reconciled.correlation_id,
                actor=actor,
                policy=request.policy,
                initial_node_ids=tuple(
                    node.id
                    for node in candidates
                    if node.status
                    in {
                        NodeProcessingStatus.DISCOVERED,
                        NodeProcessingStatus.INTERRUPTED,
                    }
                ),
            )
        except Exception as exc:
            self._fail_recovery(
                database_path,
                project_id,
                reconciled.recovery_job_id,
                reconciled.correlation_id,
                actor,
                exc,
            )
            if isinstance(exc, ApplicationError):
                raise
            raise ApplicationError(
                code=ErrorCode.RECOVERY_FAILED.value,
                message="Project recovery failed",
            ) from exc

        warning_count = queue_result.warning_count + len(report.records)
        project_status = self._project_projection(database_path, project_id)
        job_status = self._project_job_status(
            project_status, warning_count, queue_result.error_count
        )
        self._finish_job_and_project(
            database_path=database_path,
            project_id=project_id,
            job_id=reconciled.recovery_job_id,
            correlation_id=reconciled.correlation_id,
            actor=actor,
            job_status=job_status,
            project_status=project_status,
            warning_count=warning_count,
            error_count=queue_result.error_count,
        )
        self._append_recovery_terminal(
            database_path,
            project_id,
            reconciled.recovery_job_id,
            reconciled.correlation_id,
            actor,
            EventType.RECOVERY_FINISHED,
            EventSeverity.WARNING if warning_count else EventSeverity.INFO,
            {
                "processed_node_count": len(queue_result.processed_node_ids),
                "quarantine_count": len(report.records),
                "warning_count": warning_count,
                "error_count": queue_result.error_count,
            },
        )
        return RecoverProjectResult(
            project_id=project_id,
            recovery_job_id=reconciled.recovery_job_id,
            job_status=job_status,
            project_status=project_status,
            interrupted_job_ids=reconciled.interrupted_job_ids,
            cancelled_job_ids=reconciled.cancelled_job_ids,
            interrupted_attempt_ids=reconciled.interrupted_attempt_ids,
            cancelled_attempt_ids=reconciled.cancelled_attempt_ids,
            recovered_node_ids=reconciled.recovered_node_ids,
            processed_node_ids=queue_result.processed_node_ids,
            attempt_ids=queue_result.attempt_ids,
            quarantine_records=tuple(report.records),
            warning_count=warning_count,
            error_count=queue_result.error_count,
            total_expanded_size=queue_result.total_expanded_size,
        )

    def _execute_node(
        self,
        *,
        database_path: Path,
        project_id: str,
        node_id: str,
        job_id: str,
        correlation_id: str,
        actor: str,
        policy: ProcessingPolicy,
    ) -> ExecuteNodeResult:
        return self._executor.execute(
            ExecuteNodeRequest(
                project_id=project_id,
                database_path=database_path,
                node_id=node_id,
                job_id=job_id,
                correlation_id=correlation_id,
                actor=actor,
                policy=policy,
            )
        )

    def _run_queue(
        self,
        *,
        database_path: Path,
        project_id: str,
        job_id: str,
        correlation_id: str,
        actor: str,
        policy: ProcessingPolicy,
        initial_node_ids: tuple[str, ...],
    ) -> _QueueResult:
        queue = deque(initial_node_ids)
        processed: list[str] = []
        attempts: list[str] = []
        warning_count = 0
        error_count = 0
        expanded_size = 0
        while queue:
            node_id = queue.popleft()
            remaining = max(policy.max_total_expanded_size - expanded_size, 0)
            executed = self._execute_node(
                database_path=database_path,
                project_id=project_id,
                node_id=node_id,
                job_id=job_id,
                correlation_id=correlation_id,
                actor=actor,
                policy=replace(policy, max_total_expanded_size=remaining),
            )
            processed.append(executed.node_id)
            attempts.append(executed.attempt_id)
            warning_count += executed.warning_count
            error_count += executed.error_count
            expanded_size += executed.workspace_bytes
            if executed.child_node_ids:
                with self._database.unit_of_work(database_path) as uow:
                    for child_id in executed.child_node_ids:
                        child = uow.catalog.get_node(child_id)
                        if child is None:
                            raise EntityNotFoundError(
                                f"newly discovered child not found: {child_id}"
                            )
                        if child.status == NodeProcessingStatus.DISCOVERED:
                            queue.append(child.id)
        return _QueueResult(
            processed_node_ids=tuple(processed),
            attempt_ids=tuple(attempts),
            warning_count=warning_count,
            error_count=error_count,
            total_expanded_size=expanded_size,
        )

    def _begin_recovery(
        self,
        *,
        database_path: Path,
        project: Project,
        actor: str,
        policy: ProcessingPolicy,
    ) -> _ReconciledState:
        recovery_job_id = self._new_id()
        correlation_id = self._new_id()
        occurred_at = self._clock()
        job_created_at = occurred_at + timedelta(microseconds=1)
        recovery_started_at = occurred_at + timedelta(microseconds=2)
        interrupted_jobs: list[str] = []
        cancelled_jobs: list[str] = []
        interrupted_attempts: list[str] = []
        cancelled_attempts: list[str] = []
        recovered_nodes: list[str] = []
        with self._database.unit_of_work(database_path) as uow:
            active_jobs = tuple(
                uow.processing.jobs_for_project(
                    project.id, (JobStatus.QUEUED, JobStatus.RUNNING)
                )
            )
            active_attempts = tuple(
                uow.processing.attempts_for_project(
                    project.id, (AttemptStatus.QUEUED, AttemptStatus.RUNNING)
                )
            )
            active_nodes = tuple(
                node
                for status in _ACTIVE_NODE_STATUSES
                for node in uow.catalog.nodes_for_project(project.id, status)
            )
            sources = tuple(uow.catalog.sources_for_project(project.id))
            artifacts = tuple(uow.catalog.artifacts_for_project(project.id))
            events = tuple(uow.processing.events_for_project(project.id))
            known_artifact_keys = frozenset(
                artifact.locator
                for artifact in artifacts
                if artifact.scope == ArtifactScope.PROJECT_WORKSPACE
            )
            known_manifest_keys = frozenset(
                storage_key
                for event in events
                if event.event_type == EventType.MANIFEST_EXPORTED
                for storage_key in (event.details.get("storage_key"),)
                if isinstance(storage_key, str)
            )

            for job in active_jobs:
                target = (
                    JobStatus.CANCELLED
                    if job.status == JobStatus.QUEUED
                    else JobStatus.INTERRUPTED
                )
                require_job_transition(job.status, target)
                uow.processing.update_job_status(
                    job.id,
                    job.status,
                    target,
                    finished_at=occurred_at,
                )
                if target == JobStatus.CANCELLED:
                    cancelled_jobs.append(job.id)
                else:
                    interrupted_jobs.append(job.id)
                uow.processing.append_event(
                    self._event(
                        event_type=(
                            EventType.JOB_CANCELLED
                            if target == JobStatus.CANCELLED
                            else EventType.JOB_INTERRUPTED
                        ),
                        project_id=project.id,
                        actor=actor,
                        correlation_id=correlation_id,
                        occurred_at=occurred_at,
                        job_id=job.id,
                        severity=EventSeverity.WARNING,
                        previous=job.status.value,
                        new=target.value,
                        details={"reason": "explicit_recovery"},
                    )
                )

            for attempt in active_attempts:
                target = (
                    AttemptStatus.CANCELLED
                    if attempt.status == AttemptStatus.QUEUED
                    else AttemptStatus.INTERRUPTED
                )
                require_attempt_transition(attempt.status, target)
                uow.processing.update_attempt_status(
                    attempt.id,
                    attempt.status,
                    target,
                    finished_at=occurred_at,
                )
                if target == AttemptStatus.CANCELLED:
                    cancelled_attempts.append(attempt.id)
                else:
                    interrupted_attempts.append(attempt.id)
                uow.processing.append_event(
                    self._event(
                        event_type=(
                            EventType.ATTEMPT_CANCELLED
                            if target == AttemptStatus.CANCELLED
                            else EventType.ATTEMPT_INTERRUPTED
                        ),
                        project_id=project.id,
                        actor=actor,
                        correlation_id=correlation_id,
                        occurred_at=occurred_at,
                        job_id=attempt.job_id,
                        attempt_id=attempt.id,
                        node_id=attempt.node_id,
                        severity=EventSeverity.WARNING,
                        previous=attempt.status.value,
                        new=target.value,
                        details={"reason": "explicit_recovery"},
                    )
                )

            for node in active_nodes:
                require_node_transition(
                    node.status, NodeProcessingStatus.INTERRUPTED
                )
                uow.catalog.update_node_status(
                    node.id,
                    node.status,
                    NodeProcessingStatus.INTERRUPTED,
                    occurred_at,
                )
                recovered_nodes.append(node.id)
                uow.processing.append_event(
                    self._event(
                        event_type=EventType.NODE_PROCESSING_INTERRUPTED,
                        project_id=project.id,
                        actor=actor,
                        correlation_id=correlation_id,
                        occurred_at=occurred_at,
                        job_id=None,
                        node_id=node.id,
                        severity=EventSeverity.WARNING,
                        previous=node.status.value,
                        new=NodeProcessingStatus.INTERRUPTED.value,
                        details={"reason": "explicit_recovery"},
                    )
                )

            for source in sources:
                if source.status != SourceStatus.VERIFYING:
                    continue
                require_source_transition(
                    SourceStatus.VERIFYING, SourceStatus.UNREADABLE
                )
                uow.catalog.update_source_status(
                    source.id,
                    SourceStatus.VERIFYING,
                    SourceStatus.UNREADABLE,
                    occurred_at,
                )
                uow.processing.append_event(
                    self._event(
                        event_type=EventType.SOURCE_UNREADABLE_DETECTED,
                        project_id=project.id,
                        actor=actor,
                        correlation_id=correlation_id,
                        occurred_at=occurred_at,
                        job_id=None,
                        source_id=source.id,
                        severity=EventSeverity.WARNING,
                        previous=SourceStatus.VERIFYING.value,
                        new=SourceStatus.UNREADABLE.value,
                        details={"reason": "verification_interrupted"},
                    )
                )

            for artifact in artifacts:
                if artifact.integrity_status != ArtifactIntegrityStatus.VERIFYING:
                    continue
                uow.catalog.update_artifact_integrity(
                    artifact.id,
                    ArtifactIntegrityStatus.VERIFYING,
                    ArtifactIntegrityStatus.UNREADABLE,
                    occurred_at,
                )
                uow.processing.append_event(
                    self._event(
                        event_type=EventType.ARTIFACT_VERIFICATION_INTERRUPTED,
                        project_id=project.id,
                        actor=actor,
                        correlation_id=correlation_id,
                        occurred_at=occurred_at,
                        job_id=None,
                        node_id=artifact.node_id,
                        severity=EventSeverity.WARNING,
                        previous=ArtifactIntegrityStatus.VERIFYING.value,
                        new=ArtifactIntegrityStatus.UNREADABLE.value,
                        details={
                            "artifact_id": artifact.id,
                            "reason": "verification_interrupted",
                        },
                    )
                )

            uow.processing.add_job(
                ProcessingJob(
                    id=recovery_job_id,
                    project_id=project.id,
                    type=JobType.RECOVER_INTERRUPTED,
                    status=JobStatus.QUEUED,
                    requested_by=actor,
                    policy_snapshot=policy.snapshot(),
                    created_at=occurred_at,
                )
            )
            if project.status != ProjectStatus.PROCESSING:
                require_project_transition(
                    project.status, ProjectStatus.PROCESSING
                )
                uow.projects.update_status(
                    project.id,
                    project.status,
                    ProjectStatus.PROCESSING,
                    occurred_at,
                )
                uow.processing.append_event(
                    self._event(
                        event_type=EventType.PROJECT_STATUS_CHANGED,
                        project_id=project.id,
                        actor=actor,
                        correlation_id=correlation_id,
                        occurred_at=occurred_at,
                        job_id=recovery_job_id,
                        previous=project.status.value,
                        new=ProjectStatus.PROCESSING.value,
                        details={"reason": "recovery_started"},
                    )
                )
            uow.processing.append_event(
                self._event(
                    event_type=EventType.JOB_CREATED,
                    project_id=project.id,
                    actor=actor,
                    correlation_id=correlation_id,
                    occurred_at=job_created_at,
                    job_id=recovery_job_id,
                    new=JobStatus.QUEUED.value,
                    details={"queue": "in_memory_deque", "job_scope": "recovery"},
                )
            )
            uow.processing.append_event(
                self._event(
                    event_type=EventType.RECOVERY_STARTED,
                    project_id=project.id,
                    actor=actor,
                    correlation_id=correlation_id,
                    occurred_at=recovery_started_at,
                    job_id=recovery_job_id,
                    new=JobStatus.QUEUED.value,
                    details={
                        "interrupted_job_count": len(interrupted_jobs),
                        "cancelled_job_count": len(cancelled_jobs),
                        "interrupted_attempt_count": len(interrupted_attempts),
                        "cancelled_attempt_count": len(cancelled_attempts),
                        "recovered_node_count": len(recovered_nodes),
                    },
                )
            )
            uow.commit()
        return _ReconciledState(
            recovery_job_id=recovery_job_id,
            correlation_id=correlation_id,
            interrupted_job_ids=tuple(interrupted_jobs),
            cancelled_job_ids=tuple(cancelled_jobs),
            interrupted_attempt_ids=tuple(interrupted_attempts),
            cancelled_attempt_ids=tuple(cancelled_attempts),
            recovered_node_ids=tuple(recovered_nodes),
            known_artifact_keys=known_artifact_keys,
            known_manifest_keys=known_manifest_keys,
        )

    def _start_existing_job(
        self,
        database_path: Path,
        project_id: str,
        job_id: str,
        correlation_id: str,
        actor: str,
    ) -> None:
        occurred_at = self._clock()
        with self._database.unit_of_work(database_path) as uow:
            require_job_transition(JobStatus.QUEUED, JobStatus.RUNNING)
            uow.processing.update_job_status(
                job_id,
                JobStatus.QUEUED,
                JobStatus.RUNNING,
                started_at=occurred_at,
            )
            uow.processing.append_event(
                self._event(
                    event_type=EventType.JOB_STARTED,
                    project_id=project_id,
                    actor=actor,
                    correlation_id=correlation_id,
                    occurred_at=occurred_at,
                    job_id=job_id,
                    previous=JobStatus.QUEUED.value,
                    new=JobStatus.RUNNING.value,
                )
            )
            uow.commit()

    def _record_quarantine(
        self,
        database_path: Path,
        project_id: str,
        job_id: str,
        correlation_id: str,
        actor: str,
        records: tuple[QuarantineRecord, ...],
    ) -> None:
        with self._database.unit_of_work(database_path) as uow:
            for record in records:
                uow.processing.append_event(
                    self._event(
                        event_type=EventType.ORPHAN_QUARANTINED,
                        project_id=project_id,
                        actor=actor,
                        correlation_id=correlation_id,
                        occurred_at=self._clock(),
                        job_id=job_id,
                        severity=EventSeverity.WARNING,
                        details={
                            "kind": record.kind,
                            "original_storage_key": record.original_storage_key,
                            "quarantine_storage_key": record.quarantine_storage_key,
                            "entry_type": record.entry_type,
                            "size": record.size,
                            "sha256": record.sha256,
                        },
                    )
                )
            uow.commit()

    def _append_recovery_terminal(
        self,
        database_path: Path,
        project_id: str,
        job_id: str,
        correlation_id: str,
        actor: str,
        event_type: EventType,
        severity: EventSeverity,
        details: dict[str, object],
        error_code: ErrorCode | None = None,
    ) -> None:
        with self._database.unit_of_work(database_path) as uow:
            uow.processing.append_event(
                self._event(
                    event_type=event_type,
                    project_id=project_id,
                    actor=actor,
                    correlation_id=correlation_id,
                    occurred_at=self._clock(),
                    job_id=job_id,
                    severity=severity,
                    details=details,
                    error_code=error_code,
                )
            )
            uow.commit()

    def _fail_recovery(
        self,
        database_path: Path,
        project_id: str,
        job_id: str,
        correlation_id: str,
        actor: str,
        failure: Exception,
    ) -> None:
        occurred_at = self._clock()
        project_event_at = occurred_at + timedelta(microseconds=1)
        recovery_event_at = occurred_at + timedelta(microseconds=2)
        failure_code = (
            failure.code
            if isinstance(failure, ApplicationError)
            else ErrorCode.RECOVERY_FAILED.value
        )
        event_error = (
            ErrorCode.WORKSPACE_INTEGRITY_FAILED
            if failure_code == ErrorCode.WORKSPACE_INTEGRITY_FAILED.value
            else ErrorCode.RECOVERY_FAILED
        )
        with self._database.unit_of_work(database_path) as uow:
            require_job_transition(JobStatus.RUNNING, JobStatus.FAILED)
            uow.processing.update_job_status(
                job_id,
                JobStatus.RUNNING,
                JobStatus.FAILED,
                finished_at=occurred_at,
                error_count=1,
            )
            uow.processing.append_event(
                self._event(
                    event_type=EventType.JOB_FINISHED,
                    project_id=project_id,
                    actor=actor,
                    correlation_id=correlation_id,
                    occurred_at=occurred_at,
                    job_id=job_id,
                    severity=EventSeverity.ERROR,
                    previous=JobStatus.RUNNING.value,
                    new=JobStatus.FAILED.value,
                    error_code=event_error,
                    details={"failure_code": failure_code},
                )
            )
            project = uow.projects.get(project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            if project.status == ProjectStatus.PROCESSING:
                require_project_transition(
                    ProjectStatus.PROCESSING, ProjectStatus.FAILED
                )
                uow.projects.update_status(
                    project_id,
                    ProjectStatus.PROCESSING,
                    ProjectStatus.FAILED,
                    occurred_at,
                )
                uow.processing.append_event(
                    self._event(
                        event_type=EventType.PROJECT_STATUS_CHANGED,
                        project_id=project_id,
                        actor=actor,
                        correlation_id=correlation_id,
                        occurred_at=project_event_at,
                        job_id=job_id,
                        severity=EventSeverity.ERROR,
                        previous=ProjectStatus.PROCESSING.value,
                        new=ProjectStatus.FAILED.value,
                        error_code=event_error,
                        details={"reason": "recovery_failed"},
                    )
                )
            uow.processing.append_event(
                self._event(
                    event_type=EventType.RECOVERY_FAILED,
                    project_id=project_id,
                    actor=actor,
                    correlation_id=correlation_id,
                    occurred_at=recovery_event_at,
                    job_id=job_id,
                    severity=EventSeverity.ERROR,
                    error_code=event_error,
                    details={"failure_code": failure_code},
                )
            )
            uow.commit()

    def _start_job(
        self,
        database_path: Path,
        project: Project,
        actor: str,
        policy: ProcessingPolicy,
        job_type: JobType = JobType.PROCESS_PROJECT,
    ) -> tuple[str, str]:
        job_id = self._new_id()
        correlation_id = self._new_id()
        queued_at = self._clock()
        with self._database.unit_of_work(database_path) as uow:
            uow.processing.add_job(
                ProcessingJob(
                    id=job_id,
                    project_id=project.id,
                    type=job_type,
                    status=JobStatus.QUEUED,
                    requested_by=actor,
                    policy_snapshot=policy.snapshot(),
                    created_at=queued_at,
                )
            )
            if project.status != ProjectStatus.PROCESSING:
                require_project_transition(project.status, ProjectStatus.PROCESSING)
                uow.projects.update_status(
                    project.id, project.status, ProjectStatus.PROCESSING, queued_at
                )
                uow.processing.append_event(
                    self._event(
                        event_type=EventType.PROJECT_STATUS_CHANGED,
                        project_id=project.id,
                        actor=actor,
                        correlation_id=correlation_id,
                        occurred_at=queued_at,
                        job_id=job_id,
                        previous=project.status.value,
                        new=ProjectStatus.PROCESSING.value,
                        details={"reason": "processing_job_started"},
                    )
                )
            uow.processing.append_event(
                self._event(
                    event_type=EventType.JOB_CREATED,
                    project_id=project.id,
                    actor=actor,
                    correlation_id=correlation_id,
                    occurred_at=queued_at,
                    job_id=job_id,
                    new=JobStatus.QUEUED.value,
                    details={"queue": "in_memory_deque", "job_scope": "project"},
                )
            )
            uow.commit()

        started_at = self._clock()
        with self._database.unit_of_work(database_path) as uow:
            require_job_transition(JobStatus.QUEUED, JobStatus.RUNNING)
            uow.processing.update_job_status(
                job_id, JobStatus.QUEUED, JobStatus.RUNNING, started_at=started_at
            )
            uow.processing.append_event(
                self._event(
                    event_type=EventType.JOB_STARTED,
                    project_id=project.id,
                    actor=actor,
                    correlation_id=correlation_id,
                    occurred_at=started_at,
                    job_id=job_id,
                    previous=JobStatus.QUEUED.value,
                    new=JobStatus.RUNNING.value,
                )
            )
            uow.commit()
        return job_id, correlation_id

    def _finish_job_and_project(
        self,
        *,
        database_path: Path,
        project_id: str,
        job_id: str,
        correlation_id: str,
        actor: str,
        job_status: JobStatus,
        project_status: ProjectStatus,
        warning_count: int,
        error_count: int,
    ) -> None:
        finished_at = self._clock()
        with self._database.unit_of_work(database_path) as uow:
            require_job_transition(JobStatus.RUNNING, job_status)
            uow.processing.update_job_status(
                job_id,
                JobStatus.RUNNING,
                job_status,
                finished_at=finished_at,
                warning_count=warning_count,
                error_count=error_count,
            )
            severity = (
                EventSeverity.ERROR
                if job_status == JobStatus.FAILED
                else EventSeverity.WARNING
                if job_status == JobStatus.PARTIAL_SUCCESS
                else EventSeverity.INFO
            )
            uow.processing.append_event(
                self._event(
                    event_type=EventType.JOB_FINISHED,
                    project_id=project_id,
                    actor=actor,
                    correlation_id=correlation_id,
                    occurred_at=finished_at,
                    job_id=job_id,
                    severity=severity,
                    previous=JobStatus.RUNNING.value,
                    new=job_status.value,
                    details={"warning_count": warning_count, "error_count": error_count},
                )
            )
            project = uow.projects.get(project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            if project.status != project_status:
                require_project_transition(project.status, project_status)
                uow.projects.update_status(
                    project_id, project.status, project_status, finished_at
                )
                uow.processing.append_event(
                    self._event(
                        event_type=EventType.PROJECT_STATUS_CHANGED,
                        project_id=project_id,
                        actor=actor,
                        correlation_id=correlation_id,
                        occurred_at=finished_at,
                        job_id=job_id,
                        severity=severity,
                        previous=project.status.value,
                        new=project_status.value,
                        details={"reason": "processing_job_finished"},
                    )
                )
            uow.commit()

    def _assert_no_recovery_required(self, database_path: Path, project_id: str) -> None:
        with self._database.unit_of_work(database_path) as uow:
            active_jobs = tuple(
                uow.processing.jobs_for_project(
                    project_id, (JobStatus.QUEUED, JobStatus.RUNNING)
                )
            )
            active_nodes = tuple(
                node
                for status in _RECOVERY_BLOCKING_NODE_STATUSES
                for node in uow.catalog.nodes_for_project(project_id, status)
            )
            active_attempts = tuple(
                uow.processing.attempts_for_project(
                    project_id, (AttemptStatus.QUEUED, AttemptStatus.RUNNING)
                )
            )
        if active_jobs or active_nodes or active_attempts:
            raise ApplicationError(
                code="RECOVERY_REQUIRED",
                message="Project contains interrupted processing state; run explicit Project recovery before processing",
                details={
                    "job_ids": [job.id for job in active_jobs],
                    "node_ids": [node.id for node in active_nodes],
                    "attempt_ids": [attempt.id for attempt in active_attempts],
                },
            )

    def _project_projection(self, database_path: Path, project_id: str) -> ProjectStatus:
        with self._database.unit_of_work(database_path) as uow:
            nodes = tuple(uow.catalog.nodes_for_project(project_id))
        statuses = {node.status for node in nodes}
        if statuses & _INCOMPLETE_NODE_STATUSES:
            return ProjectStatus.PROCESSING
        if statuses and statuses <= {NodeProcessingStatus.SUCCESS}:
            return ProjectStatus.READY
        if statuses & _USABLE_NODE_STATUSES:
            return ProjectStatus.READY_WITH_WARNINGS
        return ProjectStatus.FAILED

    def _load_project(self, database_path: Path, project_id: str) -> Project:
        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(project_id)
        if project is None:
            raise EntityNotFoundError(f"project not found: {project_id}")
        if database_path.resolve(strict=False).parent.as_uri() != project.workspace_locator:
            raise ApplicationError(
                code="PROJECT_DATABASE_MISMATCH",
                message="database path is outside the Project workspace",
            )
        return project

    def _event(
        self,
        *,
        event_type: EventType,
        project_id: str,
        actor: str,
        correlation_id: str,
        occurred_at: datetime,
        job_id: Optional[str],
        severity: EventSeverity = EventSeverity.INFO,
        source_id: Optional[str] = None,
        node_id: Optional[str] = None,
        attempt_id: Optional[str] = None,
        error_code: Optional[ErrorCode] = None,
        previous: Optional[str] = None,
        new: Optional[str] = None,
        details: Optional[dict[str, object]] = None,
    ) -> ProcessingEvent:
        return ProcessingEvent(
            id=self._new_id(),
            event_type=event_type,
            project_id=project_id,
            actor=actor,
            occurred_at=occurred_at,
            severity=severity,
            correlation_id=correlation_id,
            job_id=job_id,
            source_id=source_id,
            node_id=node_id,
            attempt_id=attempt_id,
            error_code=error_code,
            previous_status=previous,
            new_status=new,
            details=details or {},
        )

    @staticmethod
    def _single_node_job_status(status: NodeProcessingStatus) -> JobStatus:
        if status == NodeProcessingStatus.SUCCESS:
            return JobStatus.SUCCESS
        if status == NodeProcessingStatus.PARTIAL_SUCCESS:
            return JobStatus.PARTIAL_SUCCESS
        return JobStatus.FAILED

    @staticmethod
    def _project_job_status(
        project_status: ProjectStatus, warnings: int, errors: int
    ) -> JobStatus:
        if project_status == ProjectStatus.FAILED:
            return JobStatus.FAILED
        if warnings or errors or project_status == ProjectStatus.READY_WITH_WARNINGS:
            return JobStatus.PARTIAL_SUCCESS
        return JobStatus.SUCCESS

    @staticmethod
    def _absolute_database_path(value: Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            raise ApplicationError(code="INVALID_REQUEST", message="database_path must be absolute")
        return path

    @staticmethod
    def _required(value: str, field: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ApplicationError(code="INVALID_REQUEST", message=f"{field} must not be empty")
        return normalized
