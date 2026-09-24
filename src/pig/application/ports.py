from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable, Optional, Protocol, Sequence

from pig.domain.entities import Artifact, OriginalArtifact, Source
from pig.domain.enums import (
    ErrorCode,
    NodeFormat,
    OriginalSnapshotEntryKind,
    PathFlavor,
    RecoveryAction,
    RecoveryItemKind,
    SourceKind,
    WorkingContentStatus,
    WorkspaceExportKind,
)
from pig.domain.snapshot_policy import SnapshotImportPolicy
from pig.domain.repositories import UnitOfWork


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceReservation:
    project_id: str
    project_directory_name: str
    workspace_root: Path
    temporary_path: Path
    final_path: Path
    temporary_database_path: Path
    final_database_path: Path


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceObservation:
    path: Path
    locator: str
    path_flavor: PathFlavor
    kind: SourceKind
    original_name: str
    display_name: str
    size: Optional[int]
    sha256: Optional[str]
    signature: bytes
    modified_at: datetime
    verification_started_at: datetime
    verified_at: datetime


class WorkspaceManager(Protocol):
    def reserve(
        self,
        project_id: str,
        project_name: str,
        workspace_root: Optional[Path] = None,
    ) -> WorkspaceReservation: ...

    def publish(self, reservation: WorkspaceReservation) -> None: ...

    def abandon(self, reservation: WorkspaceReservation) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotInput:
    path: Path
    locator: str
    kind: SourceKind
    display_name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CapturedOriginalArtifact:
    id: str
    storage_key: str
    size: int
    sha256: str
    observed_modified_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class CapturedSnapshotEntry:
    id: str
    parent_entry_id: Optional[str]
    artifact_id: Optional[str]
    kind: OriginalSnapshotEntryKind
    original_name: str
    ordinal: int
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class CapturedSnapshot:
    root_entry_id: str
    artifacts: Sequence[CapturedOriginalArtifact]
    entries: Sequence[CapturedSnapshotEntry]
    total_size: int


class OriginalSnapshotWriteSession(Protocol):
    def capture(
        self,
        source: SnapshotInput,
        *,
        policy: SnapshotImportPolicy,
        prior_session_size: int,
    ) -> CapturedSnapshot: ...

    def publish(self) -> None: ...

    def complete(self) -> None: ...


class OriginalSnapshotStore(Protocol):
    def preflight(self, project_path: Path, input_path: Path) -> SnapshotInput: ...

    def begin(
        self,
        project_path: Path,
        import_session_id: str,
        snapshot_id: str,
    ) -> AbstractContextManager[OriginalSnapshotWriteSession]: ...

    def verify_artifact(
        self,
        project_path: Path,
        artifact: OriginalArtifact,
        *,
        chunk_size: int,
    ) -> None: ...

    def artifact_path(
        self, project_path: Path, artifact: OriginalArtifact
    ) -> Path: ...


class InspectionCacheSession(Protocol):
    def materialize(
        self,
        object_id: str,
        producer: Callable[[BinaryIO], None],
        *,
        maximum: int,
        total_maximum: int,
    ) -> Path: ...


class InspectionCacheStore(Protocol):
    def begin(
        self, project_path: Path, operation_id: str
    ) -> AbstractContextManager[InspectionCacheSession]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredWorkingContent:
    storage_key: str
    path: Path
    size: int
    sha256: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkingContentObservation:
    path: Path
    status: WorkingContentStatus
    exists: bool
    size: Optional[int] = None
    sha256: Optional[str] = None
    error_code: Optional[ErrorCode] = None
    error_message: Optional[str] = None
    modified_at: Optional[datetime] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredWorkingVersion:
    storage_key: str
    path: Path
    size: int
    sha256: str
    file_modified_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkingVersionPair:
    current: StoredWorkingVersion
    previous: Optional[StoredWorkingVersion]


class WorkingArtifactStore(Protocol):
    def materialize(
        self,
        project_path: Path,
        operation_id: str,
        workspace_item_id: str,
        display_name: str,
        trusted_suffix: str,
        producer: Callable[[BinaryIO], None],
        *,
        project_id: str,
        maximum: int,
    ) -> StoredWorkingContent: ...

    def observe(
        self,
        project_path: Path,
        storage_key: str,
        *,
        baseline_size: int,
        baseline_sha256: str,
        maximum: int,
        chunk_size: int,
        stability_retries: int,
    ) -> WorkingContentObservation: ...

    def restore(
        self,
        project_path: Path,
        operation_id: str,
        storage_key: str,
        producer: Callable[[BinaryIO], None],
        *,
        project_id: str,
        maximum: int,
        expected_size: int,
        expected_sha256: str,
        allow_replace: bool,
    ) -> StoredWorkingContent: ...


