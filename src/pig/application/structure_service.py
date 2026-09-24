from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable, Optional
from uuid import uuid4

from pig.application.contracts import (
    InspectImportSessionRequest,
    InspectImportSessionResult,
    MaterializeWorkspaceItemRequest,
    MaterializeWorkspaceItemResult,
)
from pig.application.errors import ApplicationError
from pig.application.ports import (
    InspectionCacheStore,
    OriginalSnapshotStore,
    ProjectDatabaseProvider,
    StoredWorkingContent,
    WorkingArtifactStore,
    WorkingVersionStore,
)
from pig.domain.detection import detect_node_format
from pig.domain.entities import (
    Node,
    NodeMetadata,
    NodeRelationship,
    OriginalArtifact,
    OriginalSnapshotEntry,
    ProcessingAttempt,
    ProcessingError,
    ProcessingEvent,
    ProcessingJob,
    Source,
    SourceEntryLocator,
    WorkingArtifact,
    WorkingRevision,
    WorkspaceItem,
    WorkspacePlacement,
)
from pig.domain.enums import (
    AttemptStatus,
    ErrorCode,
    ErrorCategory,
    EventSeverity,
    EventType,
    ImportItemStatus,
    ImportSessionStatus,
    JobStatus,
    JobType,
    MaterializationLocatorKind,
    NodeFormat,
    NodeKind,
    NodeProcessingStatus,
    OriginalSnapshotEntryKind,
    OriginalSnapshotStatus,
    ProjectStatus,
    ProcessingStage,
    RelationshipType,
    WorkingContentStatus,
    WorkingRevisionRole,
    WorkspaceItemKind,
    WorkspaceItemLifecycleStatus,
    WorkspaceMaterializationStatus,
)
from pig.domain.exceptions import EntityNotFoundError
from pig.domain.model_version import WORKBENCH_MODEL_VERSION
from pig.domain.paths import archive_child_path, folder_child_path, logical_segment, safe_display_name
from pig.domain.processing_policy import ProcessingPolicy
from pig.infrastructure.filesystem.staging_manifest import finalize_staging_manifest
from pig.handlers.base import HandlerOutcomeError
from pig.handlers.workbench import (
    BackendIdentity,
    SnapshotFolderStructureHandler,
    WorkbenchStructureHandler,
    WorkbenchStructureHandlerRegistry,
)


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


_USABLE = {NodeProcessingStatus.SUCCESS, NodeProcessingStatus.PARTIAL_SUCCESS}
_ERROR = {
    NodeProcessingStatus.CORRUPTED,
    NodeProcessingStatus.FAILED,
    NodeProcessingStatus.SOURCE_MISSING,
    NodeProcessingStatus.SOURCE_CHANGED,
}
_TRUSTED_SUFFIX = {
    NodeFormat.XLSX: ".xlsx",
    NodeFormat.XLS: ".xls",
    NodeFormat.CSV: ".csv",
    NodeFormat.PDF: ".pdf",
    NodeFormat.DOCX: ".docx",
    NodeFormat.DOC: ".doc",
    NodeFormat.PPTX: ".pptx",
    NodeFormat.PPT: ".ppt",
    NodeFormat.TXT: ".txt",
    NodeFormat.JPG: ".jpg",
    NodeFormat.JPEG: ".jpeg",
    NodeFormat.PNG: ".png",
    NodeFormat.UNKNOWN: ".bin",
}


@dataclass(slots=True)
class _PlannedNode:
    node: Node
    parent_node_id: Optional[str]
    relationship_id: Optional[str]
    relationship_type: Optional[RelationshipType]
    relationship_ordinal: int
    locator_kind: Optional[MaterializationLocatorKind] = None
    snapshot_entry_id: Optional[str] = None
    member_ordinal: Optional[int] = None
    expected_name: Optional[str] = None
    member_role: Optional[str] = None
    error_code: Optional[ErrorCode] = None
    error_category: Optional[ErrorCategory] = None
    error_message: Optional[str] = None
    error_retryable: bool = False
    backend_identity: Optional[BackendIdentity] = None
    metadata: tuple = ()


@dataclass(slots=True)
class _SourcePlan:
    source: Source
    root_ordinal: int
    nodes: list[_PlannedNode]


