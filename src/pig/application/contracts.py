from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from pig.domain.entities import (
    Artifact,
    LineageRecord,
    Node,
    NodeMetadata,
    ProcessingEvent,
    Project,
    RecoveryItem,
    RecoveryRun,
    Source,
    WorkingArtifact,
    WorkingRevision,
    WorkspaceItem,
    WorkspacePlacement,
)
from pig.domain.enums import (
    ImportSessionStatus,
    OriginalSnapshotStatus,
    JobStatus,
    NodeFormat,
    NodeKind,
    NodeProcessingStatus,
    ProjectStatus,
    RelationshipType,
    SourceKind,
    SourceStatus,
    WorkingRefreshReason,
    WorkingContentStatus,
    WorkspaceItemLifecycleStatus,
    WorkspaceExportKind,
)
from pig.domain.processing_policy import ProcessingPolicy
from pig.domain.snapshot_policy import SnapshotImportPolicy
from pig.application.ports import QuarantineRecord, RecoveryCandidate


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateProjectRequest:
    name: str
    actor: str
    description: Optional[str] = None
    workspace_root: Optional[Path] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateProjectResult:
    project_id: str
    status: ProjectStatus
    workspace_path: Path
    database_path: Path
    workspace_revision: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportProjectItemsRequest:
    project_id: str
    database_path: Path
    input_paths: Sequence[Path]
    actor: str
    idempotency_key: Optional[str] = None
    policy: SnapshotImportPolicy = SnapshotImportPolicy()
    target_workspace_parent_id: Optional[str] = None
    expected_workspace_revision: Optional[int] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportItemResult:
    input_path: Path
    snapshot_id: Optional[str]
    captured: bool
    source_id: Optional[str] = None
    root_node_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportProjectItemsResult:
    project_id: str
    import_session_id: str
    session_status: ImportSessionStatus
    requested_item_count: int
    accepted_item_count: int
    failed_item_count: int
    items: Sequence[ImportItemResult]


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifyOriginalSnapshotRequest:
    project_id: str
    database_path: Path
    snapshot_id: str
    actor: str
    chunk_size: int = 1024 * 1024


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifyOriginalSnapshotResult:
    project_id: str
    snapshot_id: str
    status: OriginalSnapshotStatus
    verified_artifact_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class InspectImportSessionRequest:
    project_id: str
    database_path: Path
    import_session_id: str
    actor: str
    policy: ProcessingPolicy = ProcessingPolicy()


@dataclass(frozen=True, slots=True, kw_only=True)
class InspectImportSessionResult:
    project_id: str
    import_session_id: str
    session_status: ImportSessionStatus
    job_id: str
    source_count: int
    node_count: int
    workspace_item_count: int
    warning_count: int
    error_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterializeWorkspaceItemRequest:
    project_id: str
    database_path: Path
    workspace_item_id: str
    actor: str
    policy: ProcessingPolicy = ProcessingPolicy()


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterializeWorkspaceItemResult:
    project_id: str
    workspace_item_id: str
    working_artifact: WorkingArtifact
    path: Path
    reused: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshWorkingArtifactRequest:
    project_id: str
    database_path: Path
    workspace_item_id: str
    actor: str
    reason: WorkingRefreshReason = WorkingRefreshReason.EXPLICIT


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshWorkingArtifactResult:
    project_id: str
    workspace_item_id: str
    working_artifact: WorkingArtifact
    path: Path
    reason: WorkingRefreshReason
    changed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenWorkspaceItemRequest:
    project_id: str
    database_path: Path
    workspace_item_id: str
    actor: str
    policy: ProcessingPolicy = ProcessingPolicy()


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenWorkspaceItemResult:
    project_id: str
    workspace_item_id: str
    working_artifact: WorkingArtifact
    format: NodeFormat
    path: Path
    materialized: bool
    handed_off_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class RestoreWorkingArtifactRequest:
    project_id: str
    database_path: Path
    workspace_item_id: str
    actor: str
    confirmed_replace: bool = False
    policy: ProcessingPolicy = ProcessingPolicy()


