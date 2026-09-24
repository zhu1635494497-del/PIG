from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol, Sequence

from pig.domain.entities import (
    Artifact,
    ImportSession,
    ImportSessionItem,
    LineageRecord,
    Node,
    NodeMetadata,
    NodeRelationship,
    ProcessingAttempt,
    ProcessingError,
    ProcessingEvent,
    ProcessingJob,
    Project,
    RecoveryItem,
    RecoveryRun,
    OriginalArtifact,
    OriginalSnapshot,
    OriginalSnapshotEntry,
    Source,
    SourceEntryLocator,
    WorkingArtifact,
    WorkingRevision,
    WorkspaceItem,
    WorkspacePlacement,
)
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    AttemptStatus,
    ImportSessionStatus,
    ImportItemStatus,
    JobStatus,
    NodeFormat,
    NodeKind,
    NodeProcessingStatus,
    ProjectStatus,
    RecoveryItemStatus,
    RecoveryRunStatus,
    OriginalSnapshotStatus,
    SourceStatus,
    ProcessingStage,
    WorkingContentStatus,
    WorkingRevisionRole,
    WorkspaceItemLifecycleStatus,
    WorkspaceMaterializationStatus,
)


class ProjectRepository(Protocol):
    def add(self, project: Project) -> None: ...

    def get(self, project_id: str) -> Optional[Project]: ...

    def get_singleton(self) -> Optional[Project]: ...

    def update_status(
        self,
        project_id: str,
        expected_status: ProjectStatus,
        new_status: ProjectStatus,
        updated_at: datetime,
    ) -> Project: ...

    def advance_workspace_revision(
        self,
        project_id: str,
        expected_revision: int,
        *,
        updated_at: datetime,
    ) -> Project: ...


