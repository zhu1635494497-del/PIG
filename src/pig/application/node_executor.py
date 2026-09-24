from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence
from uuid import uuid4

from pig.application.errors import ApplicationError
from pig.application.evidence import external_source_parts
from pig.application.ports import ProjectDatabaseProvider, SourceInspector
from pig.domain.detection import DetectionResult, detect_node_format
from pig.domain.entities import (
    Artifact,
    Node,
    NodeMetadata,
    NodeRelationship,
    ProcessingAttempt,
    ProcessingError,
    ProcessingEvent,
    Project,
    Source,
)
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    ArtifactScope,
    AttemptStatus,
    ErrorCategory,
    ErrorCode,
    EventSeverity,
    EventType,
    NodeFormat,
    NodeKind,
    NodeProcessingStatus,
    ProcessingStage,
    RelationshipType,
    SourceKind,
    SourceStatus,
)
from pig.domain.exceptions import EntityNotFoundError
from pig.domain.paths import (
    archive_child_path,
    blocked_archive_child_path,
    folder_child_path,
    safe_display_name,
)
from pig.domain.processing_policy import ProcessingPolicy
from pig.domain.repositories import UnitOfWork
from pig.domain.transitions import (
    require_attempt_transition,
    require_node_transition,
    require_source_transition,
)
from pig.handlers.base import (
    ArtifactStore,
    ArtifactWriteSession,
    ChildDescriptor,
    ChildMaterialization,
    ContainerHandler,
    ContainerHandlerRegistry,
    HandlerOutcomeError,
    MetadataDescriptor,
)


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecuteNodeRequest:
    project_id: str
    database_path: Path
    node_id: str
    job_id: str
    correlation_id: str
    actor: str
    policy: ProcessingPolicy


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecuteNodeResult:
    node_id: str
    attempt_id: str
    node_status: NodeProcessingStatus
    child_node_ids: Sequence[str]
    warning_count: int
    error_count: int
    workspace_bytes: int


@dataclass(slots=True)
class _Context:
    project: Project
    source: Source
    node: Node
    artifact: Optional[Artifact]
    external_parts: tuple[str, ...]
    is_source_root: bool


@dataclass(slots=True)
class _InputObservation:
    path: Path
    signature: bytes
    observed_at: datetime


@dataclass(slots=True)
class _ChildRecord:
    node: Node
    relationship: NodeRelationship
    artifact: Optional[Artifact]
    error_code: Optional[ErrorCode]
    error_category: Optional[ErrorCategory]
    error_message: Optional[str]
    retryable: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class _ChildPlan:
    descriptor: ChildDescriptor
    node_parts: tuple[str, ...]
    parent_parts: tuple[str, ...]
    relative_depth: int
    archive_member: bool


_ARCHIVE_FORMATS = frozenset(
    {NodeFormat.ZIP, NodeFormat.SEVEN_Z, NodeFormat.RAR}
)


