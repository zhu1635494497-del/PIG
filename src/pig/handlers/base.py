from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable, Mapping, Optional, Protocol, Sequence

from pig.domain.enums import (
    ArtifactRole,
    ArtifactScope,
    ErrorCategory,
    ErrorCode,
    MetadataValueType,
    NodeFormat,
    NodeProcessingStatus,
    RelationshipType,
)
from pig.domain.entities import Artifact
from pig.domain.processing_policy import ProcessingPolicy


@dataclass(frozen=True, slots=True, kw_only=True)
class ChildDescriptor:
    ordinal: int
    discovery_key: str
    original_name: str
    safe_parts: tuple[str, ...]
    is_directory: bool
    declared_size: Optional[int]
    token: object
    blocked_status: Optional[NodeProcessingStatus] = None
    error_code: Optional[ErrorCode] = None
    error_category: Optional[ErrorCategory] = None
    relationship_type: Optional[RelationshipType] = None
    media_type: Optional[str] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MetadataDescriptor:
    namespace: str
    key: str
    value_type: MetadataValueType
    provenance: str
    value_text: Optional[str] = None
    value_integer: Optional[int] = None
    value_real: Optional[float] = None
    value_boolean: Optional[bool] = None
    value_datetime: Optional[datetime] = None
    value_json: Optional[object] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainerInspection:
    children: Sequence[ChildDescriptor]
    metadata: Sequence[MetadataDescriptor] = ()
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class ChildMaterialization:
    role: ArtifactRole
    scope: ArtifactScope
    locator: str
    size: int
    sha256: str
    signature: bytes
    observed_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredArtifact:
    storage_key: str
    size: int
    sha256: str
    signature: bytes


@dataclass(frozen=True, slots=True, kw_only=True)
class ArtifactObservation:
    path: Path
    size: int
    sha256: str
    signature: bytes
    observed_at: datetime


class ArtifactWriteSession(Protocol):
    def write_stream(
        self,
        artifact_id: str,
        stream: BinaryIO,
        *,
        max_single_file_size: int,
        max_total_expanded_size: int,
        chunk_size: int,
    ) -> StoredArtifact: ...

    def write_generated(
        self,
        artifact_id: str,
        producer: Callable[[BinaryIO], None],
        *,
        max_single_file_size: int,
        max_total_expanded_size: int,
    ) -> StoredArtifact: ...

    def publish(self) -> None: ...

    def complete(self) -> None: ...


class ArtifactStore(Protocol):
    def begin(self, project_path: Path, operation_id: str): ...

    def inspect(
        self, project_path: Path, artifact: Artifact, *, chunk_size: int
    ) -> ArtifactObservation: ...


class HandlerOutcomeError(Exception):
    def __init__(
        self,
        *,
        status: NodeProcessingStatus,
        code: ErrorCode,
        category: ErrorCategory,
        message: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.category = category
        self.message = message
        self.retryable = retryable


class ContainerHandler(Protocol):
    name: str
    version: str
    format: NodeFormat
    relationship_type: RelationshipType

    def inspect(
        self, path: Path, policy: ProcessingPolicy
    ) -> ContainerInspection: ...

    def materialize(
        self,
        path: Path,
        child: ChildDescriptor,
        artifact_id: str,
        store: ArtifactWriteSession,
        policy: ProcessingPolicy,
        observed_at: datetime,
    ) -> Optional[ChildMaterialization]: ...


class ContainerHandlerRegistry:
    def __init__(self, handlers: Sequence[ContainerHandler]) -> None:
        by_format: dict[NodeFormat, ContainerHandler] = {}
        for handler in handlers:
            if handler.format in by_format:
                raise ValueError(f"duplicate handler for {handler.format.value}")
            by_format[handler.format] = handler
        self._handlers = by_format

    def resolve(self, format: NodeFormat) -> Optional[ContainerHandler]:
        return self._handlers.get(format)
