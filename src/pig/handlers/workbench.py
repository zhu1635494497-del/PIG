from __future__ import annotations

import stat
import zipfile
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Optional, Protocol, Sequence

from pig.domain.archive_security import evaluate_archive_entry_path
from pig.domain.entities import OriginalSnapshotEntry
from pig.domain.enums import (
    ErrorCategory,
    ErrorCode,
    MaterializationLocatorKind,
    NodeFormat,
    NodeProcessingStatus,
    RelationshipType,
)
from pig.domain.processing_policy import ProcessingPolicy
from pig.handlers.base import (
    ContainerHandler,
    HandlerOutcomeError,
    MetadataDescriptor,
    StoredArtifact,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class BackendIdentity:
    handler_name: str
    handler_version: str
    backend_name: str
    backend_version: str
    backend_sha256: Optional[str] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class StructureChild:
    ordinal: int
    original_name: str
    safe_parts: tuple[str, ...]
    is_directory: bool
    declared_size: Optional[int]
    locator_kind: Optional[MaterializationLocatorKind]
    relationship_type: RelationshipType
    member_role: str
    blocked_status: Optional[NodeProcessingStatus] = None
    error_code: Optional[ErrorCode] = None
    error_category: Optional[ErrorCategory] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class StructureInspection:
    children: Sequence[StructureChild]
    backend_identity: BackendIdentity
    metadata: Sequence[MetadataDescriptor] = ()


class WorkbenchStructureHandler(Protocol):
    name: str
    version: str
    format: NodeFormat
    locator_kind: MaterializationLocatorKind
    hierarchical: bool

    @property
    def default_backend_identity(self) -> BackendIdentity: ...

    def inspect(
        self, path: Path, policy: ProcessingPolicy
    ) -> StructureInspection: ...

    def materialize(
        self,
        path: Path,
        member_ordinal: int,
        expected_name: str,
        member_role: str,
        output: BinaryIO,
        policy: ProcessingPolicy,
    ) -> None: ...


class WorkbenchStructureHandlerRegistry:
    def __init__(self, handlers: Sequence[WorkbenchStructureHandler]) -> None:
        by_format: dict[NodeFormat, WorkbenchStructureHandler] = {}
        by_locator: dict[MaterializationLocatorKind, WorkbenchStructureHandler] = {}
        for handler in handlers:
            if handler.format in by_format:
                raise ValueError(
                    f"duplicate Workbench handler for {handler.format.value}"
                )
            by_format[handler.format] = handler
            if handler.locator_kind in by_locator:
                raise ValueError(
                    f"duplicate Workbench locator handler for {handler.locator_kind.value}"
                )
            by_locator[handler.locator_kind] = handler
        self._handlers = by_format
        self._locator_handlers = by_locator

    def resolve(self, format: NodeFormat) -> Optional[WorkbenchStructureHandler]:
        return self._handlers.get(format)

    def resolve_locator(
        self, kind: MaterializationLocatorKind
    ) -> Optional[WorkbenchStructureHandler]:
        return self._locator_handlers.get(kind)


class SnapshotFolderStructureHandler:
    """W3 Folder adapter over the immutable W2 Snapshot Entry tree."""

    name = "workbench-snapshot-folder"
    version = "1.0"
    format = NodeFormat.FOLDER

    @property
    def default_backend_identity(self) -> BackendIdentity:
        return BackendIdentity(
            handler_name=self.name,
            handler_version=self.version,
            backend_name="snapshot-entry-tree",
            backend_version="1.0",
        )

    def list_children(
        self,
        entries: Sequence[OriginalSnapshotEntry],
        parent_entry_id: str,
    ) -> Sequence[OriginalSnapshotEntry]:
        return tuple(
            sorted(
                (
                    entry
                    for entry in entries
                    if entry.parent_entry_id == parent_entry_id
                ),
                key=lambda entry: (entry.ordinal, entry.id),
            )
        )


class ZipStructureHandler:
    """W3 ZIP adapter: structure inspection is separate from one-member output."""

    name = "workbench-zip-stdlib"
    version = "1.0"
    format = NodeFormat.ZIP
    locator_kind = MaterializationLocatorKind.ZIP_MEMBER
    hierarchical = True

    @property
    def default_backend_identity(self) -> BackendIdentity:
        return BackendIdentity(
            handler_name=self.name,
            handler_version=self.version,
            backend_name="python-zipfile",
            backend_version="stdlib",
        )

    def inspect(
        self, path: Path, policy: ProcessingPolicy
    ) -> StructureInspection:
        try:
            with zipfile.ZipFile(path, "r") as archive:
                infos = archive.infolist()
        except (zipfile.BadZipFile, OSError) as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.CORRUPTED,
                code=ErrorCode.CORRUPTED_CONTAINER,
                category=ErrorCategory.FORMAT,
                message="ZIP central directory could not be read",
            ) from exc
        if len(infos) > policy.max_archive_entries:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.LIMIT_EXCEEDED,
                code=ErrorCode.MAX_ARCHIVE_ENTRIES_EXCEEDED,
                category=ErrorCategory.RESOURCE_LIMIT,
                message="ZIP entry count exceeds the configured limit",
            )

        result: list[StructureChild] = []
        declared_total = 0
        for ordinal, info in enumerate(infos):
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            decision = evaluate_archive_entry_path(
                info.filename, is_symbolic_link=stat.S_ISLNK(unix_mode)
            )
            status = None
            code = None
            category = None
            if not decision.allowed:
                status = NodeProcessingStatus.SECURITY_BLOCKED
                code = decision.error_code
                category = ErrorCategory.SECURITY
            elif info.flag_bits & 0x1:
                status = NodeProcessingStatus.PASSWORD_REQUIRED
                code = ErrorCode.PASSWORD_REQUIRED
                category = ErrorCategory.FORMAT
            elif info.file_size > policy.max_single_file_size:
                status = NodeProcessingStatus.LIMIT_EXCEEDED
                code = ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED
                category = ErrorCategory.RESOURCE_LIMIT
            elif not info.is_dir():
                compressed = max(info.compress_size, 1)
                if info.file_size / compressed > policy.max_compression_ratio:
                    status = NodeProcessingStatus.LIMIT_EXCEEDED
                    code = ErrorCode.MAX_COMPRESSION_RATIO_EXCEEDED
                    category = ErrorCategory.RESOURCE_LIMIT
                elif declared_total + info.file_size > policy.max_total_expanded_size:
                    status = NodeProcessingStatus.LIMIT_EXCEEDED
                    code = ErrorCode.MAX_TOTAL_EXPANDED_SIZE_EXCEEDED
                    category = ErrorCategory.RESOURCE_LIMIT
                else:
                    declared_total += info.file_size
            result.append(
                StructureChild(
                    ordinal=ordinal,
                    original_name=info.filename,
                    safe_parts=decision.safe_parts,
                    is_directory=info.is_dir(),
                    declared_size=info.file_size,
                    locator_kind=(
                        None
                        if info.is_dir() or status is not None
                        else MaterializationLocatorKind.ZIP_MEMBER
                    ),
                    relationship_type=RelationshipType.ARCHIVE_ENTRY,
                    member_role=RelationshipType.ARCHIVE_ENTRY.value,
                    blocked_status=status,
                    error_code=code,
                    error_category=category,
                )
            )
        return StructureInspection(
            children=tuple(result),
            backend_identity=self.default_backend_identity,
        )

    def materialize(
        self,
        path: Path,
        member_ordinal: int,
        expected_name: str,
        member_role: str,
        output: BinaryIO,
        policy: ProcessingPolicy,
    ) -> None:
        try:
            with zipfile.ZipFile(path, "r") as archive:
                infos = archive.infolist()
                if member_ordinal < 0 or member_ordinal >= len(infos):
                    raise HandlerOutcomeError(
                        status=NodeProcessingStatus.CORRUPTED,
                        code=ErrorCode.CORRUPTED_CONTAINER,
                        category=ErrorCategory.FORMAT,
                        message="ZIP member identity is no longer valid",
                    )
                info = infos[member_ordinal]
                if (
                    info.filename != expected_name
                    or member_role != RelationshipType.ARCHIVE_ENTRY.value
                ):
                    raise HandlerOutcomeError(
                        status=NodeProcessingStatus.CORRUPTED,
                        code=ErrorCode.CORRUPTED_CONTAINER,
                        category=ErrorCategory.FORMAT,
                        message="ZIP member identity is no longer valid",
                    )
                if info.is_dir():
                    raise HandlerOutcomeError(
                        status=NodeProcessingStatus.UNSUPPORTED,
                        code=ErrorCode.UNSUPPORTED_FEATURE,
                        category=ErrorCategory.FORMAT,
                        message="a ZIP directory has no materializable bytes",
                    )
                if info.flag_bits & 0x1:
                    raise HandlerOutcomeError(
                        status=NodeProcessingStatus.PASSWORD_REQUIRED,
                        code=ErrorCode.PASSWORD_REQUIRED,
                        category=ErrorCategory.FORMAT,
                        message="ZIP entry requires a password",
                    )
                with archive.open(info, "r") as stream:
                    while True:
                        chunk = stream.read(policy.io_chunk_size)
                        if not chunk:
                            break
                        output.write(chunk)
        except HandlerOutcomeError:
            raise
        except NotImplementedError as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.UNSUPPORTED,
                code=ErrorCode.UNSUPPORTED_FEATURE,
                category=ErrorCategory.FORMAT,
                message="ZIP compression feature is unsupported",
            ) from exc
        except RuntimeError as exc:
            code = (
                ErrorCode.PASSWORD_REQUIRED
                if "password" in str(exc).lower() or "encrypted" in str(exc).lower()
                else ErrorCode.CORRUPTED_CONTAINER
            )
            raise HandlerOutcomeError(
                status=(
                    NodeProcessingStatus.PASSWORD_REQUIRED
                    if code == ErrorCode.PASSWORD_REQUIRED
                    else NodeProcessingStatus.CORRUPTED
                ),
                code=code,
                category=ErrorCategory.FORMAT,
                message="ZIP entry could not be decoded",
            ) from exc
        except (zipfile.BadZipFile, OSError, EOFError) as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.CORRUPTED,
                code=ErrorCode.CORRUPTED_CONTAINER,
                category=ErrorCategory.FORMAT,
                message="ZIP entry could not be extracted safely",
            ) from exc

    def signature(
        self,
        path: Path,
        member_ordinal: int,
        *,
        maximum_bytes: int = 8,
    ) -> bytes:
        try:
            with zipfile.ZipFile(path, "r") as archive:
                infos = archive.infolist()
                if member_ordinal < 0 or member_ordinal >= len(infos):
                    raise IndexError(member_ordinal)
                info = infos[member_ordinal]
                if info.is_dir() or info.flag_bits & 0x1:
                    return b""
                with archive.open(info, "r") as stream:
                    return stream.read(maximum_bytes)
        except (IndexError, zipfile.BadZipFile, OSError, EOFError, RuntimeError):
            return b""