class NodeExecutor:
    """Execute one new or explicitly interrupted Node in a running Job."""

    def __init__(
        self,
        *,
        database: ProjectDatabaseProvider,
        source_inspector: SourceInspector,
        handlers: ContainerHandlerRegistry,
        artifact_store: ArtifactStore,
        clock: Clock = _utc_now,
        id_generator: IdGenerator = _new_id,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._database = database
        self._source_inspector = source_inspector
        self._handlers = handlers
        self._artifact_store = artifact_store
        self._clock = clock
        self._new_id = id_generator
        self._logger = logger or logging.getLogger(__name__)

    def execute(self, request: ExecuteNodeRequest) -> ExecuteNodeResult:
        context = self._load_context(
            Path(request.database_path), request.project_id, request.node_id
        )
        if context.node.status not in {
            NodeProcessingStatus.DISCOVERED,
            NodeProcessingStatus.INTERRUPTED,
        }:
            raise ApplicationError(
                code="NODE_NOT_PROCESSABLE",
                message="NodeExecutor accepts only DISCOVERED or INTERRUPTED Nodes",
                details={"node_id": context.node.id, "status": context.node.status.value},
            )
        attempt_id = self._new_id()
        self._queue_and_start_attempt(context, request, attempt_id)

        try:
            observation = self._verify_input(context, request, attempt_id)
        except ApplicationError as exc:
            return self._finish_input_failure(context, request, attempt_id, exc)
        except Exception as exc:
            technical_reference = self._new_id()
            self._logger.exception(
                "unexpected input verification failure [%s]", technical_reference
            )
            return self._finish_input_failure(
                context,
                request,
                attempt_id,
                ApplicationError(
                    code=ErrorCode.INTERNAL_ERROR.value,
                    message=f"unexpected input verification failure: {type(exc).__name__}",
                    details={"technical_reference": technical_reference},
                ),
            )

        detection = detect_node_format(
            context.node.original_name,
            observation.signature,
            is_directory=(context.node.kind == NodeKind.CONTAINER and context.node.format == NodeFormat.FOLDER),
        )
        if detection.kind == NodeKind.FILE:
            return self._finish_without_children(
                context=context,
                request=request,
                attempt_id=attempt_id,
                detection=detection,
                node_status=NodeProcessingStatus.SUCCESS,
            )

        handler = self._handlers.resolve(detection.format)
        if handler is None:
            return self._finish_without_children(
                context=context,
                request=request,
                attempt_id=attempt_id,
                detection=detection,
                node_status=NodeProcessingStatus.UNSUPPORTED,
                error=ProcessingError(
                    code=ErrorCode.UNSUPPORTED_FORMAT,
                    category=ErrorCategory.FORMAT,
                    stage=ProcessingStage.INSPECT_CONTAINER,
                    message=f"no Handler is available for {detection.format.value}",
                    retryable=False,
                ),
            )

        try:
            project_path = Path(request.database_path).resolve(strict=True).parent
            with self._artifact_store.begin(project_path, attempt_id) as artifact_session:
                inspection = handler.inspect(observation.path, request.policy)
                descriptors = inspection.children
                plans = self._plan_children(handler, descriptors)
                with self._database.unit_of_work(request.database_path) as uow:
                    existing_nodes = uow.catalog.node_count_for_project(context.project.id)
                if existing_nodes + len(plans) > request.policy.max_node_count:
                    raise HandlerOutcomeError(
                        status=NodeProcessingStatus.LIMIT_EXCEEDED,
                        code=ErrorCode.MAX_NODE_COUNT_EXCEEDED,
                        category=ErrorCategory.RESOURCE_LIMIT,
                        message="Project node count would exceed the configured limit",
                    )
                records = self._materialize_children(
                    context=context,
                    handler=handler,
                    plans=plans,
                    source_path=observation.path,
                    artifact_session=artifact_session,
                    request=request,
                )
                return self._persist_container_result(
                    context=context,
                    request=request,
                    attempt_id=attempt_id,
                    detection=detection,
                    handler=handler,
                    records=records,
                    metadata=inspection.metadata,
                    inspection_details=inspection.details,
                    artifact_session=artifact_session,
                )
        except HandlerOutcomeError as exc:
            return self._finish_without_children(
                context=context,
                request=request,
                attempt_id=attempt_id,
                detection=detection,
                node_status=exc.status,
                handler=handler,
                error=ProcessingError(
                    code=exc.code,
                    category=exc.category,
                    stage=ProcessingStage.INSPECT_CONTAINER,
                    message=exc.message,
                    retryable=exc.retryable,
                ),
            )
        except Exception as exc:
            technical_reference = self._new_id()
            self._logger.exception(
                "unexpected node processing failure [%s]", technical_reference
            )
            return self._finish_without_children(
                context=context,
                request=request,
                attempt_id=attempt_id,
                detection=detection,
                node_status=NodeProcessingStatus.FAILED,
                handler=handler,
                attempt_status=AttemptStatus.FAILED,
                error=ProcessingError(
                    code=ErrorCode.INTERNAL_ERROR,
                    category=ErrorCategory.INTERNAL,
                    stage=ProcessingStage.INSPECT_CONTAINER,
                    message=f"unexpected processing failure: {type(exc).__name__}",
                    retryable=True,
                    technical_reference=technical_reference,
                ),
            )

    def _load_context(
        self, database_path: Path, project_id: str, node_id: str
    ) -> _Context:
        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            if database_path.resolve(strict=False).parent.as_uri() != project.workspace_locator:
                raise ApplicationError(
                    code="PROJECT_DATABASE_MISMATCH",
                    message="database path is outside the Project workspace",
                )
            node = uow.catalog.get_node(node_id)
            if node is None or node.project_id != project_id:
                raise EntityNotFoundError(f"node not found: {node_id}")
            source = uow.catalog.get_source(node.source_id)
            if source is None:
                raise EntityNotFoundError(f"source not found: {node.source_id}")
            artifacts = tuple(uow.catalog.artifacts_for_node(node.id))
            if len(artifacts) > 1:
                raise ApplicationError(
                    code="ARTIFACT_CARDINALITY_VIOLATION",
                    message="V1 processing expects at most one input Artifact per Node",
                    details={"node_id": node.id},
                )
            is_root = source.root_node_id == node.id
            external_parts = (
                external_source_parts(uow, source, node) if not is_root else ()
            )
        artifact = artifacts[0] if artifacts else None
        if node.kind == NodeKind.FILE and artifact is None:
            raise ApplicationError(
                code="ARTIFACT_REQUIRED",
                message="processable File Node must have one Artifact",
                details={"node_id": node.id},
            )
        return _Context(project, source, node, artifact, external_parts, is_root)

    def _queue_and_start_attempt(
        self, context: _Context, request: ExecuteNodeRequest, attempt_id: str
    ) -> None:
        queued_at = self._clock()
        with self._database.unit_of_work(request.database_path) as uow:
            attempt_number = uow.processing.next_attempt_number(context.node.id)
            uow.processing.add_attempt(
                ProcessingAttempt(
                    id=attempt_id,
                    project_id=context.project.id,
                    job_id=request.job_id,
                    node_id=context.node.id,
                    attempt_number=attempt_number,
                    status=AttemptStatus.QUEUED,
                    stage=ProcessingStage.DETECT_FORMAT,
                    queued_at=queued_at,
                )
            )
            previous_node_status = context.node.status
            require_node_transition(previous_node_status, NodeProcessingStatus.PENDING)
            uow.catalog.update_node_status(
                context.node.id,
                previous_node_status,
                NodeProcessingStatus.PENDING,
                queued_at,
            )
            if context.is_source_root:
                if context.source.status == SourceStatus.VERIFYING:
                    raise ApplicationError(
                        code="SOURCE_NOT_AVAILABLE",
                        message="Source root has unreconciled verification state",
                        details={"source_id": context.source.id, "status": context.source.status.value},
                    )
                require_source_transition(context.source.status, SourceStatus.VERIFYING)
                uow.catalog.update_source_status(
                    context.source.id,
                    context.source.status,
                    SourceStatus.VERIFYING,
                    None,
                )
                uow.processing.append_event(
                    self._event(
                        EventType.SOURCE_VERIFICATION_STARTED,
                        context,
                        request,
                        queued_at,
                        attempt_id,
                        previous=context.source.status.value,
                        new=SourceStatus.VERIFYING.value,
                    )
                )
            if context.artifact is not None:
                uow.catalog.update_artifact_integrity(
                    context.artifact.id,
                    context.artifact.integrity_status,
                    ArtifactIntegrityStatus.VERIFYING,
                    None,
                )
            uow.processing.append_event(
                self._event(
                    EventType.ATTEMPT_QUEUED,
                    context,
                    request,
                    queued_at,
                    attempt_id,
                    new=AttemptStatus.QUEUED.value,
                    details={"attempt_number": attempt_number},
                )
            )
            uow.processing.append_event(
                self._event(
                    EventType.NODE_QUEUED,
                    context,
                    request,
                    queued_at,
                    attempt_id,
                    previous=previous_node_status.value,
                    new=NodeProcessingStatus.PENDING.value,
                )
            )
            uow.commit()

        started_at = self._clock()
        with self._database.unit_of_work(request.database_path) as uow:
            require_attempt_transition(AttemptStatus.QUEUED, AttemptStatus.RUNNING)
            uow.processing.update_attempt_status(
                attempt_id,
                AttemptStatus.QUEUED,
                AttemptStatus.RUNNING,
                started_at=started_at,
            )
            require_node_transition(NodeProcessingStatus.PENDING, NodeProcessingStatus.PROCESSING)
            uow.catalog.update_node_status(
                context.node.id,
                NodeProcessingStatus.PENDING,
                NodeProcessingStatus.PROCESSING,
                started_at,
            )
            uow.processing.append_event(
                self._event(
                    EventType.ATTEMPT_STARTED,
                    context,
                    request,
                    started_at,
                    attempt_id,
                    previous=AttemptStatus.QUEUED.value,
                    new=AttemptStatus.RUNNING.value,
                )
            )
            uow.processing.append_event(
                self._event(
                    EventType.NODE_PROCESSING_STARTED,
                    context,
                    request,
                    started_at,
                    attempt_id,
                    previous=NodeProcessingStatus.PENDING.value,
                    new=NodeProcessingStatus.PROCESSING.value,
                )
            )
            uow.commit()

    def _verify_input(
        self, context: _Context, request: ExecuteNodeRequest, attempt_id: str
    ) -> _InputObservation:
        if context.is_source_root:
            observed = self._source_inspector.revalidate(context.source)
            result = _InputObservation(observed.path, observed.signature, observed.verified_at)
        elif context.artifact is not None and context.artifact.scope == ArtifactScope.PROJECT_WORKSPACE:
            observed_artifact = self._artifact_store.inspect(
                Path(request.database_path).resolve(strict=True).parent,
                context.artifact,
                chunk_size=request.policy.io_chunk_size,
            )
            result = _InputObservation(
                observed_artifact.path,
                observed_artifact.signature,
                observed_artifact.observed_at,
            )
        else:
            expected_kind = (
                SourceKind.FOLDER
                if context.node.format == NodeFormat.FOLDER
                else SourceKind.FILE
            )
            observed = self._source_inspector.inspect_descendant(
                context.source,
                context.external_parts,
                expected_kind,
                context.artifact,
            )
            result = _InputObservation(observed.path, observed.signature, observed.verified_at)
        self._finish_input_verification(context, request, attempt_id, result.observed_at)
        return result

    def _finish_input_verification(
        self,
        context: _Context,
        request: ExecuteNodeRequest,
        attempt_id: str,
        observed_at: datetime,
    ) -> None:
        with self._database.unit_of_work(request.database_path) as uow:
            if context.is_source_root:
                require_source_transition(SourceStatus.VERIFYING, SourceStatus.AVAILABLE)
                uow.catalog.update_source_status(
                    context.source.id,
                    SourceStatus.VERIFYING,
                    SourceStatus.AVAILABLE,
                    observed_at,
                )
                uow.processing.append_event(
                    self._event(
                        EventType.SOURCE_VERIFIED,
                        context,
                        request,
                        observed_at,
                        attempt_id,
                        previous=SourceStatus.VERIFYING.value,
                        new=SourceStatus.AVAILABLE.value,
                    )
                )
            if context.artifact is not None:
                uow.catalog.update_artifact_integrity(
                    context.artifact.id,
                    ArtifactIntegrityStatus.VERIFYING,
                    ArtifactIntegrityStatus.VERIFIED,
                    observed_at,
                )
                uow.processing.append_event(
                    self._event(
                        EventType.ARTIFACT_VERIFIED,
                        context,
                        request,
                        observed_at,
                        attempt_id,
                        previous=ArtifactIntegrityStatus.VERIFYING.value,
                        new=ArtifactIntegrityStatus.VERIFIED.value,
                    )
                )
            uow.commit()

    def _finish_input_failure(
        self,
        context: _Context,
        request: ExecuteNodeRequest,
        attempt_id: str,
        failure: ApplicationError,
    ) -> ExecuteNodeResult:
        mapping = {
            ErrorCode.SOURCE_NOT_FOUND.value: (
                NodeProcessingStatus.SOURCE_MISSING,
                ArtifactIntegrityStatus.MISSING,
                ErrorCode.SOURCE_NOT_FOUND,
                ErrorCategory.SOURCE,
            ),
            ErrorCode.SOURCE_FINGERPRINT_MISMATCH.value: (
                NodeProcessingStatus.SOURCE_CHANGED,
                ArtifactIntegrityStatus.MISMATCH,
                ErrorCode.SOURCE_FINGERPRINT_MISMATCH,
                ErrorCategory.SOURCE,
            ),
            "SOURCE_KIND_MISMATCH": (
                NodeProcessingStatus.SOURCE_CHANGED,
                ArtifactIntegrityStatus.MISMATCH,
                ErrorCode.SOURCE_FINGERPRINT_MISMATCH,
                ErrorCategory.SOURCE,
            ),
            "SOURCE_CHANGED_DURING_READ": (
                NodeProcessingStatus.SOURCE_CHANGED,
                ArtifactIntegrityStatus.MISMATCH,
                ErrorCode.SOURCE_FINGERPRINT_MISMATCH,
                ErrorCategory.SOURCE,
            ),
            ErrorCode.ARTIFACT_MISSING.value: (
                NodeProcessingStatus.FAILED,
                ArtifactIntegrityStatus.MISSING,
                ErrorCode.ARTIFACT_MISSING,
                ErrorCategory.INTEGRITY,
            ),
            ErrorCode.ARTIFACT_HASH_MISMATCH.value: (
                NodeProcessingStatus.FAILED,
                ArtifactIntegrityStatus.MISMATCH,
                ErrorCode.ARTIFACT_HASH_MISMATCH,
                ErrorCategory.INTEGRITY,
            ),
            ErrorCode.SYMLINK_BLOCKED.value: (
                NodeProcessingStatus.SECURITY_BLOCKED,
                ArtifactIntegrityStatus.UNREADABLE,
                ErrorCode.SYMLINK_BLOCKED,
                ErrorCategory.SECURITY,
            ),
            ErrorCode.PATH_TRAVERSAL_BLOCKED.value: (
                NodeProcessingStatus.SECURITY_BLOCKED,
                ArtifactIntegrityStatus.UNREADABLE,
                ErrorCode.PATH_TRAVERSAL_BLOCKED,
                ErrorCategory.SECURITY,
            ),
            ErrorCode.SOURCE_OUTSIDE_BOUNDARY.value: (
                NodeProcessingStatus.SECURITY_BLOCKED,
                ArtifactIntegrityStatus.UNREADABLE,
                ErrorCode.SOURCE_OUTSIDE_BOUNDARY,
                ErrorCategory.SECURITY,
            ),
        }
        node_status, artifact_status, code, category = mapping.get(
            failure.code,
            (
                NodeProcessingStatus.FAILED,
                ArtifactIntegrityStatus.UNREADABLE,
                ErrorCode.INTERNAL_ERROR,
                ErrorCategory.INTERNAL,
            ),
        )
        now = self._clock()
        error = ProcessingError(
            code=code,
            category=category,
            stage=(
                ProcessingStage.VERIFY_SOURCE
                if context.is_source_root or (context.artifact and context.artifact.scope == ArtifactScope.EXTERNAL_SOURCE)
                else ProcessingStage.VERIFY_ARTIFACT
            ),
            message=failure.message,
            retryable=category not in {ErrorCategory.SECURITY},
            technical_reference=(
                str(failure.details["technical_reference"])
                if "technical_reference" in failure.details
                else None
            ),
        )
        with self._database.unit_of_work(request.database_path) as uow:
            if context.is_source_root:
                source_status = (
                    SourceStatus.MISSING
                    if node_status == NodeProcessingStatus.SOURCE_MISSING
                    else SourceStatus.CHANGED
                    if node_status == NodeProcessingStatus.SOURCE_CHANGED
                    else SourceStatus.UNREADABLE
                )
                require_source_transition(SourceStatus.VERIFYING, source_status)
                uow.catalog.update_source_status(
                    context.source.id, SourceStatus.VERIFYING, source_status, now
                )
                source_event = (
                    EventType.SOURCE_MISSING_DETECTED
                    if source_status == SourceStatus.MISSING
                    else EventType.SOURCE_CHANGED_DETECTED
                    if source_status == SourceStatus.CHANGED
                    else EventType.NODE_PROCESSING_BLOCKED
                )
                uow.processing.append_event(
                    self._event(
                        source_event,
                        context,
                        request,
                        now,
                        attempt_id,
                        severity=EventSeverity.ERROR,
                        new=source_status.value,
                        error_code=code,
                    )
                )
            if context.artifact is not None:
                uow.catalog.update_artifact_integrity(
                    context.artifact.id,
                    ArtifactIntegrityStatus.VERIFYING,
                    artifact_status,
                    now,
                )
                uow.processing.append_event(
                    self._event(
                        EventType.ARTIFACT_INTEGRITY_FAILED,
                        context,
                        request,
                        now,
                        attempt_id,
                        severity=EventSeverity.ERROR,
                        previous=ArtifactIntegrityStatus.VERIFYING.value,
                        new=artifact_status.value,
                        error_code=code,
                    )
                )
            self._finish_lifecycle(
                uow,
                context,
                request,
                attempt_id,
                node_status=node_status,
                attempt_status=(
                    AttemptStatus.FAILED
                    if category == ErrorCategory.INTERNAL
                    else AttemptStatus.COMPLETED
                ),
                error=error,
                handler=None,
                finished_at=now,
            )
            uow.commit()
        warnings, errors = self._outcome_counts(node_status, error)
        return ExecuteNodeResult(
            node_id=context.node.id,
            attempt_id=attempt_id,
            node_status=node_status,
            child_node_ids=(),
            warning_count=warnings,
            error_count=errors,
            workspace_bytes=0,
        )

    @staticmethod
    def _plan_children(
        handler: ContainerHandler,
        descriptors: Sequence[ChildDescriptor],
    ) -> tuple[_ChildPlan, ...]:
        if handler.format not in _ARCHIVE_FORMATS:
            return tuple(
                _ChildPlan(
                    descriptor=descriptor,
                    node_parts=(),
                    parent_parts=(),
                    relative_depth=1,
                    archive_member=(
                        handler.format in {NodeFormat.MSG, NodeFormat.EML}
                    ),
                )
                for descriptor in descriptors
            )

        explicit_directories = {
            descriptor.safe_parts: descriptor
            for descriptor in descriptors
            if descriptor.is_directory and descriptor.safe_parts
        }
        first_ordinals: dict[tuple[str, ...], int] = {}
        for descriptor in descriptors:
            if not descriptor.safe_parts:
                continue
            directory_depth = (
                len(descriptor.safe_parts)
                if descriptor.is_directory
                else len(descriptor.safe_parts) - 1
            )
            for length in range(1, directory_depth + 1):
                parts = descriptor.safe_parts[:length]
                first_ordinals[parts] = min(
                    first_ordinals.get(parts, descriptor.ordinal),
                    descriptor.ordinal,
                )

        plans: list[_ChildPlan] = []
        for parts in sorted(
            first_ordinals,
            key=lambda value: (len(value), first_ordinals[value], value),
        ):
            explicit = explicit_directories.get(parts)
            digest = hashlib.sha256(
                "\x00".join(parts).encode("utf-8")
            ).hexdigest()
            directory = ChildDescriptor(
                ordinal=first_ordinals[parts],
                discovery_key=f"archive-directory:{digest}",
                original_name=parts[-1],
                safe_parts=parts,
                is_directory=True,
                declared_size=None if explicit is None else explicit.declared_size,
                token=None if explicit is None else explicit.token,
                blocked_status=(
                    None if explicit is None else explicit.blocked_status
                ),
                error_code=None if explicit is None else explicit.error_code,
                error_category=(
                    None if explicit is None else explicit.error_category
                ),
            )
            plans.append(
                _ChildPlan(
                    descriptor=directory,
                    node_parts=parts,
                    parent_parts=parts[:-1],
                    relative_depth=len(parts),
                    archive_member=True,
                )
            )

        for descriptor in descriptors:
            if descriptor.is_directory and descriptor.safe_parts:
                continue
            node_parts = descriptor.safe_parts
            plans.append(
                _ChildPlan(
                    descriptor=descriptor,
                    node_parts=node_parts,
                    parent_parts=(node_parts[:-1] if node_parts else ()),
                    relative_depth=(len(node_parts) if node_parts else 1),
                    archive_member=True,
                )
            )
        return tuple(plans)

    def _materialize_children(
        self,
        *,
        context: _Context,
        handler: ContainerHandler,
        plans: Sequence[_ChildPlan],
        source_path: Path,
        artifact_session: ArtifactWriteSession,
        request: ExecuteNodeRequest,
    ) -> list[_ChildRecord]:
        records: list[_ChildRecord] = []
        directory_ids: dict[tuple[str, ...], str] = {}
        for plan in plans:
            descriptor = plan.descriptor
            child_depth = context.node.depth + plan.relative_depth
            node_id = self._new_id()
            status = descriptor.blocked_status or NodeProcessingStatus.DISCOVERED
            error_code = descriptor.error_code
            error_category = descriptor.error_category
            error_message = None if error_code is None else f"child blocked by policy: {error_code.value}"
            retryable = False
            if child_depth > request.policy.max_depth and status == NodeProcessingStatus.DISCOVERED:
                status = NodeProcessingStatus.LIMIT_EXCEEDED
                error_code = ErrorCode.MAX_DEPTH_EXCEEDED
                error_category = ErrorCategory.RESOURCE_LIMIT
                error_message = "child depth exceeds the configured limit"

            artifact_id = (
                self._new_id()
                if not descriptor.is_directory and status == NodeProcessingStatus.DISCOVERED
                else None
            )
            materialization: Optional[ChildMaterialization] = None
            if artifact_id is not None:
                try:
                    materialization = handler.materialize(
                        source_path,
                        descriptor,
                        artifact_id,
                        artifact_session,
                        request.policy,
                        self._clock(),
                    )
                except HandlerOutcomeError as exc:
                    status = exc.status
                    error_code = exc.code
                    error_category = exc.category
                    error_message = exc.message
                    retryable = exc.retryable
                    artifact_id = None
            detection = detect_node_format(
                descriptor.original_name,
                b"" if materialization is None else materialization.signature,
                is_directory=descriptor.is_directory,
            )
            if (
                descriptor.is_directory
                and handler.format in _ARCHIVE_FORMATS
                and status == NodeProcessingStatus.DISCOVERED
            ):
                status = NodeProcessingStatus.SUCCESS
            if plan.archive_member:
                logical_path = (
                    archive_child_path(context.node.logical_path, plan.node_parts)
                    if plan.node_parts
                    else blocked_archive_child_path(
                        context.node.logical_path, descriptor.original_name
                    )
                )
                display_base = (
                    plan.node_parts[-1]
                    if plan.node_parts
                    else descriptor.original_name.rstrip("/\\")
                    .replace("\\", "/")
                    .split("/")[-1]
                )
            else:
                logical_path = folder_child_path(context.node.logical_path, descriptor.original_name)
                display_base = descriptor.original_name
            now = self._clock()
            node = Node(
                id=node_id,
                project_id=context.project.id,
                source_id=context.source.id,
                kind=detection.kind,
                format=detection.format,
                original_name=descriptor.original_name,
                display_name=safe_display_name(display_base),
                logical_path=logical_path,
                depth=child_depth,
                media_type=descriptor.media_type,
                declared_size=descriptor.declared_size,
                status=status,
                detection_method=detection.method,
                detection_confidence=detection.confidence,
                detection_details=detection.details,
                discovery_key=descriptor.discovery_key,
                created_at=now,
                updated_at=now,
            )
            parent_node_id = (
                context.node.id
                if not plan.parent_parts
                else directory_ids[plan.parent_parts]
            )
            relationship_type = (
                RelationshipType.FOLDER_CONTAINS
                if plan.parent_parts
                else descriptor.relationship_type or handler.relationship_type
            )
            relationship = NodeRelationship(
                id=self._new_id(),
                project_id=context.project.id,
                parent_node_id=parent_node_id,
                child_node_id=node.id,
                type=relationship_type,
                ordinal=descriptor.ordinal,
                discovery_key=descriptor.discovery_key,
                created_by_job_id=request.job_id,
                created_at=now,
            )
            artifact = None
            if artifact_id is not None and materialization is not None:
                artifact = Artifact(
                    id=artifact_id,
                    project_id=context.project.id,
                    node_id=node.id,
                    role=materialization.role,
                    scope=materialization.scope,
                    locator=materialization.locator,
                    size=materialization.size,
                    sha256=materialization.sha256,
                    integrity_status=ArtifactIntegrityStatus.VERIFIED,
                    observed_at=materialization.observed_at,
                    created_at=now,
                )
            records.append(
                _ChildRecord(
                    node,
                    relationship,
                    artifact,
                    error_code,
                    error_category,
                    error_message,
                    retryable,
                )
            )
            if descriptor.is_directory and plan.node_parts:
                directory_ids[plan.node_parts] = node.id
        return records

    def _persist_container_result(
        self,
        *,
        context: _Context,
        request: ExecuteNodeRequest,
        attempt_id: str,
        detection: DetectionResult,
        handler: ContainerHandler,
        records: Sequence[_ChildRecord],
        metadata: Sequence[MetadataDescriptor],
        inspection_details: Mapping[str, object],
        artifact_session: ArtifactWriteSession,
    ) -> ExecuteNodeResult:
        error_count = sum(
            record.node.status in {NodeProcessingStatus.FAILED, NodeProcessingStatus.CORRUPTED}
            for record in records
        )
        warning_count = sum(
            record.error_code is not None
            and record.node.status not in {NodeProcessingStatus.FAILED, NodeProcessingStatus.CORRUPTED}
            for record in records
        )
        node_status = (
            NodeProcessingStatus.PARTIAL_SUCCESS
            if warning_count or error_count
            else NodeProcessingStatus.SUCCESS
        )
        workspace_bytes = sum(
            (record.artifact.size or 0)
            for record in records
            if record.artifact is not None and record.artifact.scope == ArtifactScope.PROJECT_WORKSPACE
        )
        finished_at = self._clock()
        with self._database.unit_of_work(request.database_path) as uow:
            self._persist_detection(uow, context, request, attempt_id, detection, finished_at)
            for descriptor in metadata:
                uow.catalog.add_metadata(
                    NodeMetadata(
                        id=self._new_id(),
                        project_id=context.project.id,
                        node_id=context.node.id,
                        namespace=descriptor.namespace,
                        key=descriptor.key,
                        value_type=descriptor.value_type,
                        provenance=descriptor.provenance,
                        value_text=descriptor.value_text,
                        value_integer=descriptor.value_integer,
                        value_real=descriptor.value_real,
                        value_boolean=descriptor.value_boolean,
                        value_datetime=descriptor.value_datetime,
                        value_json=descriptor.value_json,
                        observed_at=finished_at,
                        created_at=finished_at,
                    )
                )
            uow.processing.append_event(
                self._event(
                    EventType.CONTAINER_OPENED,
                    context,
                    request,
                    finished_at,
                    attempt_id,
                    details={
                        "handler": handler.name,
                        "child_count": len(records),
                        "metadata_count": len(metadata),
                        "inspection": dict(inspection_details),
                    },
                )
            )
            for record in records:
                uow.catalog.register_child(record.node, record.relationship)
                uow.processing.append_event(
                    self._event(
                        EventType.CHILD_DISCOVERED,
                        context,
                        request,
                        record.node.created_at,
                        attempt_id,
                        node_id=record.node.id,
                        new=record.node.status.value,
                        details={"logical_path": record.node.logical_path, "ordinal": record.relationship.ordinal},
                    )
                )
                uow.processing.append_event(
                    self._event(
                        EventType.RELATIONSHIP_CREATED,
                        context,
                        request,
                        record.relationship.created_at,
                        attempt_id,
                        node_id=record.node.id,
                        details={
                            "parent_node_id": record.relationship.parent_node_id,
                            "type": record.relationship.type.value,
                        },
                    )
                )
                uow.processing.append_event(
                    self._event(
                        EventType.LINEAGE_UPDATED,
                        context,
                        request,
                        record.relationship.created_at,
                        attempt_id,
                        node_id=record.node.id,
                        details={
                            "parent_node_id": record.relationship.parent_node_id
                        },
                    )
                )
                if record.artifact is not None:
                    uow.catalog.add_artifact(record.artifact)
                    uow.processing.append_event(
                        self._event(
                            EventType.ARTIFACT_REGISTERED,
                            context,
                            request,
                            record.artifact.created_at,
                            attempt_id,
                            node_id=record.node.id,
                            new=ArtifactIntegrityStatus.VERIFIED.value,
                            details={"artifact_id": record.artifact.id, "scope": record.artifact.scope.value},
                        )
                    )
                    if record.artifact.scope == ArtifactScope.PROJECT_WORKSPACE:
                        uow.processing.append_event(
                            self._event(
                                EventType.CHILD_EXTRACTED,
                                context,
                                request,
                                record.artifact.created_at,
                                attempt_id,
                                node_id=record.node.id,
                                details={"artifact_id": record.artifact.id, "storage_key": record.artifact.locator},
                            )
                        )
                if record.error_code is not None:
                    uow.processing.append_event(
                        self._event(
                            EventType.NODE_PROCESSING_BLOCKED,
                            context,
                            request,
                            record.node.created_at,
                            attempt_id,
                            node_id=record.node.id,
                            severity=EventSeverity.WARNING,
                            new=record.node.status.value,
                            error_code=record.error_code,
                            details={
                                "handler": handler.name,
                                "stage": ProcessingStage.EXTRACT_CHILD.value,
                                "category": None if record.error_category is None else record.error_category.value,
                                "message": record.error_message,
                                "retryable": record.retryable,
                            },
                        )
                    )
            self._finish_lifecycle(
                uow,
                context,
                request,
                attempt_id,
                node_status=node_status,
                attempt_status=AttemptStatus.COMPLETED,
                error=None,
                handler=handler,
                finished_at=finished_at,
            )
            artifact_session.publish()
            uow.commit()
            artifact_session.complete()
        return ExecuteNodeResult(
            node_id=context.node.id,
            attempt_id=attempt_id,
            node_status=node_status,
            child_node_ids=tuple(record.node.id for record in records),
            warning_count=warning_count,
            error_count=error_count,
            workspace_bytes=workspace_bytes,
        )

    def _finish_without_children(
        self,
        *,
        context: _Context,
        request: ExecuteNodeRequest,
        attempt_id: str,
        detection: DetectionResult,
        node_status: NodeProcessingStatus,
        handler: Optional[ContainerHandler] = None,
        attempt_status: AttemptStatus = AttemptStatus.COMPLETED,
        error: Optional[ProcessingError] = None,
    ) -> ExecuteNodeResult:
        now = self._clock()
        with self._database.unit_of_work(request.database_path) as uow:
            self._persist_detection(uow, context, request, attempt_id, detection, now)
            self._finish_lifecycle(
                uow,
                context,
                request,
                attempt_id,
                node_status=node_status,
                attempt_status=attempt_status,
                error=error,
                handler=handler,
                finished_at=now,
            )
            uow.commit()
        warnings, errors = self._outcome_counts(node_status, error)
        return ExecuteNodeResult(
            node_id=context.node.id,
            attempt_id=attempt_id,
            node_status=node_status,
            child_node_ids=(),
            warning_count=warnings,
            error_count=errors,
            workspace_bytes=0,
        )

    def _persist_detection(
        self,
        uow: UnitOfWork,
        context: _Context,
        request: ExecuteNodeRequest,
        attempt_id: str,
        detection: DetectionResult,
        occurred_at: datetime,
    ) -> None:
        uow.catalog.update_node_detection(
            context.node.id,
            kind=detection.kind,
            format=detection.format,
            method=detection.method,
            confidence=detection.confidence,
            details=detection.details,
            updated_at=occurred_at,
        )
        uow.processing.append_event(
            self._event(
                EventType.NODE_FORMAT_DETECTED,
                context,
                request,
                occurred_at,
                attempt_id,
                details={"format": detection.format.value, "method": detection.method},
            )
        )

    def _finish_lifecycle(
        self,
        uow: UnitOfWork,
        context: _Context,
        request: ExecuteNodeRequest,
        attempt_id: str,
        *,
        node_status: NodeProcessingStatus,
        attempt_status: AttemptStatus,
        error: Optional[ProcessingError],
        handler: Optional[ContainerHandler],
        finished_at: datetime,
    ) -> None:
        require_node_transition(NodeProcessingStatus.PROCESSING, node_status)
        uow.catalog.update_node_status(
            context.node.id,
            NodeProcessingStatus.PROCESSING,
            node_status,
            finished_at,
        )
        require_attempt_transition(AttemptStatus.RUNNING, attempt_status)
        uow.processing.update_attempt_status(
            attempt_id,
            AttemptStatus.RUNNING,
            attempt_status,
            handler_name=None if handler is None else handler.name,
            handler_version=None if handler is None else handler.version,
            stage=(
                error.stage
                if error is not None
                else ProcessingStage.INSPECT_CONTAINER
                if handler is not None
                else ProcessingStage.DETECT_FORMAT
            ),
            finished_at=finished_at,
            error=error,
        )
        node_event = EventType.NODE_PROCESSING_FINISHED
        severity = EventSeverity.INFO
        if node_status in {NodeProcessingStatus.FAILED, NodeProcessingStatus.CORRUPTED}:
            node_event = EventType.NODE_PROCESSING_FAILED
            severity = EventSeverity.ERROR
        elif node_status not in {NodeProcessingStatus.SUCCESS, NodeProcessingStatus.PARTIAL_SUCCESS}:
            node_event = EventType.NODE_PROCESSING_BLOCKED
            severity = EventSeverity.WARNING
        uow.processing.append_event(
            self._event(
                node_event,
                context,
                request,
                finished_at,
                attempt_id,
                severity=severity,
                previous=NodeProcessingStatus.PROCESSING.value,
                new=node_status.value,
                error_code=None if error is None else error.code,
            )
        )
        uow.processing.append_event(
            self._event(
                EventType.ATTEMPT_FAILED if attempt_status == AttemptStatus.FAILED else EventType.ATTEMPT_FINISHED,
                context,
                request,
                finished_at,
                attempt_id,
                severity=severity,
                previous=AttemptStatus.RUNNING.value,
                new=attempt_status.value,
                error_code=None if error is None else error.code,
            )
        )

    def _event(
        self,
        event_type: EventType,
        context: _Context,
        request: ExecuteNodeRequest,
        occurred_at: datetime,
        attempt_id: str,
        *,
        node_id: Optional[str] = None,
        severity: EventSeverity = EventSeverity.INFO,
        previous: Optional[str] = None,
        new: Optional[str] = None,
        error_code: Optional[ErrorCode] = None,
        details: Optional[dict[str, object]] = None,
    ) -> ProcessingEvent:
        return ProcessingEvent(
            id=self._new_id(),
            event_type=event_type,
            project_id=context.project.id,
            source_id=context.source.id,
            node_id=node_id or context.node.id,
            job_id=request.job_id,
            attempt_id=attempt_id,
            actor=request.actor,
            occurred_at=occurred_at,
            severity=severity,
            previous_status=previous,
            new_status=new,
            error_code=error_code,
            details=details or {},
            correlation_id=request.correlation_id,
        )

    @staticmethod
    def _outcome_counts(
        status: NodeProcessingStatus, error: Optional[ProcessingError]
    ) -> tuple[int, int]:
        if error is None:
            return 0, 0
        if status in {NodeProcessingStatus.FAILED, NodeProcessingStatus.CORRUPTED}:
            return 0, 1
        return 1, 0