class WorkingVersionStore(Protocol):
    def initialize(
        self,
        project_path: Path,
        operation_id: str,
        working_artifact_id: str,
        working_storage_key: str,
        *,
        project_id: str,
        expected_size: int,
        expected_sha256: str,
        maximum: int,
        chunk_size: int,
        stability_retries: int,
    ) -> StoredWorkingVersion: ...

    def capture(
        self,
        project_path: Path,
        operation_id: str,
        working_artifact_id: str,
        working_storage_key: str,
        current_checkpoint_key: str,
        *,
        project_id: str,
        expected_old_size: int,
        expected_old_sha256: str,
        expected_new_size: int,
        expected_new_sha256: str,
        maximum: int,
        chunk_size: int,
        stability_retries: int,
    ) -> WorkingVersionPair: ...

    def rollback(
        self,
        project_path: Path,
        operation_id: str,
        working_artifact_id: str,
        working_storage_key: str,
        current_checkpoint_key: str,
        previous_storage_key: str,
        *,
        project_id: str,
        expected_current_size: int,
        expected_current_sha256: str,
        expected_previous_size: int,
        expected_previous_sha256: str,
        maximum: int,
        chunk_size: int,
        stability_retries: int,
    ) -> WorkingVersionPair: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceExportEntry:
    workspace_item_id: str
    relative_path: str
    source_path: Path
    size: int
    sha256: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceExportDirectory:
    relative_path: str


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredWorkspaceExport:
    path: Path
    size: int
    sha256: str
    entry_count: int


class WorkspaceExportStore(Protocol):
    def write(
        self,
        destination: Path,
        operation_id: str,
        entries: Sequence[WorkspaceExportEntry],
        directories: Sequence[WorkspaceExportDirectory] = (),
        *,
        export_kind: WorkspaceExportKind,
        allow_replace: bool,
        maximum_total_size: int,
        chunk_size: int,
    ) -> StoredWorkspaceExport: ...


class ImportUndoStorageSession(Protocol):
    @property
    def removed_size(self) -> int: ...

    def stage(self) -> None: ...

    def complete(self) -> None: ...


class ImportUndoStore(Protocol):
    def begin(
        self,
        project_path: Path,
        operation_id: str,
        snapshot_id: str,
        *,
        project_id: str,
        working_storage_keys: Sequence[str],
        revision_storage_keys: Sequence[str],
    ) -> AbstractContextManager[ImportUndoStorageSession]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredManifest:
    storage_key: str
    path: Path
    size: int
    sha256: str


class ManifestWriteSession(Protocol):
    def write(
        self,
        manifest_id: str,
        payload: bytes,
        *,
        max_size: int,
    ) -> StoredManifest: ...

    def publish(self) -> None: ...

    def complete(self) -> None: ...


class ManifestStore(Protocol):
    def begin(
        self, project_path: Path, operation_id: str
    ) -> AbstractContextManager[ManifestWriteSession]: ...


class FileOpener(Protocol):
    def open(self, path: Path) -> None: ...


class OpenHandoffStore(Protocol):
    def prepare(
        self,
        project_path: Path,
        artifact: Artifact,
        format: NodeFormat,
        verified_path: Path,
    ) -> Path: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class QuarantineRecord:
    kind: str
    original_storage_key: str
    quarantine_storage_key: str
    entry_type: str
    size: Optional[int] = None
    sha256: Optional[str] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceRecoveryReport:
    records: Sequence[QuarantineRecord]


class WorkspaceRecovery(Protocol):
    def reconcile(
        self,
        project_path: Path,
        recovery_id: str,
        *,
        known_artifact_keys: frozenset[str],
        known_manifest_keys: frozenset[str],
    ) -> WorkspaceRecoveryReport: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryCandidate:
    kind: RecoveryItemKind
    action: RecoveryAction
    storage_key: str
    reason: str
    operation_id: Optional[str] = None
    details: dict[str, object] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryInspection:
    token: str
    candidates: Sequence[RecoveryCandidate]


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryDisposition:
    status: str
    size: Optional[int] = None
    sha256: Optional[str] = None
    recovery_storage_key: Optional[str] = None


class WorkbenchRecoveryStore(Protocol):
    def inspect(
        self,
        project_path: Path,
        project_id: str,
        *,
        known_original_keys: frozenset[str],
        known_working_keys: frozenset[str],
        known_version_keys: frozenset[str],
        purged_snapshot_ids: frozenset[str],
    ) -> RecoveryInspection: ...

    def execute(
        self,
        project_path: Path,
        recovery_run_id: str,
        recovery_item_id: str,
        candidate: RecoveryCandidate,
    ) -> RecoveryDisposition: ...


class ProjectDatabaseProvider(Protocol):
    def migrate(self, database_path: Path) -> None: ...

    def unit_of_work(
        self, database_path: Path
    ) -> AbstractContextManager[UnitOfWork]: ...


class SourceInspector(Protocol):
    def inspect(self, path: Path, expected_kind: SourceKind) -> SourceObservation: ...

    def revalidate(self, source: Source) -> SourceObservation: ...

    def inspect_descendant(
        self,
        source: Source,
        relative_parts: Sequence[str],
        expected_kind: SourceKind,
        expected_artifact: Optional[Artifact] = None,
    ) -> SourceObservation: ...