class _DigestingOutput:
    def __init__(self, output: BinaryIO, maximum: int) -> None:
        self._output = output
        self._maximum = maximum
        self._digest = hashlib.sha256()
        self._signature = bytearray()
        self.size = 0

    def write(self, data: bytes | bytearray) -> int:
        payload = bytes(data)
        if self.size + len(payload) > self._maximum:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.LIMIT_EXCEEDED,
                code=ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED,
                category=ErrorCategory.RESOURCE_LIMIT,
                message="container member exceeds the configured single-file limit",
            )
        written = self._output.write(payload)
        accepted = payload[:written]
        self._digest.update(accepted)
        if len(self._signature) < 8:
            self._signature.extend(accepted[: 8 - len(self._signature)])
        self.size += written
        return written

    def flush(self) -> None:
        flush = getattr(self._output, "flush", None)
        if flush is not None:
            flush()

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    @property
    def signature(self) -> bytes:
        return bytes(self._signature)


class _DirectArtifactSession:
    """Expose a historical Handler to the Workbench without publishing an Artifact."""

    def __init__(self, output: BinaryIO) -> None:
        self._output = output

    def write_stream(
        self,
        artifact_id: str,
        stream: BinaryIO,
        *,
        max_single_file_size: int,
        max_total_expanded_size: int,
        chunk_size: int,
    ) -> StoredArtifact:
        writer = _DigestingOutput(
            self._output, min(max_single_file_size, max_total_expanded_size)
        )
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            writer.write(chunk)
        return self._stored(artifact_id, writer)

    def write_generated(
        self,
        artifact_id: str,
        producer,
        *,
        max_single_file_size: int,
        max_total_expanded_size: int,
    ) -> StoredArtifact:
        writer = _DigestingOutput(
            self._output, min(max_single_file_size, max_total_expanded_size)
        )
        producer(writer)
        return self._stored(artifact_id, writer)

    @staticmethod
    def _stored(artifact_id: str, writer: _DigestingOutput) -> StoredArtifact:
        return StoredArtifact(
            storage_key=f"workbench-direct/{artifact_id}",
            size=writer.size,
            sha256=writer.sha256,
            signature=writer.signature,
        )

    def publish(self) -> None:
        return None

    def complete(self) -> None:
        return None