class ImportRepository(Protocol):
    def add_session(self, session: ImportSession) -> None: ...

    def get_session(self, session_id: str) -> Optional[ImportSession]: ...

    def sessions_for_project(self, project_id: str) -> Sequence[ImportSession]: ...

    def get_session_by_correlation(
        self, project_id: str, correlation_id: str
    ) -> Optional[ImportSession]: ...

    def add_session_item(self, item: ImportSessionItem) -> None: ...

    def items_for_session(
        self, import_session_id: str
    ) -> Sequence[ImportSessionItem]: ...

    def update_session_item(
        self,
        item_id: str,
        expected_status: ImportItemStatus,
        new_status: ImportItemStatus,
        *,
        updated_at: datetime,
        snapshot_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> ImportSessionItem: ...

    def update_session_status(
        self,
        session_id: str,
        expected_status: ImportSessionStatus,
        new_status: ImportSessionStatus,
        *,
        accepted_item_count: Optional[int] = None,
        failed_item_count: Optional[int] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> ImportSession: ...

    def add_snapshot(self, snapshot: OriginalSnapshot) -> None: ...

    def get_snapshot(self, snapshot_id: str) -> Optional[OriginalSnapshot]: ...

    def snapshots_for_project(
        self, project_id: str
    ) -> Sequence[OriginalSnapshot]: ...

    def update_snapshot_status(
        self,
        snapshot_id: str,
        expected_status: OriginalSnapshotStatus,
        new_status: OriginalSnapshotStatus,
        *,
        verified_at: Optional[datetime] = None,
    ) -> OriginalSnapshot: ...

    def add_original_artifact(self, artifact: OriginalArtifact) -> None: ...

    def get_original_artifact(
        self, artifact_id: str
    ) -> Optional[OriginalArtifact]: ...

    def original_artifacts_for_snapshot(
        self, snapshot_id: str
    ) -> Sequence[OriginalArtifact]: ...

    def update_original_artifact_integrity(
        self,
        artifact_id: str,
        expected_status: ArtifactIntegrityStatus,
        new_status: ArtifactIntegrityStatus,
    ) -> OriginalArtifact: ...

    def bind_original_artifact_to_source_node(
        self, artifact_id: str, source_node_id: str
    ) -> OriginalArtifact: ...

    def add_snapshot_entry(self, entry: OriginalSnapshotEntry) -> None: ...

    def get_snapshot_entry(
        self, entry_id: str
    ) -> Optional[OriginalSnapshotEntry]: ...

    def entries_for_snapshot(
        self, snapshot_id: str
    ) -> Sequence[OriginalSnapshotEntry]: ...

    def bind_snapshot_entry_to_source_node(
        self, entry_id: str, source_node_id: str
    ) -> OriginalSnapshotEntry: ...


class WorkspaceRepository(Protocol):
    def add_item(
        self,
        item: WorkspaceItem,
        placement: WorkspacePlacement,
        *,
        allow_container_parent: bool = False,
    ) -> None: ...

    def get_item(self, item_id: str) -> Optional[WorkspaceItem]: ...

    def items_for_project(
        self, project_id: str, *, include_deleted: bool = False
    ) -> Sequence[WorkspaceItem]: ...

    def get_placement(self, item_id: str) -> Optional[WorkspacePlacement]: ...

    def children_for_parent(
        self,
        project_id: str,
        parent_id: Optional[str],
        *,
        include_deleted: bool = False,
    ) -> Sequence[tuple[WorkspaceItem, WorkspacePlacement]]: ...

    def is_effectively_active(self, item_id: str) -> bool: ...

    def insert_item(
        self,
        item: WorkspaceItem,
        *,
        parent_id: Optional[str],
        ordinal: int,
        updated_at: datetime,
    ) -> WorkspacePlacement: ...

    def move_item(
        self,
        item_id: str,
        *,
        new_parent_id: Optional[str],
        new_ordinal: int,
        updated_at: datetime,
    ) -> WorkspacePlacement: ...

    def soft_delete_item(
        self,
        item_id: str,
        *,
        updated_at: datetime,
    ) -> tuple[WorkspaceItem, WorkspacePlacement]: ...

    def restore_item(
        self,
        item_id: str,
        *,
        updated_at: datetime,
    ) -> tuple[WorkspaceItem, WorkspacePlacement, bool]: ...

    def purge_items(
        self,
        item_ids: Sequence[str],
        *,
        updated_at: datetime,
    ) -> Sequence[WorkspaceItem]: ...

    def update_lifecycle(
        self,
        item_id: str,
        expected_status: WorkspaceItemLifecycleStatus,
        new_status: WorkspaceItemLifecycleStatus,
        *,
        updated_at: datetime,
        deleted_at: Optional[datetime],
    ) -> WorkspaceItem: ...

    def update_materialization_status(
        self,
        item_id: str,
        expected_status: WorkspaceMaterializationStatus,
        new_status: WorkspaceMaterializationStatus,
        *,
        updated_at: datetime,
    ) -> WorkspaceItem: ...

    def add_working_artifact(self, artifact: WorkingArtifact) -> None: ...

    def get_working_artifact(
        self, artifact_id: str
    ) -> Optional[WorkingArtifact]: ...

    def working_artifact_for_item(
        self, item_id: str
    ) -> Optional[WorkingArtifact]: ...

    def update_working_content(
        self,
        artifact_id: str,
        expected_status: WorkingContentStatus,
        new_status: WorkingContentStatus,
        *,
        expected_updated_at: datetime,
        current_size: Optional[int],
        current_sha256: Optional[str],
        last_checked_at: datetime,
        updated_at: datetime,
    ) -> WorkingArtifact: ...

    def set_working_revision(self, revision: WorkingRevision) -> WorkingRevision: ...

    def working_revision_for_artifact(
        self, artifact_id: str, role: WorkingRevisionRole
    ) -> Optional[WorkingRevision]: ...

    def working_revisions_for_artifact(
        self, artifact_id: str
    ) -> Sequence[WorkingRevision]: ...


class CatalogRepository(Protocol):
    def add_source(self, source: Source) -> None: ...

    def get_source(self, source_id: str) -> Optional[Source]: ...

    def sources_for_project(self, project_id: str) -> Sequence[Source]: ...

    def source_for_snapshot(self, snapshot_id: str) -> Optional[Source]: ...

    def update_source_status(
        self,
        source_id: str,
        expected_status: SourceStatus,
        new_status: SourceStatus,
        verified_at: Optional[datetime],
    ) -> Source: ...

    def register_root(self, node: Node) -> None: ...

    def register_child(
        self, node: Node, relationship: NodeRelationship
    ) -> None: ...

    def get_node(self, node_id: str) -> Optional[Node]: ...

    def node_count_for_project(self, project_id: str) -> int: ...

    def nodes_for_project(
        self,
        project_id: str,
        status: Optional[NodeProcessingStatus] = None,
    ) -> Sequence[Node]: ...

    def search_nodes(
        self,
        project_id: str,
        *,
        query: Optional[str],
        source_id: Optional[str],
        kinds: Sequence[NodeKind],
        formats: Sequence[NodeFormat],
        statuses: Sequence[NodeProcessingStatus],
        limit: int,
        offset: int,
    ) -> tuple[Sequence[Node], int]: ...

    def update_node_detection(
        self,
        node_id: str,
        *,
        kind: NodeKind,
        format: NodeFormat,
        method: str,
        confidence: float,
        details: dict[str, object],
        updated_at: datetime,
    ) -> Node: ...

    def update_node_status(
        self,
        node_id: str,
        expected_status: NodeProcessingStatus,
        new_status: NodeProcessingStatus,
        updated_at: datetime,
    ) -> Node: ...

    def add_artifact(self, artifact: Artifact) -> None: ...

    def artifacts_for_node(self, node_id: str) -> Sequence[Artifact]: ...

    def artifacts_for_project(self, project_id: str) -> Sequence[Artifact]: ...

    def update_artifact_integrity(
        self,
        artifact_id: str,
        expected_status: ArtifactIntegrityStatus,
        new_status: ArtifactIntegrityStatus,
        observed_at: Optional[datetime],
    ) -> Artifact: ...

    def relationship_for_child(
        self, child_node_id: str
    ) -> Optional[NodeRelationship]: ...

    def relationships_for_project(
        self, project_id: str
    ) -> Sequence[NodeRelationship]: ...

    def add_entry_locator(self, locator: SourceEntryLocator) -> None: ...

    def entry_locator_for_relationship(
        self, relationship_id: str
    ) -> Optional[SourceEntryLocator]: ...

    def entry_locator_for_child(
        self, child_node_id: str
    ) -> Optional[SourceEntryLocator]: ...

    def children_of(self, parent_node_id: str) -> Sequence[Node]: ...

    def lineage_for(self, descendant_node_id: str) -> Sequence[LineageRecord]: ...

    def lineage_for_project(
        self, project_id: str
    ) -> Sequence[LineageRecord]: ...

    def add_metadata(self, metadata: NodeMetadata) -> None: ...

    def metadata_for_node(self, node_id: str) -> Sequence[NodeMetadata]: ...

    def metadata_for_project(self, project_id: str) -> Sequence[NodeMetadata]: ...


class ProcessingRepository(Protocol):
    def add_job(self, job: ProcessingJob) -> None: ...

    def get_job(self, job_id: str) -> Optional[ProcessingJob]: ...

    def jobs_for_project(
        self,
        project_id: str,
        statuses: Optional[Sequence[JobStatus]] = None,
    ) -> Sequence[ProcessingJob]: ...

    def job_for_import_session(
        self, import_session_id: str
    ) -> Optional[ProcessingJob]: ...

    def update_job_status(
        self,
        job_id: str,
        expected_status: JobStatus,
        new_status: JobStatus,
        *,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        warning_count: Optional[int] = None,
        error_count: Optional[int] = None,
    ) -> ProcessingJob: ...

    def add_attempt(self, attempt: ProcessingAttempt) -> None: ...

    def get_attempt(self, attempt_id: str) -> Optional[ProcessingAttempt]: ...

    def attempts_for_project(
        self,
        project_id: str,
        statuses: Optional[Sequence[AttemptStatus]] = None,
    ) -> Sequence[ProcessingAttempt]: ...

    def next_attempt_number(self, node_id: str) -> int: ...

    def update_attempt_status(
        self,
        attempt_id: str,
        expected_status: AttemptStatus,
        new_status: AttemptStatus,
        *,
        handler_name: Optional[str] = None,
        handler_version: Optional[str] = None,
        backend_name: Optional[str] = None,
        backend_version: Optional[str] = None,
        backend_sha256: Optional[str] = None,
        stage: Optional[ProcessingStage] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        error: Optional[ProcessingError] = None,
    ) -> ProcessingAttempt: ...

    def append_event(self, event: ProcessingEvent) -> None: ...

    def events_for_project(self, project_id: str) -> Sequence[ProcessingEvent]: ...


class RecoveryRepository(Protocol):
    def add_run(self, run: RecoveryRun) -> None: ...

    def get_run(self, run_id: str) -> Optional[RecoveryRun]: ...

    def runs_for_project(self, project_id: str) -> Sequence[RecoveryRun]: ...

    def update_run_status(
        self,
        run_id: str,
        expected_status: RecoveryRunStatus,
        new_status: RecoveryRunStatus,
        *,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        recovered_count: Optional[int] = None,
        failed_count: Optional[int] = None,
    ) -> RecoveryRun: ...

    def add_item(self, item: RecoveryItem) -> None: ...

    def items_for_run(self, run_id: str) -> Sequence[RecoveryItem]: ...

    def update_item_status(
        self,
        item_id: str,
        expected_status: RecoveryItemStatus,
        new_status: RecoveryItemStatus,
        *,
        updated_at: datetime,
        size: Optional[int] = None,
        sha256: Optional[str] = None,
        recovery_storage_key: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> RecoveryItem: ...


class UnitOfWork(Protocol):
    projects: ProjectRepository
    imports: ImportRepository
    workspace: WorkspaceRepository
    catalog: CatalogRepository
    processing: ProcessingRepository
    recovery: RecoveryRepository

    def __enter__(self) -> "UnitOfWork": ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