@dataclass(frozen=True, slots=True, kw_only=True)
class RestoreWorkingArtifactResult:
    project_id: str
    workspace_item_id: str
    working_artifact: WorkingArtifact
    path: Path
    replaced: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class RollbackWorkingArtifactRequest:
    project_id: str
    database_path: Path
    workspace_item_id: str
    actor: str
    confirmed_replace: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class RollbackWorkingArtifactResult:
    project_id: str
    workspace_item_id: str
    working_artifact: WorkingArtifact
    previous_revision: WorkingRevision
    path: Path


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportWorkspaceItemsRequest:
    project_id: str
    database_path: Path
    workspace_item_ids: Sequence[str]
    destination_path: Path
    actor: str
    confirmed_replace: bool = False
    policy: ProcessingPolicy = ProcessingPolicy()


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportWorkspaceItemsResult:
    project_id: str
    workspace_item_ids: Sequence[str]
    destination_path: Path
    export_kind: WorkspaceExportKind
    entry_count: int
    size: int
    sha256: str

    @property
    def archive(self) -> bool:
        return self.export_kind == WorkspaceExportKind.ZIP


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateWorkspaceFolderRequest:
    project_id: str
    database_path: Path
    display_name: str
    actor: str
    expected_workspace_revision: int
    parent_workspace_item_id: Optional[str] = None
    ordinal: Optional[int] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MoveWorkspaceItemRequest:
    project_id: str
    database_path: Path
    workspace_item_id: str
    actor: str
    expected_workspace_revision: int
    new_parent_workspace_item_id: Optional[str] = None
    new_ordinal: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class SoftDeleteWorkspaceItemRequest:
    project_id: str
    database_path: Path
    workspace_item_id: str
    actor: str
    expected_workspace_revision: int
    confirmed: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class RestoreWorkspaceItemRequest:
    project_id: str
    database_path: Path
    workspace_item_id: str
    actor: str
    expected_workspace_revision: int


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceMutationResult:
    project_id: str
    workspace_revision: int
    item: WorkspaceItem
    placement: WorkspacePlacement
    restore_fallback: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class AddWorkspaceInputsRequest:
    project_id: str
    database_path: Path
    input_paths: Sequence[Path]
    actor: str
    expected_workspace_revision: int
    target_workspace_parent_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    snapshot_policy: SnapshotImportPolicy = SnapshotImportPolicy()
    processing_policy: ProcessingPolicy = ProcessingPolicy()


@dataclass(frozen=True, slots=True, kw_only=True)
class AddWorkspaceInputsResult:
    project_id: str
    workspace_revision: int
    import_result: ImportProjectItemsResult
    inspection_result: Optional[InspectImportSessionResult]


@dataclass(frozen=True, slots=True, kw_only=True)
class PreviewImportUndoRequest:
    project_id: str
    database_path: Path
    workspace_item_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportUndoImpact:
    project_id: str
    workspace_item_id: str
    snapshot_id: str
    source_id: str
    display_name: str
    workspace_item_count: int
    working_file_count: int
    modified_working_file_count: int
    original_byte_count: int
    working_byte_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class UndoImportedItemRequest:
    project_id: str
    database_path: Path
    workspace_item_id: str
    actor: str
    expected_workspace_revision: int
    confirmed: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class UndoImportedItemResult:
    project_id: str
    workspace_item_id: str
    snapshot_id: str
    source_id: str
    workspace_revision: int
    purged_workspace_item_count: int
    removed_byte_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceItemView:
    item: WorkspaceItem
    placement: WorkspacePlacement
    workspace_path: str
    effectively_active: bool
    source_node: Optional[Node] = None
    source: Optional[Source] = None
    working_artifact: Optional[WorkingArtifact] = None
    current_revision: Optional[WorkingRevision] = None
    previous_revision: Optional[WorkingRevision] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class GetWorkspaceTreeRequest:
    project_id: str
    database_path: Path


@dataclass(frozen=True, slots=True, kw_only=True)
class GetWorkspaceTreeResult:
    project: Project
    workspace_revision: int
    items: Sequence[WorkspaceItemView]
    deleted_items: Sequence[WorkspaceItemView]