class WorkbenchStructureService:
    """Workbench actions for eager Container structure and lazy terminal bytes."""

    def __init__(
        self,
        *,
        database: ProjectDatabaseProvider,
        originals: OriginalSnapshotStore,
        inspection_cache: InspectionCacheStore,
        working_store: WorkingArtifactStore,
        version_store: WorkingVersionStore,
        folder_handler: SnapshotFolderStructureHandler,
        handlers: WorkbenchStructureHandlerRegistry,
        clock: Clock = _utc_now,
        id_generator: IdGenerator = _new_id,
    ) -> None:
        self._database = database
        self._originals = originals
        self._inspection_cache = inspection_cache
        self._working_store = working_store
        self._version_store = version_store
        self._folder = folder_handler
        self._handlers = handlers
        self._clock = clock
        self._new_id = id_generator

    def inspect(
        self, request: InspectImportSessionRequest
    ) -> InspectImportSessionResult:
        project_id = self._required(request.project_id, "project_id")
        actor = self._required(request.actor, "actor")
        database_path = self._absolute(request.database_path)
        project_path = database_path.resolve(strict=False).parent
        operation_id = self._new_id()

        with self._database.unit_of_work(database_path) as uow:
            project = self._project(uow, project_id, database_path)
            session = uow.imports.get_session(request.import_session_id)
            if session is None or session.project_id != project_id:
                raise EntityNotFoundError(
                    f"import session not found: {request.import_session_id}"
                )
            existing_job = uow.processing.job_for_import_session(session.id)
            if session.status != ImportSessionStatus.INSPECTING:
                if session.status in {
                    ImportSessionStatus.SUCCESS,
                    ImportSessionStatus.PARTIAL_SUCCESS,
                    ImportSessionStatus.FAILED,
                } and existing_job is not None:
                    return self._existing_inspection_result(uow, session, existing_job)
                raise ApplicationError(
                    "IMPORT_SESSION_NOT_INSPECTABLE",
                    "import session is not awaiting structure inspection",
                    {"status": session.status.value},
                )
            if existing_job is not None:
                raise ApplicationError(
                    "INSPECTION_RECOVERY_REQUIRED",
                    "the session already has an inspection job",
                )
            if (
                session.expected_workspace_revision is not None
                and project.workspace_revision
                != session.expected_workspace_revision
            ):
                self._interrupt_pending_add(
                    uow,
                    session,
                    project,
                    actor=actor,
                    correlation_id=operation_id,
                    reason="workspace_revision_conflict",
                )
                uow.commit()
                raise ApplicationError(
                    "WORKSPACE_REVISION_CONFLICT",
                    "Workspace changed while the Add operation was pending",
                    {
                        "expected": session.expected_workspace_revision,
                        "actual": project.workspace_revision,
                    },
                )
            if session.target_workspace_parent_id is not None:
                target = uow.workspace.get_item(session.target_workspace_parent_id)
                if (
                    target is None
                    or target.project_id != project_id
                    or target.item_kind != WorkspaceItemKind.FOLDER
                    or not uow.workspace.is_effectively_active(target.id)
                ):
                    self._interrupt_pending_add(
                        uow,
                        session,
                        project,
                        actor=actor,
                        correlation_id=operation_id,
                        reason="workspace_target_invalid",
                    )
                    uow.commit()
                    raise ApplicationError(
                        "INVALID_WORKSPACE_TARGET",
                        "the Add target is no longer an active ordinary folder",
                    )
            items = tuple(uow.imports.items_for_session(session.id))
            captured = tuple(
                item
                for item in items
                if item.status == ImportItemStatus.CAPTURED
                and item.snapshot_id is not None
            )
            existing_node_count = uow.catalog.node_count_for_project(project_id)

        plans: list[_SourcePlan] = []
        planned_new_nodes = 0
        with self._inspection_cache.begin(project_path, operation_id) as cache:
            for item in captured:
                with self._database.unit_of_work(database_path) as uow:
                    snapshot = uow.imports.get_snapshot(item.snapshot_id)
                    source = uow.catalog.source_for_snapshot(item.snapshot_id)
                    entries = tuple(uow.imports.entries_for_snapshot(item.snapshot_id))
                    artifacts = tuple(
                        uow.imports.original_artifacts_for_snapshot(item.snapshot_id)
                    )
                    root = (
                        None
                        if source is None or source.root_node_id is None
                        else uow.catalog.get_node(source.root_node_id)
                    )
                if (
                    snapshot is None
                    or snapshot.status != OriginalSnapshotStatus.READY
                    or source is None
                    or root is None
                ):
                    continue
                try:
                    plan = self._plan_source(
                        project_path=project_path,
                        source=source,
                        root=root,
                        entries=entries,
                        artifacts=artifacts,
                        root_ordinal=item.ordinal,
                        cache=cache,
                        policy=request.policy,
                    )
                except HandlerOutcomeError as exc:
                    root.status = exc.status
                    plan = _SourcePlan(
                        source=source,
                        root_ordinal=item.ordinal,
                        nodes=[
                            _PlannedNode(
                                node=root,
                                parent_node_id=None,
                                relationship_id=None,
                                relationship_type=None,
                                relationship_ordinal=item.ordinal,
                                error_code=exc.code,
                                error_category=exc.category,
                                error_message=exc.message,
                                error_retryable=exc.retryable,
                            )
                        ],
                    )
                additional = max(0, len(plan.nodes) - 1)
                if (
                    existing_node_count + planned_new_nodes + additional
                    > request.policy.max_node_count
                ):
                    plan.nodes[0].node.status = NodeProcessingStatus.LIMIT_EXCEEDED
                    plan.nodes[0].error_code = ErrorCode.MAX_NODE_COUNT_EXCEEDED
                    plan.nodes = [plan.nodes[0]]
                    additional = 0
                planned_new_nodes += additional
                plans.append(plan)

        all_nodes = [planned for plan in plans for planned in plan.nodes]
        warning_count = sum(
            planned.node.status != NodeProcessingStatus.SUCCESS
            for planned in all_nodes
        )
        error_count = sum(planned.node.status in _ERROR for planned in all_nodes)
        usable_sources = sum(plan.nodes[0].node.status in _USABLE for plan in plans)
        if not plans or usable_sources == 0:
            session_status = ImportSessionStatus.FAILED
            project_status = ProjectStatus.FAILED
            job_status = JobStatus.FAILED
        elif (
            usable_sources == len(plans)
            and warning_count == 0
            and session.failed_item_count == 0
        ):
            session_status = ImportSessionStatus.SUCCESS
            project_status = ProjectStatus.READY
            job_status = JobStatus.SUCCESS
        else:
            session_status = ImportSessionStatus.PARTIAL_SUCCESS
            project_status = ProjectStatus.READY_WITH_WARNINGS
            job_status = JobStatus.PARTIAL_SUCCESS

        job_id = self._new_id()
        correlation_id = operation_id
        now = self._clock()
        workspace_count = 0
        with self._database.unit_of_work(database_path) as uow:
            session = uow.imports.get_session(request.import_session_id)
            if session is None or session.status != ImportSessionStatus.INSPECTING:
                raise ApplicationError(
                    "CONCURRENT_INSPECTION", "import session changed during inspection"
                )
            project = self._project(uow, project_id, database_path)
            if (
                session.expected_workspace_revision is not None
                and project.workspace_revision
                != session.expected_workspace_revision
            ):
                self._interrupt_pending_add(
                    uow,
                    session,
                    project,
                    actor=actor,
                    correlation_id=operation_id,
                    reason="workspace_revision_conflict",
                )
                uow.commit()
                raise ApplicationError(
                    "WORKSPACE_REVISION_CONFLICT",
                    "Workspace changed while the Add operation was pending",
                    {
                        "expected": session.expected_workspace_revision,
                        "actual": project.workspace_revision,
                    },
                )
            target_parent_id = session.target_workspace_parent_id
            if target_parent_id is not None:
                target = uow.workspace.get_item(target_parent_id)
                if (
                    target is None
                    or target.item_kind != WorkspaceItemKind.FOLDER
                    or not uow.workspace.is_effectively_active(target.id)
                ):
                    self._interrupt_pending_add(
                        uow,
                        session,
                        project,
                        actor=actor,
                        correlation_id=operation_id,
                        reason="workspace_target_invalid",
                    )
                    uow.commit()
                    raise ApplicationError(
                        "INVALID_WORKSPACE_TARGET",
                        "the Add target is no longer an active ordinary folder",
                    )
            root_ordinal_base = len(
                uow.workspace.children_for_parent(project_id, target_parent_id)
            )
            job = ProcessingJob(
                id=job_id,
                project_id=project_id,
                import_session_id=session.id,
                type=JobType.IMPORT_SOURCE,
                status=JobStatus.QUEUED,
                requested_by=actor,
                policy_snapshot=request.policy.snapshot(),
                created_at=now,
            )
            uow.processing.add_job(job)
            self._event(
                uow,
                EventType.JOB_CREATED,
                project_id,
                actor,
                correlation_id,
                job_id=job_id,
                import_session_id=session.id,
                new_status=JobStatus.QUEUED.value,
                details={"job_type": JobType.IMPORT_SOURCE.value},
            )
            uow.processing.update_job_status(
                job_id, JobStatus.QUEUED, JobStatus.RUNNING, started_at=now
            )
            self._event(
                uow,
                EventType.JOB_STARTED,
                project_id,
                actor,
                correlation_id,
                job_id=job_id,
                import_session_id=session.id,
                previous_status=JobStatus.QUEUED.value,
                new_status=JobStatus.RUNNING.value,
            )
            if project.status == ProjectStatus.IMPORTING:
                uow.projects.update_status(
                    project_id, ProjectStatus.IMPORTING, ProjectStatus.PROCESSING, now
                )
                self._event(
                    uow,
                    EventType.PROJECT_STATUS_CHANGED,
                    project_id,
                    actor,
                    correlation_id,
                    job_id=job_id,
                    import_session_id=session.id,
                    previous_status=ProjectStatus.IMPORTING.value,
                    new_status=ProjectStatus.PROCESSING.value,
                    details={"reason": "structure_inspection_started"},
                )

            workspace_ids: dict[str, str] = {}
            next_child_ordinal: dict[str, int] = {}
            for plan_index, plan in enumerate(plans):
                for planned in plan.nodes:
                    node = planned.node
                    if planned.parent_node_id is None:
                        persisted = uow.catalog.get_node(node.id)
                        if persisted is None:
                            raise EntityNotFoundError(f"root node not found: {node.id}")
                        uow.catalog.update_node_detection(
                            node.id,
                            kind=node.kind,
                            format=node.format,
                            method=node.detection_method or "workbench",
                            confidence=node.detection_confidence or 0.0,
                            details=dict(node.detection_details),
                            updated_at=now,
                        )
                        self._advance_node(uow, node.id, persisted.status, node.status, now)
                    else:
                        relationship = NodeRelationship(
                            id=planned.relationship_id or self._new_id(),
                            project_id=project_id,
                            parent_node_id=planned.parent_node_id,
                            child_node_id=node.id,
                            type=planned.relationship_type or RelationshipType.FOLDER_CONTAINS,
                            ordinal=planned.relationship_ordinal,
                            discovery_key=node.discovery_key,
                            created_by_job_id=job_id,
                            created_at=now,
                        )
                        initial = replace(
                            node, status=NodeProcessingStatus.DISCOVERED
                        )
                        uow.catalog.register_child(initial, relationship)
                        self._advance_node(
                            uow,
                            node.id,
                            NodeProcessingStatus.DISCOVERED,
                            node.status,
                            now,
                        )
                        if planned.locator_kind is not None:
                            uow.catalog.add_entry_locator(
                                SourceEntryLocator(
                                    relationship_id=relationship.id,
                                    project_id=project_id,
                                    child_node_id=node.id,
                                    kind=planned.locator_kind,
                                    snapshot_entry_id=planned.snapshot_entry_id,
                                    member_ordinal=planned.member_ordinal,
                                    expected_name=planned.expected_name,
                                    member_role=planned.member_role,
                                    created_at=now,
                                )
                            )
                        self._event(
                            uow,
                            EventType.RELATIONSHIP_CREATED,
                            project_id,
                            actor,
                            correlation_id,
                            job_id=job_id,
                            source_id=plan.source.id,
                            node_id=node.id,
                            details={"relationship_id": relationship.id},
                        )
                    for descriptor in planned.metadata:
                        uow.catalog.add_metadata(
                            NodeMetadata(
                                id=self._new_id(),
                                project_id=project_id,
                                node_id=node.id,
                                namespace=descriptor.namespace,
                                key=descriptor.key,
                                value_type=descriptor.value_type,
                                provenance=descriptor.provenance,
                                created_at=now,
                                value_text=descriptor.value_text,
                                value_integer=descriptor.value_integer,
                                value_real=descriptor.value_real,
                                value_boolean=descriptor.value_boolean,
                                value_datetime=descriptor.value_datetime,
                                value_json=descriptor.value_json,
                                observed_at=now,
                            )
                        )
                    attempt_id = self._persist_attempt(
                        uow,
                        planned,
                        actor=actor,
                        correlation_id=correlation_id,
                        job_id=job_id,
                        now=now,
                    )
                    self._node_events(
                        uow,
                        planned,
                        plan.source,
                        actor,
                        correlation_id,
                        job_id,
                        attempt_id=attempt_id,
                    )

                    item_id = self._new_id()
                    workspace_ids[node.id] = item_id
                    parent_item_id = (
                        target_parent_id
                        if planned.parent_node_id is None
                        else workspace_ids[planned.parent_node_id]
                    )
                    if planned.parent_node_id is None:
                        workspace_ordinal = root_ordinal_base + plan_index
                    else:
                        workspace_ordinal = next_child_ordinal.get(parent_item_id, 0)
                        next_child_ordinal[parent_item_id] = workspace_ordinal + 1
                    item_kind = self._workspace_kind(node)
                    uow.workspace.add_item(
                        WorkspaceItem(
                            id=item_id,
                            project_id=project_id,
                            origin_source_node_id=node.id,
                            item_kind=item_kind,
                            display_name=node.display_name,
                            lifecycle_status=WorkspaceItemLifecycleStatus.ACTIVE,
                            materialization_status=WorkspaceMaterializationStatus.VIRTUAL,
                            created_at=now,
                            updated_at=now,
                        ),
                        WorkspacePlacement(
                            workspace_item_id=item_id,
                            project_id=project_id,
                            parent_workspace_item_id=parent_item_id,
                            ordinal=workspace_ordinal,
                            updated_at=now,
                        ),
                        allow_container_parent=True,
                    )
                    workspace_count += 1
                    self._event(
                        uow,
                        EventType.WORKSPACE_ITEM_ADDED,
                        project_id,
                        actor,
                        correlation_id,
                        job_id=job_id,
                        source_id=plan.source.id,
                        node_id=node.id,
                        workspace_item_id=item_id,
                        details={
                            "initial_projection": True,
                            "item_kind": item_kind.value,
                            "parent_workspace_item_id": parent_item_id,
                            "ordinal": workspace_ordinal,
                        },
                    )

            if workspace_count:
                expected_revision = (
                    project.workspace_revision
                    if session.expected_workspace_revision is None
                    else session.expected_workspace_revision
                )
                uow.projects.advance_workspace_revision(
                    project_id,
                    expected_revision,
                    updated_at=now,
                )

            uow.processing.update_job_status(
                job_id,
                JobStatus.RUNNING,
                job_status,
                finished_at=now,
                warning_count=warning_count,
                error_count=error_count,
            )
            self._event(
                uow,
                EventType.JOB_FINISHED,
                project_id,
                actor,
                correlation_id,
                job_id=job_id,
                import_session_id=session.id,
                severity=(
                    EventSeverity.INFO
                    if job_status == JobStatus.SUCCESS
                    else EventSeverity.WARNING
                    if job_status == JobStatus.PARTIAL_SUCCESS
                    else EventSeverity.ERROR
                ),
                previous_status=JobStatus.RUNNING.value,
                new_status=job_status.value,
                details={
                    "warning_count": warning_count,
                    "error_count": error_count,
                },
            )
            uow.imports.update_session_status(
                session.id,
                ImportSessionStatus.INSPECTING,
                session_status,
                finished_at=now,
            )
            current_project = uow.projects.get(project_id)
            if current_project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            if current_project.status == ProjectStatus.PROCESSING:
                uow.projects.update_status(
                    project_id,
                    ProjectStatus.PROCESSING,
                    project_status,
                    now,
                )
                self._event(
                    uow,
                    EventType.PROJECT_STATUS_CHANGED,
                    project_id,
                    actor,
                    correlation_id,
                    job_id=job_id,
                    import_session_id=session.id,
                    previous_status=ProjectStatus.PROCESSING.value,
                    new_status=project_status.value,
                    details={"reason": "structure_inspection_finished"},
                )
            self._event(
                uow,
                EventType.IMPORT_FINISHED
                if session_status != ImportSessionStatus.FAILED
                else EventType.IMPORT_FAILED,
                project_id,
                actor,
                correlation_id,
                job_id=job_id,
                import_session_id=session.id,
                severity=(
                    EventSeverity.INFO
                    if session_status == ImportSessionStatus.SUCCESS
                    else EventSeverity.WARNING
                    if session_status == ImportSessionStatus.PARTIAL_SUCCESS
                    else EventSeverity.ERROR
                ),
                previous_status=ImportSessionStatus.INSPECTING.value,
                new_status=session_status.value,
                details={
                    "source_count": len(plans),
                    "node_count": len(all_nodes),
                    "workspace_item_count": workspace_count,
                    "warning_count": warning_count,
                    "error_count": error_count,
                },
            )
            uow.commit()

        return InspectImportSessionResult(
            project_id=project_id,
            import_session_id=request.import_session_id,
            session_status=session_status,
            job_id=job_id,
            source_count=len(plans),
            node_count=len(all_nodes),
            workspace_item_count=workspace_count,
            warning_count=warning_count,
            error_count=error_count,
        )

    def materialize(
        self, request: MaterializeWorkspaceItemRequest
    ) -> MaterializeWorkspaceItemResult:
        project_id = self._required(request.project_id, "project_id")
        actor = self._required(request.actor, "actor")
        database_path = self._absolute(request.database_path)
        project_path = database_path.resolve(strict=False).parent
        operation_id = self._new_id()
        working_artifact_id = self._new_id()
        with self._database.unit_of_work(database_path) as uow:
            self._project(uow, project_id, database_path)
            item = uow.workspace.get_item(request.workspace_item_id)
            if item is None or item.project_id != project_id:
                raise EntityNotFoundError(
                    f"workspace item not found: {request.workspace_item_id}"
                )
            if item.item_kind != WorkspaceItemKind.FILE or item.origin_source_node_id is None:
                raise ApplicationError(
                    "WORKSPACE_ITEM_NOT_MATERIALIZABLE",
                    "only source-backed terminal files can be materialized",
                )
            existing = uow.workspace.working_artifact_for_item(item.id)
            if existing is not None:
                path = self._working_path(project_path, existing.storage_key)
                return MaterializeWorkspaceItemResult(
                    project_id=project_id,
                    workspace_item_id=item.id,
                    working_artifact=existing,
                    path=path,
                    reused=True,
                )
            node = uow.catalog.get_node(item.origin_source_node_id)
            if node is None or node.status != NodeProcessingStatus.SUCCESS:
                raise ApplicationError(
                    "SOURCE_NODE_NOT_MATERIALIZABLE",
                    "source node is not a successful terminal file",
                    {"status": None if node is None else node.status.value},
                )
            if item.materialization_status not in {
                WorkspaceMaterializationStatus.VIRTUAL,
                WorkspaceMaterializationStatus.FAILED,
                WorkspaceMaterializationStatus.INTERRUPTED,
            }:
                raise ApplicationError(
                    "MATERIALIZATION_ALREADY_ACTIVE",
                    "workspace item is already materializing",
                )
            source = uow.catalog.get_source(node.source_id)
            if source is None or source.root_node_id is None:
                raise ApplicationError(ErrorCode.INTERNAL_ERROR.value, "source root is missing")
            chain = self._relationship_chain(uow, source.root_node_id, node.id)
            root_entry = next(
                (
                    entry
                    for entry in uow.imports.entries_for_snapshot(source.snapshot_id)
                    if entry.source_node_id == source.root_node_id
                ),
                None,
            )
            root_artifact = (
                None
                if root_entry is None or root_entry.artifact_id is None
                else uow.imports.get_original_artifact(root_entry.artifact_id)
            )
            locator_chain = tuple(
                (
                    relationship,
                    uow.catalog.entry_locator_for_relationship(relationship.id),
                )
                for relationship in chain
            )
            previous_status = item.materialization_status
            uow.workspace.update_materialization_status(
                item.id,
                previous_status,
                WorkspaceMaterializationStatus.MATERIALIZING,
                updated_at=self._clock(),
            )
            self._event(
                uow,
                EventType.WORKING_FILE_MATERIALIZATION_STARTED,
                project_id,
                actor,
                operation_id,
                source_id=source.id,
                node_id=node.id,
                workspace_item_id=item.id,
                previous_status=previous_status.value,
                new_status=WorkspaceMaterializationStatus.MATERIALIZING.value,
            )
            uow.commit()

        try:
            with self._inspection_cache.begin(project_path, operation_id) as cache:
                producer = self._materialization_producer(
                    database_path=database_path,
                    project_path=project_path,
                    root_artifact=root_artifact,
                    locator_chain=locator_chain,
                    cache=cache,
                    policy=request.policy,
                )
                stored = self._working_store.materialize(
                    project_path,
                    operation_id,
                    request.workspace_item_id,
                    item.display_name,
                    _TRUSTED_SUFFIX.get(node.format, ".bin"),
                    producer,
                    project_id=project_id,
                    maximum=request.policy.max_single_file_size,
                )
                current_version = self._version_store.initialize(
                    project_path,
                    operation_id,
                    working_artifact_id,
                    stored.storage_key,
                    project_id=project_id,
                    expected_size=stored.size,
                    expected_sha256=stored.sha256,
                    maximum=request.policy.max_single_file_size,
                    chunk_size=request.policy.io_chunk_size,
                    stability_retries=1,
                )
        except BaseException as exc:
            with self._database.unit_of_work(database_path) as uow:
                current = uow.workspace.get_item(request.workspace_item_id)
                if (
                    current is not None
                    and current.materialization_status
                    == WorkspaceMaterializationStatus.MATERIALIZING
                ):
                    terminal = (
                        WorkspaceMaterializationStatus.INTERRUPTED
                        if isinstance(exc, (KeyboardInterrupt, SystemExit))
                        else WorkspaceMaterializationStatus.FAILED
                    )
                    uow.workspace.update_materialization_status(
                        current.id,
                        WorkspaceMaterializationStatus.MATERIALIZING,
                        terminal,
                        updated_at=self._clock(),
                    )
                    self._event(
                        uow,
                        EventType.WORKING_FILE_MATERIALIZATION_FAILED,
                        project_id,
                        actor,
                        operation_id,
                        node_id=current.origin_source_node_id,
                        workspace_item_id=current.id,
                        severity=EventSeverity.ERROR,
                        previous_status=WorkspaceMaterializationStatus.MATERIALIZING.value,
                        new_status=terminal.value,
                        error_code=self._error_from_exception(exc),
                        details={"exception_type": type(exc).__name__},
                    )
                    uow.commit()
            raise

        artifact = WorkingArtifact(
            id=working_artifact_id,
            project_id=project_id,
            workspace_item_id=request.workspace_item_id,
            storage_key=stored.storage_key,
            baseline_size=stored.size,
            baseline_sha256=stored.sha256,
            current_size=stored.size,
            current_sha256=stored.sha256,
            content_status=WorkingContentStatus.CLEAN,
            materialized_at=self._clock(),
            updated_at=self._clock(),
        )
        version_now = self._clock()
        checkpoint = WorkingRevision(
            id=self._new_id(),
            project_id=project_id,
            working_artifact_id=artifact.id,
            role=WorkingRevisionRole.CURRENT_CHECKPOINT,
            storage_key=current_version.storage_key,
            size=current_version.size,
            sha256=current_version.sha256,
            file_modified_at=current_version.file_modified_at,
            detected_at=version_now,
            created_at=version_now,
            updated_at=version_now,
        )
        with self._database.unit_of_work(database_path) as uow:
            uow.workspace.add_working_artifact(artifact)
            uow.workspace.set_working_revision(checkpoint)
            uow.workspace.update_materialization_status(
                request.workspace_item_id,
                WorkspaceMaterializationStatus.MATERIALIZING,
                WorkspaceMaterializationStatus.MATERIALIZED,
                updated_at=self._clock(),
            )
            self._event(
                uow,
                EventType.WORKING_FILE_MATERIALIZED,
                project_id,
                actor,
                operation_id,
                node_id=node.id,
                workspace_item_id=request.workspace_item_id,
                working_artifact_id=artifact.id,
                previous_status=WorkspaceMaterializationStatus.MATERIALIZING.value,
                new_status=WorkspaceMaterializationStatus.MATERIALIZED.value,
                details={"size": stored.size, "sha256": stored.sha256},
            )
            uow.commit()
        finalize_staging_manifest(project_path, f"{operation_id}-working")
        finalize_staging_manifest(project_path, f"{operation_id}-version")
        return MaterializeWorkspaceItemResult(
            project_id=project_id,
            workspace_item_id=request.workspace_item_id,
            working_artifact=artifact,
            path=stored.path,
            reused=False,
        )

    def restore_content(
        self,
        *,
        project_id: str,
        database_path: Path,
        workspace_item_id: str,
        operation_id: str,
        actor: str,
        policy: ProcessingPolicy,
        allow_replace: bool,
    ) -> StoredWorkingContent:
        """Replay immutable Original bytes into an existing stable working path."""
        project_id = self._required(project_id, "project_id")
        self._required(actor, "actor")
        database_path = self._absolute(database_path)
        project_path = database_path.resolve(strict=False).parent
        operation_id = self._required(operation_id, "operation_id")
        with self._database.unit_of_work(database_path) as uow:
            self._project(uow, project_id, database_path)
            item = uow.workspace.get_item(workspace_item_id)
            if (
                item is None
                or item.project_id != project_id
                or item.item_kind != WorkspaceItemKind.FILE
                or item.origin_source_node_id is None
                or not uow.workspace.is_effectively_active(item.id)
            ):
                raise ApplicationError(
                    "WORKSPACE_ITEM_NOT_RESTORABLE",
                    "only active source-backed files can be restored",
                )
            artifact = uow.workspace.working_artifact_for_item(item.id)
            if artifact is None:
                raise ApplicationError(
                    "WORKING_ARTIFACT_NOT_FOUND",
                    "the workspace file has not been materialized",
                )
            node = uow.catalog.get_node(item.origin_source_node_id)
            if node is None or node.status != NodeProcessingStatus.SUCCESS:
                raise ApplicationError(
                    "SOURCE_NODE_NOT_MATERIALIZABLE",
                    "source node is not a successful terminal file",
                )
            source = uow.catalog.get_source(node.source_id)
            if source is None or source.root_node_id is None:
                raise ApplicationError(ErrorCode.INTERNAL_ERROR.value, "source root is missing")
            chain = self._relationship_chain(uow, source.root_node_id, node.id)
            root_entry = next(
                (
                    entry
                    for entry in uow.imports.entries_for_snapshot(source.snapshot_id)
                    if entry.source_node_id == source.root_node_id
                ),
                None,
            )
            root_artifact = (
                None
                if root_entry is None or root_entry.artifact_id is None
                else uow.imports.get_original_artifact(root_entry.artifact_id)
            )
            locator_chain = tuple(
                (
                    relationship,
                    uow.catalog.entry_locator_for_relationship(relationship.id),
                )
                for relationship in chain
            )

        with self._inspection_cache.begin(project_path, operation_id) as cache:
            producer = self._materialization_producer(
                database_path=database_path,
                project_path=project_path,
                root_artifact=root_artifact,
                locator_chain=locator_chain,
                cache=cache,
                policy=policy,
            )
            return self._working_store.restore(
                project_path,
                operation_id,
                artifact.storage_key,
                producer,
                project_id=project_id,
                maximum=policy.max_single_file_size,
                expected_size=artifact.baseline_size,
                expected_sha256=artifact.baseline_sha256,
                allow_replace=allow_replace,
            )

    def _plan_source(
        self,
        *,
        project_path: Path,
        source: Source,
        root: Node,
        entries: tuple[OriginalSnapshotEntry, ...],
        artifacts: tuple[OriginalArtifact, ...],
        root_ordinal: int,
        cache,
        policy: ProcessingPolicy,
    ) -> _SourcePlan:
        artifact_by_id = {artifact.id: artifact for artifact in artifacts}
        root_entry = next((entry for entry in entries if entry.parent_entry_id is None), None)
        if root_entry is None:
            raise ApplicationError(ErrorCode.INTERNAL_ERROR.value, "snapshot root entry is missing")
        plans: list[_PlannedNode] = []
        root_path: Optional[Path] = None
        if root_entry.kind == OriginalSnapshotEntryKind.FOLDER:
            detection = detect_node_format(root.original_name, b"", is_directory=True)
        else:
            artifact = artifact_by_id.get(root_entry.artifact_id or "")
            if artifact is None:
                raise ApplicationError(ErrorCode.INTERNAL_ERROR.value, "snapshot root artifact is missing")
            root_path = self._verified_original_path(project_path, artifact, policy)
            detection = detect_node_format(root.original_name, self._signature(root_path))
        root.kind = detection.kind
        root.format = detection.format
        root.detection_method = detection.method
        root.detection_confidence = detection.confidence
        root.detection_details = detection.details
        root.status = self._initial_result(detection.kind, detection.format)
        root_plan = _PlannedNode(
            node=root,
            parent_node_id=None,
            relationship_id=None,
            relationship_type=None,
            relationship_ordinal=root_ordinal,
        )
        plans.append(root_plan)
        path_for_container: dict[str, Path] = {}
        container_queue: deque[str] = deque()
        if self._handlers.resolve(detection.format) is not None and root_path is not None:
            path_for_container[root.id] = root_path
            container_queue.append(root.id)

        if root_entry.kind == OriginalSnapshotEntryKind.FOLDER:
            root_plan.backend_identity = self._folder.default_backend_identity
            node_for_entry = {root_entry.id: root.id}
            queue = deque([root_entry.id])
            while queue:
                parent_entry_id = queue.popleft()
                parent_node_id = node_for_entry[parent_entry_id]
                parent_node = self._planned_node(plans, parent_node_id)
                for entry in self._folder.list_children(entries, parent_entry_id):
                    if len(plans) >= policy.max_node_count:
                        raise HandlerOutcomeError(
                            status=NodeProcessingStatus.LIMIT_EXCEEDED,
                            code=ErrorCode.MAX_NODE_COUNT_EXCEEDED,
                            category=ErrorCategory.RESOURCE_LIMIT,
                            message="source node count exceeds the configured limit",
                        )
                    node_id = self._new_id()
                    if entry.kind == OriginalSnapshotEntryKind.FOLDER:
                        detection = detect_node_format(entry.original_name, b"", is_directory=True)
                        path = None
                    else:
                        artifact = artifact_by_id.get(entry.artifact_id or "")
                        if artifact is None:
                            raise ApplicationError(ErrorCode.INTERNAL_ERROR.value, "snapshot entry artifact is missing")
                        path = self._verified_original_path(project_path, artifact, policy)
                        detection = detect_node_format(entry.original_name, self._signature(path))
                    node = self._new_node(
                        node_id=node_id,
                        source=source,
                        detection=detection,
                        original_name=entry.original_name,
                        logical_path=folder_child_path(parent_node.logical_path, entry.original_name),
                        depth=parent_node.depth + 1,
                        discovery_key=f"snapshot-entry:{entry.id}",
                        declared_size=(
                            None
                            if entry.artifact_id is None
                            else artifact_by_id[entry.artifact_id].size
                        ),
                    )
                    exceeds_depth = node.depth > policy.max_depth
                    if exceeds_depth:
                        node.status = NodeProcessingStatus.LIMIT_EXCEEDED
                    plans.append(
                        _PlannedNode(
                            node=node,
                            parent_node_id=parent_node_id,
                            relationship_id=self._new_id(),
                            relationship_type=RelationshipType.FOLDER_CONTAINS,
                            relationship_ordinal=entry.ordinal,
                            locator_kind=MaterializationLocatorKind.SNAPSHOT_ENTRY,
                            snapshot_entry_id=entry.id,
                            error_code=(
                                ErrorCode.MAX_DEPTH_EXCEEDED
                                if exceeds_depth
                                else None
                            ),
                        )
                    )
                    node_for_entry[entry.id] = node_id
                    if entry.kind == OriginalSnapshotEntryKind.FOLDER and not exceeds_depth:
                        queue.append(entry.id)
                    elif (
                        self._handlers.resolve(detection.format) is not None
                        and path is not None
                        and not exceeds_depth
                    ):
                        path_for_container[node_id] = path
                        container_queue.append(node_id)

        while container_queue:
            container_id = container_queue.popleft()
            container_plan = self._planned_plan(plans, container_id)
            handler = self._handlers.resolve(container_plan.node.format)
            if handler is None:
                container_plan.node.status = NodeProcessingStatus.UNSUPPORTED
                container_plan.error_code = ErrorCode.UNSUPPORTED_FORMAT
                container_plan.error_category = ErrorCategory.FORMAT
                container_plan.error_message = "no Workbench handler supports this container"
                continue
            container_plan.backend_identity = handler.default_backend_identity
            if container_plan.node.depth >= policy.max_depth:
                container_plan.node.status = NodeProcessingStatus.LIMIT_EXCEEDED
                container_plan.error_code = ErrorCode.MAX_DEPTH_EXCEEDED
                container_plan.error_category = ErrorCategory.RESOURCE_LIMIT
                container_plan.error_message = "container depth exceeds the configured limit"
                continue
            try:
                inspection = handler.inspect(path_for_container[container_id], policy)
            except HandlerOutcomeError as exc:
                container_plan.node.status = exc.status
                container_plan.error_code = exc.code
                container_plan.error_category = exc.category
                container_plan.error_message = exc.message
                container_plan.error_retryable = exc.retryable
                continue
            descriptors = inspection.children
            container_plan.backend_identity = inspection.backend_identity
            container_plan.metadata = tuple(inspection.metadata)
            container_plan.node.status = NodeProcessingStatus.SUCCESS
            directories: dict[tuple[str, ...], str] = {(): container_id}
            for descriptor in descriptors:
                if len(plans) >= policy.max_node_count:
                    container_plan.node.status = NodeProcessingStatus.LIMIT_EXCEEDED
                    container_plan.error_code = ErrorCode.MAX_NODE_COUNT_EXCEEDED
                    break
                if descriptor.blocked_status is not None or not descriptor.safe_parts:
                    node_id = self._new_id()
                    blocked = self._new_node_from_values(
                        node_id=node_id,
                        source=source,
                        kind=NodeKind.FILE,
                        format=NodeFormat.UNKNOWN,
                        original_name=descriptor.original_name,
                        logical_path=f"{container_plan.node.logical_path}!/{logical_segment(descriptor.original_name)}",
                        depth=container_plan.node.depth + 1,
                        discovery_key=(
                            f"{handler.format.value.lower()}-entry:"
                            f"{container_id}:{descriptor.ordinal}"
                        ),
                        declared_size=descriptor.declared_size,
                        status=descriptor.blocked_status or NodeProcessingStatus.SECURITY_BLOCKED,
                    )
                    plans.append(
                        _PlannedNode(
                            node=blocked,
                            parent_node_id=container_id,
                            relationship_id=self._new_id(),
                            relationship_type=descriptor.relationship_type,
                            relationship_ordinal=descriptor.ordinal,
                            error_code=descriptor.error_code,
                            error_category=descriptor.error_category,
                            error_message=(
                                "container child is blocked by format or security policy"
                            ),
                        )
                    )
                    continue
                directory_parts = (
                    descriptor.safe_parts
                    if handler.hierarchical and descriptor.is_directory
                    else descriptor.safe_parts[:-1]
                    if handler.hierarchical
                    else ()
                )
                for length in range(1, len(directory_parts) + 1):
                    parts = directory_parts[:length]
                    if parts in directories:
                        continue
                    parent_parts = parts[:-1]
                    parent_id = directories[parent_parts]
                    parent_node = self._planned_node(plans, parent_id)
                    node_id = self._new_id()
                    directory = self._new_node_from_values(
                        node_id=node_id,
                        source=source,
                        kind=NodeKind.CONTAINER,
                        format=NodeFormat.FOLDER,
                        original_name=parts[-1],
                        logical_path=archive_child_path(container_plan.node.logical_path, parts),
                        depth=parent_node.depth + 1,
                        discovery_key=(
                            f"{handler.format.value.lower()}-dir:"
                            f"{container_id}:{'/'.join(parts)}"
                        ),
                        declared_size=None,
                        status=NodeProcessingStatus.SUCCESS,
                        detection_method="zip_implicit_directory",
                        detection_confidence=1.0,
                    )
                    plans.append(
                        _PlannedNode(
                            node=directory,
                            parent_node_id=parent_id,
                            relationship_id=self._new_id(),
                            relationship_type=(
                                descriptor.relationship_type
                                if parent_id == container_id
                                else RelationshipType.FOLDER_CONTAINS
                            ),
                            relationship_ordinal=descriptor.ordinal,
                        )
                    )
                    directories[parts] = node_id
                if descriptor.is_directory:
                    continue
                parent_id = directories[directory_parts]
                parent_node = self._planned_node(plans, parent_id)
                detection = detect_node_format(descriptor.safe_parts[-1], b"")
                node_id = self._new_id()
                node = self._new_node(
                    node_id=node_id,
                    source=source,
                    detection=detection,
                    original_name=descriptor.safe_parts[-1],
                    logical_path=archive_child_path(
                        container_plan.node.logical_path, descriptor.safe_parts
                    ),
                    depth=parent_node.depth + 1,
                    discovery_key=(
                        f"{handler.format.value.lower()}-entry:"
                        f"{container_id}:{descriptor.ordinal}"
                    ),
                    declared_size=descriptor.declared_size,
                )
                plan = _PlannedNode(
                    node=node,
                    parent_node_id=parent_id,
                    relationship_id=self._new_id(),
                    relationship_type=(
                        descriptor.relationship_type
                        if parent_id == container_id
                        else RelationshipType.FOLDER_CONTAINS
                    ),
                    relationship_ordinal=descriptor.ordinal,
                    locator_kind=descriptor.locator_kind,
                    member_ordinal=descriptor.ordinal,
                    expected_name=descriptor.original_name,
                    member_role=descriptor.member_role,
                )
                plans.append(plan)
                if self._handlers.resolve(detection.format) is not None:
                    try:
                        nested_path = cache.materialize(
                            node_id,
                            lambda output,
                            path=path_for_container[container_id],
                            ordinal=descriptor.ordinal,
                            expected_name=descriptor.original_name,
                            member_role=descriptor.member_role,
                            handler=handler: handler.materialize(
                                path,
                                ordinal,
                                expected_name,
                                member_role,
                                output,
                                policy,
                            ),
                            maximum=policy.max_single_file_size,
                            total_maximum=policy.max_total_expanded_size,
                        )
                    except HandlerOutcomeError as exc:
                        node.status = exc.status
                        plan.error_code = exc.code
                    except ApplicationError as exc:
                        node.status = NodeProcessingStatus.LIMIT_EXCEEDED
                        try:
                            plan.error_code = ErrorCode(exc.code)
                        except ValueError:
                            plan.error_code = ErrorCode.INTERNAL_ERROR
                    else:
                        verified = detect_node_format(
                            descriptor.safe_parts[-1], self._signature(nested_path)
                        )
                        node.kind = verified.kind
                        node.format = verified.format
                        node.detection_method = verified.method
                        node.detection_confidence = verified.confidence
                        node.detection_details = verified.details
                        if self._handlers.resolve(node.format) is None:
                            node.status = NodeProcessingStatus.UNSUPPORTED
                            plan.error_code = ErrorCode.UNSUPPORTED_FORMAT
                            plan.error_category = ErrorCategory.FORMAT
                            plan.error_message = (
                                "nested container signature resolved to an unsupported format"
                            )
                            continue
                        path_for_container[node_id] = nested_path
                        container_queue.append(node_id)

        self._roll_up_container_statuses(plans)
        return _SourcePlan(source=source, root_ordinal=root_ordinal, nodes=plans)

    def _materialization_producer(
        self,
        *,
        database_path: Path,
        project_path: Path,
        root_artifact: Optional[OriginalArtifact],
        locator_chain,
        cache,
        policy: ProcessingPolicy,
    ) -> Callable[[BinaryIO], None]:
        current_container = (
            None
            if root_artifact is None
            else self._verified_original_path(project_path, root_artifact, policy)
        )
        final_producer: Optional[Callable[[BinaryIO], None]] = None
        for index, (_relationship, locator) in enumerate(locator_chain):
            if locator is None:
                continue
            is_last_locator = not any(
                later is not None
                for _, later in locator_chain[index + 1 :]
            )
            if locator.kind == MaterializationLocatorKind.SNAPSHOT_ENTRY:
                with self._database.unit_of_work(database_path) as uow:
                    entry = uow.imports.get_snapshot_entry(locator.snapshot_entry_id or "")
                    artifact = (
                        None
                        if entry is None or entry.artifact_id is None
                        else uow.imports.get_original_artifact(entry.artifact_id)
                    )
                if artifact is None:
                    continue
                path = self._verified_original_path(project_path, artifact, policy)
                current_container = path
                if is_last_locator:
                    final_producer = lambda output, path=path: self._copy_path(
                        path, output, policy.io_chunk_size
                    )
            else:
                handler = self._handlers.resolve_locator(locator.kind)
                if (
                    current_container is None
                    or locator.member_ordinal is None
                    or locator.expected_name is None
                    or locator.member_role is None
                    or handler is None
                ):
                    raise ApplicationError(
                        ErrorCode.INTERNAL_ERROR.value,
                        "container materialization recipe is incomplete",
                    )
                if is_last_locator:
                    final_producer = (
                        lambda output,
                        path=current_container,
                        ordinal=locator.member_ordinal,
                        expected_name=locator.expected_name,
                        member_role=locator.member_role,
                        handler=handler: handler.materialize(
                            path,
                            ordinal,
                            expected_name,
                            member_role,
                            output,
                            policy,
                        )
                    )
                else:
                    current_container = cache.materialize(
                        self._new_id(),
                        lambda output,
                        path=current_container,
                        ordinal=locator.member_ordinal,
                        expected_name=locator.expected_name,
                        member_role=locator.member_role,
                        handler=handler: handler.materialize(
                            path,
                            ordinal,
                            expected_name,
                            member_role,
                            output,
                            policy,
                        ),
                        maximum=policy.max_single_file_size,
                        total_maximum=policy.max_total_expanded_size,
                    )
        if final_producer is None:
            if current_container is None:
                raise ApplicationError(
                    "MATERIALIZATION_RECIPE_MISSING",
                    "source node has no materialization recipe",
                )
            final_producer = lambda output: self._copy_path(
                current_container, output, policy.io_chunk_size
            )
        return final_producer

    @staticmethod
    def _copy_path(path: Path, output: BinaryIO, chunk_size: int) -> None:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                output.write(chunk)

    @staticmethod
    def _signature(path: Path) -> bytes:
        with path.open("rb") as stream:
            return stream.read(8)

    def _verified_original_path(
        self,
        project_path: Path,
        artifact: OriginalArtifact,
        policy: ProcessingPolicy,
    ) -> Path:
        self._originals.verify_artifact(
            project_path, artifact, chunk_size=policy.io_chunk_size
        )
        return self._originals.artifact_path(project_path, artifact)

    def _new_node(self, *, detection, **values) -> Node:
        return self._new_node_from_values(
            kind=detection.kind,
            format=detection.format,
            status=self._initial_result(detection.kind, detection.format),
            detection_method=detection.method,
            detection_confidence=detection.confidence,
            detection_details=detection.details,
            **values,
        )

    def _new_node_from_values(
        self,
        *,
        node_id: str,
        source: Source,
        kind: NodeKind,
        format: NodeFormat,
        original_name: str,
        logical_path: str,
        depth: int,
        discovery_key: str,
        declared_size: Optional[int],
        status: NodeProcessingStatus,
        detection_method: str = "workbench",
        detection_confidence: float = 0.0,
        detection_details: Optional[dict[str, object]] = None,
    ) -> Node:
        now = self._clock()
        return Node(
            id=node_id,
            project_id=source.project_id,
            source_id=source.id,
            kind=kind,
            format=format,
            original_name=original_name,
            display_name=safe_display_name(original_name),
            logical_path=logical_path,
            depth=depth,
            status=status,
            discovery_key=discovery_key,
            declared_size=declared_size,
            detection_method=detection_method,
            detection_confidence=detection_confidence,
            detection_details=detection_details or {},
            created_at=now,
            updated_at=now,
        )

    def _initial_result(
        self, kind: NodeKind, format: NodeFormat
    ) -> NodeProcessingStatus:
        if kind == NodeKind.FILE:
            return NodeProcessingStatus.SUCCESS
        if format == NodeFormat.FOLDER or self._handlers.resolve(format) is not None:
            return NodeProcessingStatus.SUCCESS
        return NodeProcessingStatus.UNSUPPORTED

    @staticmethod
    def _planned_plan(plans: list[_PlannedNode], node_id: str) -> _PlannedNode:
        return next(plan for plan in plans if plan.node.id == node_id)

    @classmethod
    def _planned_node(cls, plans: list[_PlannedNode], node_id: str) -> Node:
        return cls._planned_plan(plans, node_id).node

    @staticmethod
    def _roll_up_container_statuses(plans: list[_PlannedNode]) -> None:
        children: dict[str, list[Node]] = {}
        for plan in plans:
            if plan.parent_node_id is not None:
                children.setdefault(plan.parent_node_id, []).append(plan.node)
        for plan in sorted(plans, key=lambda value: value.node.depth, reverse=True):
            node = plan.node
            if node.kind != NodeKind.CONTAINER or node.status != NodeProcessingStatus.SUCCESS:
                continue
            if any(child.status != NodeProcessingStatus.SUCCESS for child in children.get(node.id, ())):
                node.status = NodeProcessingStatus.PARTIAL_SUCCESS

    @staticmethod
    def _workspace_kind(node: Node) -> WorkspaceItemKind:
        if node.format == NodeFormat.FOLDER:
            return WorkspaceItemKind.FOLDER
        if node.kind == NodeKind.CONTAINER:
            return WorkspaceItemKind.CONTAINER_VIEW
        return WorkspaceItemKind.FILE

    @staticmethod
    def _advance_node(uow, node_id, current, final, now) -> None:
        uow.catalog.update_node_status(
            node_id, current, NodeProcessingStatus.PENDING, now
        )
        uow.catalog.update_node_status(
            node_id,
            NodeProcessingStatus.PENDING,
            NodeProcessingStatus.PROCESSING,
            now,
        )
        uow.catalog.update_node_status(
            node_id, NodeProcessingStatus.PROCESSING, final, now
        )

    def _persist_attempt(
        self,
        uow,
        planned: _PlannedNode,
        *,
        actor: str,
        correlation_id: str,
        job_id: str,
        now: datetime,
    ) -> Optional[str]:
        identity = planned.backend_identity
        if identity is None:
            return None
        attempt_id = self._new_id()
        attempt_number = uow.processing.next_attempt_number(planned.node.id)
        uow.processing.add_attempt(
            ProcessingAttempt(
                id=attempt_id,
                project_id=planned.node.project_id,
                job_id=job_id,
                node_id=planned.node.id,
                attempt_number=attempt_number,
                status=AttemptStatus.QUEUED,
                stage=ProcessingStage.INSPECT_CONTAINER,
                queued_at=now,
            )
        )
        self._event(
            uow,
            EventType.ATTEMPT_QUEUED,
            planned.node.project_id,
            actor,
            correlation_id,
            node_id=planned.node.id,
            job_id=job_id,
            attempt_id=attempt_id,
            new_status=AttemptStatus.QUEUED.value,
        )
        uow.processing.update_attempt_status(
            attempt_id,
            AttemptStatus.QUEUED,
            AttemptStatus.RUNNING,
            handler_name=identity.handler_name,
            handler_version=identity.handler_version,
            backend_name=identity.backend_name,
            backend_version=identity.backend_version,
            backend_sha256=identity.backend_sha256,
            started_at=now,
        )
        self._event(
            uow,
            EventType.ATTEMPT_STARTED,
            planned.node.project_id,
            actor,
            correlation_id,
            node_id=planned.node.id,
            job_id=job_id,
            attempt_id=attempt_id,
            previous_status=AttemptStatus.QUEUED.value,
            new_status=AttemptStatus.RUNNING.value,
            details={
                "handler_name": identity.handler_name,
                "handler_version": identity.handler_version,
                "backend_name": identity.backend_name,
                "backend_version": identity.backend_version,
                **(
                    {}
                    if identity.backend_sha256 is None
                    else {"backend_sha256": identity.backend_sha256}
                ),
            },
        )
        successful = planned.node.status in _USABLE
        final = AttemptStatus.COMPLETED if successful else AttemptStatus.FAILED
        error = None
        if not successful:
            error = ProcessingError(
                code=planned.error_code or ErrorCode.HANDLER_FAILURE,
                category=planned.error_category or ErrorCategory.PROCESSING,
                stage=ProcessingStage.INSPECT_CONTAINER,
                message=planned.error_message or "container inspection did not succeed",
                retryable=planned.error_retryable,
            )
        uow.processing.update_attempt_status(
            attempt_id,
            AttemptStatus.RUNNING,
            final,
            finished_at=now,
            error=error,
        )
        self._event(
            uow,
            EventType.ATTEMPT_FINISHED if successful else EventType.ATTEMPT_FAILED,
            planned.node.project_id,
            actor,
            correlation_id,
            node_id=planned.node.id,
            job_id=job_id,
            attempt_id=attempt_id,
            severity=EventSeverity.INFO if successful else EventSeverity.ERROR,
            previous_status=AttemptStatus.RUNNING.value,
            new_status=final.value,
            error_code=None if error is None else error.code,
        )
        return attempt_id

    def _node_events(
        self,
        uow,
        planned,
        source,
        actor,
        correlation,
        job_id,
        *,
        attempt_id=None,
    ) -> None:
        node = planned.node
        if planned.parent_node_id is not None:
            self._event(
                uow,
                EventType.CHILD_DISCOVERED,
                node.project_id,
                actor,
                correlation,
                job_id=job_id,
                source_id=source.id,
                node_id=node.id,
                attempt_id=attempt_id,
                new_status=NodeProcessingStatus.DISCOVERED.value,
                details={"ordinal": planned.relationship_ordinal},
            )
        self._event(
            uow,
            EventType.NODE_FORMAT_DETECTED,
            node.project_id,
            actor,
            correlation,
            job_id=job_id,
            source_id=source.id,
            node_id=node.id,
            attempt_id=attempt_id,
            details={"format": node.format.value, "method": node.detection_method},
        )
        if node.kind == NodeKind.CONTAINER and node.status in _USABLE:
            self._event(
                uow,
                EventType.CONTAINER_OPENED,
                node.project_id,
                actor,
                correlation,
                job_id=job_id,
                source_id=source.id,
                node_id=node.id,
                details={
                    "handler": (
                        None
                        if planned.backend_identity is None
                        else planned.backend_identity.handler_name
                    ),
                    "backend": (
                        None
                        if planned.backend_identity is None
                        else planned.backend_identity.backend_name
                    ),
                },
                attempt_id=attempt_id,
            )
        event_type = (
            EventType.NODE_PROCESSING_FINISHED
            if node.status in _USABLE
            else EventType.NODE_PROCESSING_FAILED
            if node.status in _ERROR
            else EventType.NODE_PROCESSING_BLOCKED
        )
        self._event(
            uow,
            event_type,
            node.project_id,
            actor,
            correlation,
            job_id=job_id,
            source_id=source.id,
            node_id=node.id,
            attempt_id=attempt_id,
            severity=(
                EventSeverity.INFO
                if node.status == NodeProcessingStatus.SUCCESS
                else EventSeverity.ERROR
                if node.status in _ERROR
                else EventSeverity.WARNING
            ),
            new_status=node.status.value,
            error_code=planned.error_code,
        )

    @staticmethod
    def _relationship_chain(uow, root_id: str, target_id: str):
        chain = []
        current = target_id
        while current != root_id:
            relationship = uow.catalog.relationship_for_child(current)
            if relationship is None:
                raise ApplicationError(
                    "MATERIALIZATION_RECIPE_MISSING",
                    "source relationship chain is incomplete",
                )
            chain.append(relationship)
            current = relationship.parent_node_id
        chain.reverse()
        return tuple(chain)

    @staticmethod
    def _working_path(project_path: Path, storage_key: str) -> Path:
        relative = PurePosixPath(storage_key)
        if relative.is_absolute() or ".." in relative.parts:
            raise ApplicationError("UNSAFE_WORKSPACE", "invalid working storage key")
        path = project_path.joinpath(*relative.parts)
        current = project_path
        for segment in relative.parts:
            current = current / segment
            if current.is_symlink():
                raise ApplicationError("UNSAFE_WORKSPACE", "working path traverses a link")
        if not path.is_file():
            raise ApplicationError(ErrorCode.ARTIFACT_MISSING.value, "Working Artifact is missing")
        return path

    def _existing_inspection_result(self, uow, session, job) -> InspectImportSessionResult:
        snapshot_ids = {
            snapshot.id
            for snapshot in uow.imports.snapshots_for_project(session.project_id)
            if snapshot.import_session_id == session.id
        }
        sources = tuple(
            source
            for source in uow.catalog.sources_for_project(session.project_id)
            if source.snapshot_id in snapshot_ids
        )
        source_ids = {source.id for source in sources}
        nodes = tuple(
            node
            for node in uow.catalog.nodes_for_project(session.project_id)
            if node.source_id in source_ids
        )
        node_ids = {node.id for node in nodes}
        items = tuple(
            item
            for item in uow.workspace.items_for_project(session.project_id)
            if item.origin_source_node_id in node_ids
        )
        return InspectImportSessionResult(
            project_id=session.project_id,
            import_session_id=session.id,
            session_status=session.status,
            job_id=job.id,
            source_count=len(sources),
            node_count=len(nodes),
            workspace_item_count=len(items),
            warning_count=job.warning_count,
            error_count=job.error_count,
        )

    @staticmethod
    def _error_from_exception(exc: BaseException) -> Optional[ErrorCode]:
        if isinstance(exc, HandlerOutcomeError):
            return exc.code
        if isinstance(exc, ApplicationError):
            try:
                return ErrorCode(exc.code)
            except ValueError:
                return ErrorCode.INTERNAL_ERROR
        return ErrorCode.INTERNAL_ERROR

    def _interrupt_pending_add(
        self,
        uow,
        session,
        project,
        *,
        actor: str,
        correlation_id: str,
        reason: str,
    ) -> None:
        now = self._clock()
        uow.imports.update_session_status(
            session.id,
            ImportSessionStatus.INSPECTING,
            ImportSessionStatus.INTERRUPTED,
            finished_at=now,
        )
        self._event(
            uow,
            EventType.IMPORT_INTERRUPTED,
            project.id,
            actor,
            correlation_id,
            severity=EventSeverity.WARNING,
            import_session_id=session.id,
            previous_status=ImportSessionStatus.INSPECTING.value,
            new_status=ImportSessionStatus.INTERRUPTED.value,
            details={"reason": reason},
        )
        if project.status == ProjectStatus.IMPORTING:
            uow.projects.update_status(
                project.id,
                ProjectStatus.IMPORTING,
                ProjectStatus.FAILED,
                now,
            )
            self._event(
                uow,
                EventType.PROJECT_STATUS_CHANGED,
                project.id,
                actor,
                correlation_id,
                severity=EventSeverity.WARNING,
                import_session_id=session.id,
                previous_status=ProjectStatus.IMPORTING.value,
                new_status=ProjectStatus.FAILED.value,
                details={"reason": reason},
            )

    def _event(
        self,
        uow,
        event_type,
        project_id,
        actor,
        correlation_id,
        *,
        severity=EventSeverity.INFO,
        error_code=None,
        details=None,
        **links,
    ) -> None:
        uow.processing.append_event(
            ProcessingEvent(
                id=self._new_id(),
                event_type=event_type,
                project_id=project_id,
                actor=actor,
                occurred_at=self._clock(),
                severity=severity,
                correlation_id=correlation_id,
                error_code=error_code,
                details={} if details is None else details,
                **links,
            )
        )

    @staticmethod
    def _required(value: str, field: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ApplicationError("INVALID_REQUEST", f"{field} must not be empty")
        return normalized

    @staticmethod
    def _absolute(path: Path) -> Path:
        value = Path(path)
        if not value.is_absolute():
            raise ApplicationError("INVALID_REQUEST", "database_path must be absolute")
        return value

    @staticmethod
    def _project(uow, project_id: str, database_path: Path):
        project = uow.projects.get(project_id)
        if project is None:
            raise EntityNotFoundError(f"project not found: {project_id}")
        if project.model_version != WORKBENCH_MODEL_VERSION:
            raise ApplicationError(
                "UNSUPPORTED_PROJECT_MODEL_VERSION", "unsupported Project data model"
            )
        if database_path.resolve(strict=False).parent.as_uri() != project.workspace_locator:
            raise ApplicationError(
                "PROJECT_DATABASE_MISMATCH", "database path is outside the Project workspace"
            )
        return project