class LegacyContainerWorkbenchAdapter:
    """Workbench-native facade over vetted EML/MSG/7z/RAR format handlers."""

    def __init__(
        self,
        handler: ContainerHandler,
        *,
        locator_kind: MaterializationLocatorKind,
        hierarchical: bool,
        backend_name: str,
        backend_version: str,
    ) -> None:
        self._handler = handler
        self.format = handler.format
        self.name = f"workbench-{handler.name}"
        self.version = "1.0"
        self.hierarchical = hierarchical
        self._default_identity = BackendIdentity(
            handler_name=self.name,
            handler_version=self.version,
            backend_name=backend_name,
            backend_version=backend_version,
        )
        self._locator_kind = locator_kind
        self.locator_kind = locator_kind

    @property
    def default_backend_identity(self) -> BackendIdentity:
        return self._default_identity

    def inspect(self, path: Path, policy: ProcessingPolicy) -> StructureInspection:
        result = self._handler.inspect(path, policy)
        details = result.details
        identity = BackendIdentity(
            handler_name=self.name,
            handler_version=self.version,
            backend_name=str(details.get("backend", self._default_identity.backend_name)),
            backend_version=str(
                details.get("backend_version", self._default_identity.backend_version)
            ),
            backend_sha256=(
                None
                if details.get("executable_sha256") is None
                else str(details["executable_sha256"])
            ),
        )
        children = tuple(
            StructureChild(
                ordinal=child.ordinal,
                original_name=child.original_name,
                safe_parts=child.safe_parts,
                is_directory=child.is_directory,
                declared_size=child.declared_size,
                locator_kind=(
                    None
                    if child.is_directory or child.blocked_status is not None
                    else self._locator_kind
                ),
                relationship_type=(
                    child.relationship_type or self._handler.relationship_type
                ),
                member_role=(
                    child.relationship_type or self._handler.relationship_type
                ).value,
                blocked_status=child.blocked_status,
                error_code=child.error_code,
                error_category=child.error_category,
            )
            for child in result.children
        )
        return StructureInspection(
            children=children,
            metadata=result.metadata,
            backend_identity=identity,
        )

    def materialize(
        self,
        path: Path,
        member_ordinal: int,
        expected_name: str,
        member_role: str,
        output: BinaryIO,
        policy: ProcessingPolicy,
    ) -> None:
        inspection = self._handler.inspect(path, policy)
        try:
            child = next(
                child
                for child in inspection.children
                if child.ordinal == member_ordinal
            )
        except StopIteration as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.CORRUPTED,
                code=ErrorCode.CORRUPTED_CONTAINER,
                category=ErrorCategory.FORMAT,
                message="container member identity is no longer valid",
            ) from exc
        relationship = child.relationship_type or self._handler.relationship_type
        if child.original_name != expected_name or relationship.value != member_role:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.CORRUPTED,
                code=ErrorCode.CORRUPTED_CONTAINER,
                category=ErrorCategory.FORMAT,
                message="container member identity changed during recipe replay",
            )
        if child.blocked_status is not None or child.is_directory:
            raise HandlerOutcomeError(
                status=child.blocked_status or NodeProcessingStatus.UNSUPPORTED,
                code=child.error_code or ErrorCode.UNSUPPORTED_FEATURE,
                category=child.error_category or ErrorCategory.FORMAT,
                message="container member is not materializable",
            )
        result = self._handler.materialize(
            path,
            child,
            f"direct-{member_ordinal}",
            _DirectArtifactSession(output),
            policy,
            datetime.now(timezone.utc),
        )
        if result is None:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.UNSUPPORTED,
                code=ErrorCode.UNSUPPORTED_FEATURE,
                category=ErrorCategory.FORMAT,
                message="container member produced no materializable bytes",
            )