@dataclass(frozen=True, slots=True, kw_only=True)
class GetWorkspaceItemRequest:
    project_id: str
    database_path: Path
    workspace_item_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class GetWorkspaceItemResult:
    project: Project
    view: WorkspaceItemView


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchWorkspaceItemsRequest:
    project_id: str
    database_path: Path
    query: Optional[str] = None
    formats: Sequence[NodeFormat] = ()
    content_statuses: Sequence[WorkingContentStatus] = ()
    lifecycle_statuses: Sequence[WorkspaceItemLifecycleStatus] = (
        WorkspaceItemLifecycleStatus.ACTIVE,
    )
    limit: int = 200
    offset: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchWorkspaceItemsResult:
    project_id: str
    items: Sequence[WorkspaceItemView]
    total: int
    limit: int
    offset: int
    has_more: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisterSourceRequest:
    project_id: str
    database_path: Path
    source_path: Path
    source_kind: SourceKind
    actor: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisterSourceResult:
    project_id: str
    source_id: str
    source_status: SourceStatus
    root_node_id: str
    artifact_id: Optional[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class GetProjectOverviewRequest:
    project_id: str
    database_path: Path


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceOverview:
    source: Source
    root_node: Node
    artifacts: Sequence[Artifact]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectOverview:
    project: Project
    sources: Sequence[SourceOverview]
    events: Sequence[ProcessingEvent]


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadProjectRequest:
    database_path: Path


@dataclass(frozen=True, slots=True, kw_only=True)
class GetNodeRequest:
    project_id: str
    database_path: Path
    node_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeDetails:
    node: Node
    source: Source
    artifacts: Sequence[Artifact]
    metadata: Sequence[NodeMetadata]
    lineage: Sequence[LineageRecord]
    children: Sequence[Node] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessNodeRequest:
    project_id: str
    database_path: Path
    node_id: str
    actor: str
    policy: ProcessingPolicy = ProcessingPolicy()


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessNodeResult:
    project_id: str
    node_id: str
    node_status: NodeProcessingStatus
    job_id: str
    job_status: JobStatus
    attempt_id: str
    child_node_ids: Sequence[str]
    warning_count: int
    error_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessProjectRequest:
    project_id: str
    database_path: Path
    actor: str
    policy: ProcessingPolicy = ProcessingPolicy()


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessProjectResult:
    project_id: str
    job_id: str
    job_status: JobStatus
    project_status: ProjectStatus
    processed_node_ids: Sequence[str]
    attempt_ids: Sequence[str]
    warning_count: int
    error_count: int
    total_expanded_size: int


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoverProjectRequest:
    project_id: str
    database_path: Path
    actor: str
    policy: ProcessingPolicy = ProcessingPolicy()


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoverProjectResult:
    project_id: str
    recovery_job_id: str
    job_status: JobStatus
    project_status: ProjectStatus
    interrupted_job_ids: Sequence[str]
    cancelled_job_ids: Sequence[str]
    interrupted_attempt_ids: Sequence[str]
    cancelled_attempt_ids: Sequence[str]
    recovered_node_ids: Sequence[str]
    processed_node_ids: Sequence[str]
    attempt_ids: Sequence[str]
    quarantine_records: Sequence[QuarantineRecord]
    warning_count: int
    error_count: int
    total_expanded_size: int


@dataclass(frozen=True, slots=True, kw_only=True)
class InspectProjectRecoveryRequest:
    project_id: str
    database_path: Path


@dataclass(frozen=True, slots=True, kw_only=True)
class InspectProjectRecoveryResult:
    project_id: str
    inspection_token: str
    recovery_required: bool
    candidates: Sequence[RecoveryCandidate]


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoverWorkbenchProjectRequest:
    project_id: str
    database_path: Path
    actor: str
    inspection_token: str
    confirmed: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoverWorkbenchProjectResult:
    project_id: str
    recovery_run: RecoveryRun
    recovery_items: Sequence[RecoveryItem]
    remaining_candidate_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchNodesRequest:
    project_id: str
    database_path: Path
    query: Optional[str] = None
    source_id: Optional[str] = None
    kinds: Sequence[NodeKind] = ()
    formats: Sequence[NodeFormat] = ()
    statuses: Sequence[NodeProcessingStatus] = ()
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchNodeHit:
    node: Node
    parent_node_id: Optional[str]
    relationship_type: Optional[RelationshipType]


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchNodesResult:
    project_id: str
    items: Sequence[SearchNodeHit]
    total: int
    limit: int
    offset: int
    has_more: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportManifestRequest:
    project_id: str
    database_path: Path
    actor: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportManifestResult:
    project_id: str
    manifest_id: str
    schema_version: str
    generated_at: datetime
    storage_key: str
    manifest_path: Path
    size: int
    sha256: str
    included_event_count: int
    last_included_event_id: Optional[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class GetProjectTreeRequest:
    project_id: str
    database_path: Path


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectTreeItem:
    node: Node
    parent_node_id: Optional[str]
    relationship_type: Optional[RelationshipType]
    ordinal: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectTreeResult:
    project: Project
    sources: Sequence[Source]
    items: Sequence[ProjectTreeItem]


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenNodeRequest:
    project_id: str
    database_path: Path
    node_id: str
    actor: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenNodeResult:
    project_id: str
    node_id: str
    artifact_id: str
    format: NodeFormat
    path: Path
    handed_off_at: datetime
