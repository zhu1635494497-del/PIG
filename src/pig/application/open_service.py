from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from pig.application.contracts import OpenNodeRequest, OpenNodeResult
from pig.application.errors import ApplicationError
from pig.application.evidence import external_source_parts
from pig.application.ports import (
    FileOpener,
    OpenHandoffStore,
    ProjectDatabaseProvider,
    SourceInspector,
)
from pig.domain.entities import Artifact, Node, ProcessingEvent, Project, Source
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    ArtifactScope,
    ErrorCode,
    EventSeverity,
    EventType,
    SourceKind,
    SourceStatus,
)
from pig.domain.exceptions import EntityNotFoundError
from pig.domain.open_policy import OpenPolicy
from pig.domain.transitions import require_source_transition
from pig.handlers.base import ArtifactStore


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


@dataclass(frozen=True, slots=True, kw_only=True)
class _OpenContext:
    project: Project
    source: Source
    node: Node
    artifact: Artifact | None
    artifact_count: int
    external_parts: tuple[str, ...]
    is_source_root: bool


class OpenNodeService:
    """Authorize, revalidate, audit, and hand one Node to the host OS."""

    def __init__(
        self,
        *,
        database: ProjectDatabaseProvider,
        source_inspector: SourceInspector,
        artifact_store: ArtifactStore,
        handoff_store: OpenHandoffStore,
        opener: FileOpener,
        policy: OpenPolicy = OpenPolicy(),
        clock: Clock = _utc_now,
        id_generator: IdGenerator = _new_id,
        logger: logging.Logger | None = None,
    ) -> None:
        self._database = database
        self._source_inspector = source_inspector
        self._artifact_store = artifact_store
        self._handoff_store = handoff_store
        self._opener = opener
        self._policy = policy
        self._clock = clock
        self._new_id = id_generator
        self._logger = logger or logging.getLogger(__name__)

    def execute(self, request: OpenNodeRequest) -> OpenNodeResult:
        project_id = self._required_text(request.project_id, "project_id")
        node_id = self._required_text(request.node_id, "node_id")
        actor = self._required_text(request.actor, "actor")
        database_path = Path(request.database_path)
        if not database_path.is_absolute():
            raise ApplicationError(
                code="INVALID_REQUEST",
                message="database_path must be absolute",
                details={"field": "database_path"},
            )
        context = self._load_context(database_path, project_id, node_id)
        correlation_id = self._new_id()

        if context.node.format not in self._policy.allowed_formats:
            failure = ApplicationError(
                code=ErrorCode.OPEN_FORMAT_DENIED.value,
                message="Node format is not allowed for direct opening",
                details={
                    "node_id": node_id,
                    "format": context.node.format.value,
                },
            )
            self._record_immediate_denial(
                database_path, context, actor, correlation_id, failure
            )
            raise failure
        if context.artifact_count != 1 or context.artifact is None:
            failure = ApplicationError(
                code=ErrorCode.OPEN_INTEGRITY_REQUIRED.value,
                message="Node does not have exactly one verifiable Artifact",
                details={"node_id": node_id},
            )
            self._record_immediate_denial(
                database_path, context, actor, correlation_id, failure
            )
            raise failure

        self._begin_verification(
            database_path, context, actor, correlation_id
        )
        try:
            verified_path = self._verify(database_path, context)
        except ApplicationError as failure:
            self._finish_verification_failure(
                database_path, context, actor, correlation_id, failure
            )
            raise
        except Exception as exc:
            technical_reference = self._new_id()
            self._logger.exception(
                "unexpected open verification failure [%s]", technical_reference
            )
            failure = ApplicationError(
                code=ErrorCode.OPEN_INTEGRITY_REQUIRED.value,
                message="Node Artifact could not be verified for opening",
                details={"technical_reference": technical_reference},
            )
            self._finish_verification_failure(
                database_path, context, actor, correlation_id, failure
            )
            raise failure from exc

        self._finish_verification_success(
            database_path, context, actor, correlation_id
        )
        open_path = verified_path
        try:
            if context.artifact.scope == ArtifactScope.PROJECT_WORKSPACE:
                open_path = self._handoff_store.prepare(
                    database_path.resolve(strict=True).parent,
                    context.artifact,
                    context.node.format,
                    verified_path,
                )
            self._opener.open(open_path)
        except Exception as exc:
            technical_reference = self._new_id()
            self._logger.exception(
                "host open handoff failed [%s]", technical_reference
            )
            failure = ApplicationError(
                code=ErrorCode.OPEN_HANDOFF_FAILED.value,
                message="the host operating system rejected the open request",
                details={"technical_reference": technical_reference},
            )
            self._record_open_terminal(
                database_path=database_path,
                context=context,
                actor=actor,
                correlation_id=correlation_id,
                event_type=EventType.FILE_OPEN_FAILED,
                severity=EventSeverity.ERROR,
                error_code=ErrorCode.OPEN_HANDOFF_FAILED,
                details={"technical_reference": technical_reference},
            )
            raise failure from exc

        handed_off_at = self._clock()
        self._record_open_terminal(
            database_path=database_path,
            context=context,
            actor=actor,
            correlation_id=correlation_id,
            event_type=EventType.FILE_OPENED,
            severity=EventSeverity.INFO,
            details={
                "handed_off_at": handed_off_at.isoformat(),
                "typed_handoff_copy": open_path != verified_path,
            },
            occurred_at=handed_off_at,
        )
        return OpenNodeResult(
            project_id=project_id,
            node_id=node_id,
            artifact_id=context.artifact.id,
            format=context.node.format,
            path=open_path,
            handed_off_at=handed_off_at,
        )

    def _load_context(
        self, database_path: Path, project_id: str, node_id: str
    ) -> _OpenContext:
        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            if (
                database_path.resolve(strict=False).parent.as_uri()
                != project.workspace_locator
            ):
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
            is_source_root = source.root_node_id == node.id
            parts = (
                external_source_parts(uow, source, node)
                if not is_source_root
                else ()
            )
        return _OpenContext(
            project=project,
            source=source,
            node=node,
            artifact=artifacts[0] if len(artifacts) == 1 else None,
            artifact_count=len(artifacts),
            external_parts=parts,
            is_source_root=is_source_root,
        )

    def _begin_verification(
        self,
        database_path: Path,
        context: _OpenContext,
        actor: str,
        correlation_id: str,
    ) -> None:
        assert context.artifact is not None
        requested_at = self._clock()
        with self._database.unit_of_work(database_path) as uow:
            uow.processing.append_event(
                self._event(
                    context,
                    actor,
                    correlation_id,
                    EventType.FILE_OPEN_REQUESTED,
                    EventSeverity.INFO,
                    requested_at,
                )
            )
            if context.is_source_root:
                verifying_at = self._clock()
                require_source_transition(
                    context.source.status, SourceStatus.VERIFYING
                )
                uow.catalog.update_source_status(
                    context.source.id,
                    context.source.status,
                    SourceStatus.VERIFYING,
                    None,
                )
                uow.processing.append_event(
                    self._event(
                        context,
                        actor,
                        correlation_id,
                        EventType.SOURCE_VERIFICATION_STARTED,
                        EventSeverity.INFO,
                        verifying_at,
                        previous_status=context.source.status.value,
                        new_status=SourceStatus.VERIFYING.value,
                    )
                )
            uow.catalog.update_artifact_integrity(
                context.artifact.id,
                context.artifact.integrity_status,
                ArtifactIntegrityStatus.VERIFYING,
                None,
            )
            uow.commit()

    def _verify(self, database_path: Path, context: _OpenContext) -> Path:
        artifact = context.artifact
        assert artifact is not None
        if artifact.scope == ArtifactScope.PROJECT_WORKSPACE:
            observation = self._artifact_store.inspect(
                database_path.resolve(strict=True).parent,
                artifact,
                chunk_size=self._policy.verification_chunk_size,
            )
            return observation.path
        if artifact.scope != ArtifactScope.EXTERNAL_SOURCE:
            raise ApplicationError(
                code=ErrorCode.OPEN_INTEGRITY_REQUIRED.value,
                message="Artifact scope is not openable",
            )
        if context.is_source_root:
            observation = self._source_inspector.revalidate(context.source)
            if (
                observation.locator != artifact.locator
                or observation.size != artifact.size
                or observation.sha256 != artifact.sha256
            ):
                raise ApplicationError(
                    code=ErrorCode.SOURCE_FINGERPRINT_MISMATCH.value,
                    message="Source and Artifact fingerprints do not match",
                    details={"artifact_id": artifact.id},
                )
            return observation.path
        observation = self._source_inspector.inspect_descendant(
            context.source,
            context.external_parts,
            SourceKind.FILE,
            artifact,
        )
        return observation.path

    def _finish_verification_success(
        self,
        database_path: Path,
        context: _OpenContext,
        actor: str,
        correlation_id: str,
    ) -> None:
        assert context.artifact is not None
        occurred_at = self._clock()
        with self._database.unit_of_work(database_path) as uow:
            if context.is_source_root:
                require_source_transition(
                    SourceStatus.VERIFYING, SourceStatus.AVAILABLE
                )
                uow.catalog.update_source_status(
                    context.source.id,
                    SourceStatus.VERIFYING,
                    SourceStatus.AVAILABLE,
                    occurred_at,
                )
                uow.processing.append_event(
                    self._event(
                        context,
                        actor,
                        correlation_id,
                        EventType.SOURCE_VERIFIED,
                        EventSeverity.INFO,
                        occurred_at,
                        previous_status=SourceStatus.VERIFYING.value,
                        new_status=SourceStatus.AVAILABLE.value,
                    )
                )
            uow.catalog.update_artifact_integrity(
                context.artifact.id,
                ArtifactIntegrityStatus.VERIFYING,
                ArtifactIntegrityStatus.VERIFIED,
                occurred_at,
            )
            uow.processing.append_event(
                self._event(
                    context,
                    actor,
                    correlation_id,
                    EventType.ARTIFACT_VERIFIED,
                    EventSeverity.INFO,
                    occurred_at,
                    previous_status=ArtifactIntegrityStatus.VERIFYING.value,
                    new_status=ArtifactIntegrityStatus.VERIFIED.value,
                )
            )
            uow.commit()

    def _finish_verification_failure(
        self,
        database_path: Path,
        context: _OpenContext,
        actor: str,
        correlation_id: str,
        failure: ApplicationError,
    ) -> None:
        assert context.artifact is not None
        error_code = self._verification_error_code(failure.code)
        artifact_status = self._artifact_failure_status(error_code)
        occurred_at = self._clock()
        with self._database.unit_of_work(database_path) as uow:
            if context.is_source_root:
                source_status = self._source_failure_status(error_code)
                require_source_transition(SourceStatus.VERIFYING, source_status)
                uow.catalog.update_source_status(
                    context.source.id,
                    SourceStatus.VERIFYING,
                    source_status,
                    occurred_at,
                )
                source_event = {
                    SourceStatus.MISSING: EventType.SOURCE_MISSING_DETECTED,
                    SourceStatus.CHANGED: EventType.SOURCE_CHANGED_DETECTED,
                    SourceStatus.UNREADABLE: EventType.SOURCE_UNREADABLE_DETECTED,
                }[source_status]
                uow.processing.append_event(
                    self._event(
                        context,
                        actor,
                        correlation_id,
                        source_event,
                        EventSeverity.WARNING,
                        occurred_at,
                        error_code=error_code,
                        previous_status=SourceStatus.VERIFYING.value,
                        new_status=source_status.value,
                    )
                )
            uow.catalog.update_artifact_integrity(
                context.artifact.id,
                ArtifactIntegrityStatus.VERIFYING,
                artifact_status,
                occurred_at,
            )
            uow.processing.append_event(
                self._event(
                    context,
                    actor,
                    correlation_id,
                    EventType.ARTIFACT_INTEGRITY_FAILED,
                    EventSeverity.WARNING,
                    occurred_at,
                    error_code=error_code,
                    previous_status=ArtifactIntegrityStatus.VERIFYING.value,
                    new_status=artifact_status.value,
                )
            )
            uow.processing.append_event(
                self._event(
                    context,
                    actor,
                    correlation_id,
                    EventType.FILE_OPEN_DENIED,
                    EventSeverity.WARNING,
                    occurred_at,
                    error_code=error_code,
                    details={"reason": failure.code},
                )
            )
            uow.commit()

    def _record_immediate_denial(
        self,
        database_path: Path,
        context: _OpenContext,
        actor: str,
        correlation_id: str,
        failure: ApplicationError,
    ) -> None:
        error_code = ErrorCode(failure.code)
        requested_at = self._clock()
        with self._database.unit_of_work(database_path) as uow:
            uow.processing.append_event(
                self._event(
                    context,
                    actor,
                    correlation_id,
                    EventType.FILE_OPEN_REQUESTED,
                    EventSeverity.INFO,
                    requested_at,
                )
            )
            denied_at = self._clock()
            uow.processing.append_event(
                self._event(
                    context,
                    actor,
                    correlation_id,
                    EventType.FILE_OPEN_DENIED,
                    EventSeverity.WARNING,
                    denied_at,
                    error_code=error_code,
                    details={"reason": failure.code},
                )
            )
            uow.commit()

    def _record_open_terminal(
        self,
        *,
        database_path: Path,
        context: _OpenContext,
        actor: str,
        correlation_id: str,
        event_type: EventType,
        severity: EventSeverity,
        details: dict[str, object],
        error_code: ErrorCode | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        with self._database.unit_of_work(database_path) as uow:
            uow.processing.append_event(
                self._event(
                    context,
                    actor,
                    correlation_id,
                    event_type,
                    severity,
                    occurred_at or self._clock(),
                    error_code=error_code,
                    details=details,
                )
            )
            uow.commit()

    @staticmethod
    def _verification_error_code(code: str) -> ErrorCode:
        mapping = {
            "SOURCE_KIND_MISMATCH": ErrorCode.SOURCE_FINGERPRINT_MISMATCH,
            "SOURCE_CHANGED_DURING_READ": ErrorCode.SOURCE_FINGERPRINT_MISMATCH,
            "SOURCE_UNREADABLE": ErrorCode.OPEN_INTEGRITY_REQUIRED,
            "UNSAFE_WORKSPACE": ErrorCode.OPEN_INTEGRITY_REQUIRED,
            "UNSUPPORTED_SOURCE_LOCATOR": ErrorCode.OPEN_INTEGRITY_REQUIRED,
            "INVALID_ARTIFACT_SCOPE": ErrorCode.OPEN_INTEGRITY_REQUIRED,
        }
        if code in mapping:
            return mapping[code]
        try:
            return ErrorCode(code)
        except ValueError:
            return ErrorCode.OPEN_INTEGRITY_REQUIRED

    @staticmethod
    def _artifact_failure_status(code: ErrorCode) -> ArtifactIntegrityStatus:
        if code in {ErrorCode.SOURCE_NOT_FOUND, ErrorCode.ARTIFACT_MISSING}:
            return ArtifactIntegrityStatus.MISSING
        if code in {
            ErrorCode.SOURCE_FINGERPRINT_MISMATCH,
            ErrorCode.ARTIFACT_HASH_MISMATCH,
        }:
            return ArtifactIntegrityStatus.MISMATCH
        return ArtifactIntegrityStatus.UNREADABLE

    @staticmethod
    def _source_failure_status(code: ErrorCode) -> SourceStatus:
        if code == ErrorCode.SOURCE_NOT_FOUND:
            return SourceStatus.MISSING
        if code == ErrorCode.SOURCE_FINGERPRINT_MISMATCH:
            return SourceStatus.CHANGED
        return SourceStatus.UNREADABLE

    def _event(
        self,
        context: _OpenContext,
        actor: str,
        correlation_id: str,
        event_type: EventType,
        severity: EventSeverity,
        occurred_at: datetime,
        *,
        error_code: ErrorCode | None = None,
        previous_status: str | None = None,
        new_status: str | None = None,
        details: dict[str, object] | None = None,
    ) -> ProcessingEvent:
        artifact = context.artifact
        base_details: dict[str, object] = {
            "format": context.node.format.value,
        }
        if artifact is not None:
            base_details.update(
                {"artifact_id": artifact.id, "scope": artifact.scope.value}
            )
        if details:
            base_details.update(details)
        return ProcessingEvent(
            id=self._new_id(),
            event_type=event_type,
            project_id=context.project.id,
            source_id=context.source.id,
            node_id=context.node.id,
            actor=actor,
            occurred_at=occurred_at,
            severity=severity,
            previous_status=previous_status,
            new_status=new_status,
            error_code=error_code,
            details=base_details,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _required_text(value: str, field_name: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 255:
            raise ApplicationError(
                code="INVALID_REQUEST",
                message=f"{field_name} is invalid",
                details={"field": field_name},
            )
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise ApplicationError(
                code="INVALID_REQUEST",
                message=f"{field_name} contains control characters",
                details={"field": field_name},
            )
        return normalized
