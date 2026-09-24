from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Mapping, Optional, Protocol, Sequence

from pig.domain.archive_security import evaluate_archive_entry_path
from pig.domain.enums import (
    ArtifactRole,
    ArtifactScope,
    ErrorCategory,
    ErrorCode,
    NodeFormat,
    NodeProcessingStatus,
    RelationshipType,
)
from pig.domain.processing_policy import ProcessingPolicy
from pig.handlers.base import (
    ArtifactWriteSession,
    ChildDescriptor,
    ChildMaterialization,
    ContainerInspection,
    HandlerOutcomeError,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchiveMemberToken:
    ordinal: int
    name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchiveMemberInfo:
    ordinal: int
    name: str
    is_directory: bool
    is_symbolic_link: bool
    size: Optional[int]
    compressed_size: Optional[int]
    encrypted: bool
    token: ArchiveMemberToken
    supported: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchiveInspection:
    members: Sequence[ArchiveMemberInfo]
    details: Mapping[str, object] = field(default_factory=dict)


class ArchiveBackendError(Exception):
    pass


class ArchiveBackendCorruptedError(ArchiveBackendError):
    pass


class ArchiveBackendPasswordError(ArchiveBackendError):
    pass


class ArchiveBackendUnsupportedError(ArchiveBackendError):
    pass


class ArchiveBackendDependencyError(ArchiveBackendError):
    pass


class ArchiveBackendVersionError(ArchiveBackendError):
    pass


class ArchiveBackendLimitError(ArchiveBackendError):
    def __init__(self, message: str, *, code: ErrorCode) -> None:
        super().__init__(message)
        self.code = code


class ArchiveBackendTimeoutError(ArchiveBackendError):
    pass


class ArchiveBackendExecutionError(ArchiveBackendError):
    pass


class ArchiveBackend(Protocol):
    name: str
    version: str

    def inspect(
        self, path: Path, *, policy: ProcessingPolicy
    ) -> ArchiveInspection: ...

    def write_member(
        self,
        path: Path,
        token: ArchiveMemberToken,
        output: BinaryIO,
        *,
        policy: ProcessingPolicy,
    ) -> None: ...


class ArchiveHandler:
    relationship_type = RelationshipType.ARCHIVE_ENTRY

    def __init__(self, format: NodeFormat, backend: ArchiveBackend) -> None:
        if format not in {NodeFormat.SEVEN_Z, NodeFormat.RAR}:
            raise ValueError("ArchiveHandler supports only SEVEN_Z or RAR")
        self.format = format
        self._backend = backend
        self.name = f"{format.value.lower()}-{backend.name}"
        self.version = backend.version

    def inspect(
        self, path: Path, policy: ProcessingPolicy
    ) -> ContainerInspection:
        try:
            inspection = self._backend.inspect(path, policy=policy)
        except ArchiveBackendError as exc:
            raise self._outcome(exc) from exc
        if len(inspection.members) > policy.max_archive_entries:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.LIMIT_EXCEEDED,
                code=ErrorCode.MAX_ARCHIVE_ENTRIES_EXCEEDED,
                category=ErrorCategory.RESOURCE_LIMIT,
                message=f"{self.format.value} entry count exceeds the configured limit",
            )

        names: dict[str, int] = {}
        for member in inspection.members:
            names[member.name] = names.get(member.name, 0) + 1

        declared_total = 0
        archive_size = max(path.stat().st_size, 1)
        archive_uncompressed = sum(
            member.size or 0
            for member in inspection.members
            if not member.is_directory and member.supported
        )
        archive_ratio_exceeded = (
            archive_uncompressed / archive_size > policy.max_compression_ratio
        )
        descriptors: list[ChildDescriptor] = []
        for member in inspection.members:
            decision = evaluate_archive_entry_path(
                member.name, is_symbolic_link=member.is_symbolic_link
            )
            status: Optional[NodeProcessingStatus] = None
            code: Optional[ErrorCode] = None
            category: Optional[ErrorCategory] = None
            if not decision.allowed:
                status = NodeProcessingStatus.SECURITY_BLOCKED
                code = decision.error_code
                category = ErrorCategory.SECURITY
            elif member.encrypted:
                status = NodeProcessingStatus.PASSWORD_REQUIRED
                code = ErrorCode.PASSWORD_REQUIRED
                category = ErrorCategory.FORMAT
            elif not member.supported:
                status = NodeProcessingStatus.UNSUPPORTED
                code = ErrorCode.UNSUPPORTED_FEATURE
                category = ErrorCategory.FORMAT
            elif names[member.name] > 1 and not member.is_directory:
                status = NodeProcessingStatus.UNSUPPORTED
                code = ErrorCode.UNSUPPORTED_FEATURE
                category = ErrorCategory.FORMAT
            elif member.size is not None and member.size > policy.max_single_file_size:
                status = NodeProcessingStatus.LIMIT_EXCEEDED
                code = ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED
                category = ErrorCategory.RESOURCE_LIMIT
            elif not member.is_directory and archive_ratio_exceeded:
                status = NodeProcessingStatus.LIMIT_EXCEEDED
                code = ErrorCode.MAX_COMPRESSION_RATIO_EXCEEDED
                category = ErrorCategory.RESOURCE_LIMIT
            elif not member.is_directory and member.size is not None:
                if (
                    member.compressed_size is not None
                    and member.compressed_size > 0
                    and member.size / member.compressed_size
                    > policy.max_compression_ratio
                ):
                    status = NodeProcessingStatus.LIMIT_EXCEEDED
                    code = ErrorCode.MAX_COMPRESSION_RATIO_EXCEEDED
                    category = ErrorCategory.RESOURCE_LIMIT
                elif declared_total + member.size > policy.max_total_expanded_size:
                    status = NodeProcessingStatus.LIMIT_EXCEEDED
                    code = ErrorCode.MAX_TOTAL_EXPANDED_SIZE_EXCEEDED
                    category = ErrorCategory.RESOURCE_LIMIT
                else:
                    declared_total += member.size
            descriptors.append(
                ChildDescriptor(
                    ordinal=member.ordinal,
                    discovery_key=(
                        f"{self.format.value.lower()}-entry:{member.ordinal}"
                    ),
                    original_name=member.name,
                    safe_parts=decision.safe_parts,
                    is_directory=member.is_directory,
                    declared_size=member.size,
                    token=member.token,
                    blocked_status=status,
                    error_code=code,
                    error_category=category,
                )
            )
        return ContainerInspection(
            children=tuple(descriptors), details=dict(inspection.details)
        )

    def materialize(
        self,
        path: Path,
        child: ChildDescriptor,
        artifact_id: str,
        store: ArtifactWriteSession,
        policy: ProcessingPolicy,
        observed_at: datetime,
    ) -> Optional[ChildMaterialization]:
        if child.is_directory or child.blocked_status is not None:
            return None
        token = child.token
        if not isinstance(token, ArchiveMemberToken):
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.FAILED,
                code=ErrorCode.HANDLER_FAILURE,
                category=ErrorCategory.INTERNAL,
                message="archive member token is invalid",
            )

        def produce(output: BinaryIO) -> None:
            try:
                self._backend.write_member(
                    path, token, output, policy=policy
                )
            except ArchiveBackendError as exc:
                raise self._outcome(exc) from exc

        stored = store.write_generated(
            artifact_id,
            produce,
            max_single_file_size=policy.max_single_file_size,
            max_total_expanded_size=policy.max_total_expanded_size,
        )
        return ChildMaterialization(
            role=ArtifactRole.EXTRACTED_ARTIFACT,
            scope=ArtifactScope.PROJECT_WORKSPACE,
            locator=stored.storage_key,
            size=stored.size,
            sha256=stored.sha256,
            signature=stored.signature,
            observed_at=observed_at,
        )

    @staticmethod
    def _outcome(exc: ArchiveBackendError) -> HandlerOutcomeError:
        if isinstance(exc, ArchiveBackendPasswordError):
            return HandlerOutcomeError(
                status=NodeProcessingStatus.PASSWORD_REQUIRED,
                code=ErrorCode.PASSWORD_REQUIRED,
                category=ErrorCategory.FORMAT,
                message=str(exc) or "archive requires a password",
            )
        if isinstance(exc, ArchiveBackendCorruptedError):
            return HandlerOutcomeError(
                status=NodeProcessingStatus.CORRUPTED,
                code=ErrorCode.CORRUPTED_CONTAINER,
                category=ErrorCategory.FORMAT,
                message=str(exc) or "archive structure is corrupted",
            )
        if isinstance(exc, ArchiveBackendUnsupportedError):
            return HandlerOutcomeError(
                status=NodeProcessingStatus.UNSUPPORTED,
                code=ErrorCode.UNSUPPORTED_FEATURE,
                category=ErrorCategory.FORMAT,
                message=str(exc) or "archive feature is unsupported",
            )
        if isinstance(exc, ArchiveBackendDependencyError):
            return HandlerOutcomeError(
                status=NodeProcessingStatus.UNSUPPORTED,
                code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                category=ErrorCategory.PROCESSING,
                message=str(exc) or "archive dependency is unavailable",
            )
        if isinstance(exc, ArchiveBackendVersionError):
            return HandlerOutcomeError(
                status=NodeProcessingStatus.UNSUPPORTED,
                code=ErrorCode.DEPENDENCY_VERSION_UNSUPPORTED,
                category=ErrorCategory.PROCESSING,
                message=str(exc) or "archive dependency version is unsupported",
            )
        if isinstance(exc, ArchiveBackendTimeoutError):
            return HandlerOutcomeError(
                status=NodeProcessingStatus.LIMIT_EXCEEDED,
                code=ErrorCode.EXTERNAL_PROCESS_TIMEOUT,
                category=ErrorCategory.RESOURCE_LIMIT,
                message=str(exc) or "archive process exceeded its time limit",
                retryable=True,
            )
        if isinstance(exc, ArchiveBackendLimitError):
            return HandlerOutcomeError(
                status=NodeProcessingStatus.LIMIT_EXCEEDED,
                code=exc.code,
                category=ErrorCategory.RESOURCE_LIMIT,
                message=str(exc) or "archive inspection exceeded a resource limit",
            )
        return HandlerOutcomeError(
            status=NodeProcessingStatus.FAILED,
            code=ErrorCode.HANDLER_FAILURE,
            category=ErrorCategory.PROCESSING,
            message=str(exc) or "archive backend failed",
            retryable=True,
        )
