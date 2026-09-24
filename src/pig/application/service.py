from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Callable, Optional, Protocol, Sequence, TypeVar
from uuid import uuid4

from pig.application.contracts import (
    AddWorkspaceInputsRequest,
    AddWorkspaceInputsResult,
    CreateProjectRequest,
    CreateProjectResult,
    CreateWorkspaceFolderRequest,
    ExportManifestRequest,
    ExportManifestResult,
    ExportWorkspaceItemsRequest,
    ExportWorkspaceItemsResult,
    GetNodeRequest,
    GetWorkspaceItemRequest,
    GetWorkspaceItemResult,
    GetWorkspaceTreeRequest,
    GetWorkspaceTreeResult,
    GetProjectTreeRequest,
    GetProjectOverviewRequest,
    ImportProjectItemsRequest,
    ImportProjectItemsResult,
    InspectImportSessionRequest,
    InspectImportSessionResult,
    InspectProjectRecoveryRequest,
    InspectProjectRecoveryResult,
    LoadProjectRequest,
    MaterializeWorkspaceItemRequest,
    MaterializeWorkspaceItemResult,
    MoveWorkspaceItemRequest,
    NodeDetails,
    OpenNodeRequest,
    OpenNodeResult,
    OpenWorkspaceItemRequest,
    OpenWorkspaceItemResult,
    PreviewImportUndoRequest,
    ImportUndoImpact,
    ProcessNodeRequest,
    ProcessNodeResult,
    ProcessProjectRequest,
    ProcessProjectResult,
    ProjectOverview,
    ProjectTreeItem,
    ProjectTreeResult,
    RecoverProjectRequest,
    RecoverProjectResult,
    RecoverWorkbenchProjectRequest,
    RecoverWorkbenchProjectResult,
    RefreshWorkingArtifactRequest,
    RefreshWorkingArtifactResult,
    RollbackWorkingArtifactRequest,
    RollbackWorkingArtifactResult,
    RestoreWorkspaceItemRequest,
    RestoreWorkingArtifactRequest,
    RestoreWorkingArtifactResult,
    RegisterSourceRequest,
    RegisterSourceResult,
    SearchNodeHit,
    SearchNodesRequest,
    SearchNodesResult,
    SearchWorkspaceItemsRequest,
    SearchWorkspaceItemsResult,
    SourceOverview,
    SoftDeleteWorkspaceItemRequest,
    UndoImportedItemRequest,
    UndoImportedItemResult,
    VerifyOriginalSnapshotRequest,
    VerifyOriginalSnapshotResult,
    WorkspaceMutationResult,
)
from pig.application.errors import ApplicationError
from pig.application.manifest import (
    MANIFEST_SCHEMA_VERSION,
    build_manifest_document,
)
from pig.application.ports import (
    ManifestStore,
    ProjectDatabaseProvider,
    SourceInspector,
    WorkspaceManager,
)
from pig.domain.catalog_policy import CatalogPolicy
from pig.domain.entities import ProcessingEvent, Project
from pig.domain.enums import (
    ErrorCode,
    EventSeverity,
    EventType,
    NodeFormat,
    NodeKind,
    NodeProcessingStatus,
    ProjectStatus,
)
from pig.domain.exceptions import EntityNotFoundError
from pig.domain.model_version import WORKBENCH_MODEL_VERSION


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]
EnumType = TypeVar("EnumType", bound=Enum)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


def _required_text(value: str, field_name: str, maximum: int = 255) -> str:
    normalized = value.strip()
    if not normalized:
        raise ApplicationError(
            code="INVALID_REQUEST",
            message=f"{field_name} must not be empty",
            details={"field": field_name},
        )
    if len(normalized) > maximum:
        raise ApplicationError(
            code="INVALID_REQUEST",
            message=f"{field_name} exceeds {maximum} characters",
            details={"field": field_name, "maximum": maximum},
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ApplicationError(
            code="INVALID_REQUEST",
            message=f"{field_name} contains control characters",
            details={"field": field_name},
        )
    return normalized


class PigApplication:
    """Caller-facing Application actions; processing is delegated to its service."""

    def __init__(
        self,
        *,
        workspace: WorkspaceManager,
        database: ProjectDatabaseProvider,
        source_inspector: SourceInspector,
        manifest_store: Optional[ManifestStore] = None,
        catalog_policy: CatalogPolicy = CatalogPolicy(),
        processing_service: Optional["ProcessingService"] = None,
        open_service: Optional["OpenService"] = None,
        snapshot_import_service: Optional["SnapshotImportService"] = None,
        structure_service: Optional["WorkbenchStructureService"] = None,
        workspace_action_service: Optional["WorkspaceActionService"] = None,
        working_file_service: Optional["WorkingFileService"] = None,
        workspace_query_service: Optional["WorkspaceQueryService"] = None,
        workspace_export_service: Optional["WorkspaceExportService"] = None,
        import_undo_service: Optional["ImportUndoService"] = None,
        workbench_recovery_service: Optional["WorkbenchRecoveryService"] = None,
        clock: Clock = _utc_now,
        id_generator: IdGenerator = _new_id,
    ) -> None:
        self._workspace = workspace
        self._database = database
        self._source_inspector = source_inspector
        self._manifest_store = manifest_store
        self._catalog_policy = catalog_policy
        self._clock = clock
        self._new_id = id_generator
        self._processing_service = processing_service
        self._open_service = open_service
        self._snapshot_import_service = snapshot_import_service
        self._structure_service = structure_service
        self._workspace_action_service = workspace_action_service
        self._working_file_service = working_file_service
        self._workspace_query_service = workspace_query_service
        self._workspace_export_service = workspace_export_service
        self._import_undo_service = import_undo_service
        self._workbench_recovery_service = workbench_recovery_service

    def import_project_items(
        self, request: ImportProjectItemsRequest
    ) -> ImportProjectItemsResult:
        self._assert_writable(request.project_id, request.database_path)
        if self._snapshot_import_service is None:
            raise ApplicationError(
                code="SNAPSHOT_IMPORT_NOT_CONFIGURED",
                message="immutable snapshot import is not configured",
            )
        return self._snapshot_import_service.import_items(request)

    def verify_original_snapshot(
        self, request: VerifyOriginalSnapshotRequest
    ) -> VerifyOriginalSnapshotResult:
        self._assert_writable(request.project_id, request.database_path)
        if self._snapshot_import_service is None:
            raise ApplicationError(
                code="SNAPSHOT_IMPORT_NOT_CONFIGURED",
                message="immutable snapshot verification is not configured",
            )
        return self._snapshot_import_service.verify(request)

    def inspect_import_session(
        self, request: InspectImportSessionRequest
    ) -> InspectImportSessionResult:
        if self._structure_service is None:
            raise ApplicationError(
                code="STRUCTURE_INSPECTION_NOT_CONFIGURED",
                message="Workbench structure inspection is not configured",
            )
        return self._structure_service.inspect(request)

    def materialize_workspace_item(
        self, request: MaterializeWorkspaceItemRequest
    ) -> MaterializeWorkspaceItemResult:
        self._assert_writable(request.project_id, request.database_path)
        if self._structure_service is None:
            raise ApplicationError(
                code="WORKING_MATERIALIZATION_NOT_CONFIGURED",
                message="Working Artifact materialization is not configured",
            )
        return self._structure_service.materialize(request)

    def refresh_working_artifact(
        self, request: RefreshWorkingArtifactRequest
    ) -> RefreshWorkingArtifactResult:
        self._assert_writable(request.project_id, request.database_path)
        return self._working_files().refresh(request)

    def open_workspace_item(
        self, request: OpenWorkspaceItemRequest
    ) -> OpenWorkspaceItemResult:
        self._assert_writable(request.project_id, request.database_path)
        return self._working_files().open(request)

    def restore_working_artifact(
        self, request: RestoreWorkingArtifactRequest
    ) -> RestoreWorkingArtifactResult:
        self._assert_writable(request.project_id, request.database_path)
        return self._working_files().restore(request)

    def rollback_working_artifact(
        self, request: RollbackWorkingArtifactRequest
    ) -> RollbackWorkingArtifactResult:
        self._assert_writable(request.project_id, request.database_path)
        return self._working_files().rollback(request)

    def get_workspace_tree(
        self, request: GetWorkspaceTreeRequest
    ) -> GetWorkspaceTreeResult:
        return self._workspace_queries().tree(request)

    def get_workspace_item(
        self, request: GetWorkspaceItemRequest
    ) -> GetWorkspaceItemResult:
        return self._workspace_queries().item(request)

    def search_workspace_items(
        self, request: SearchWorkspaceItemsRequest
    ) -> SearchWorkspaceItemsResult:
        return self._workspace_queries().search(request)

    def export_workspace_items(
        self, request: ExportWorkspaceItemsRequest
    ) -> ExportWorkspaceItemsResult:
        self._assert_writable(request.project_id, request.database_path)
        if self._workspace_export_service is None:
            raise ApplicationError(
                "WORKSPACE_EXPORT_NOT_CONFIGURED",
                "Workspace export is not configured",
            )
        return self._workspace_export_service.export(request)

    def preview_import_undo(
        self, request: PreviewImportUndoRequest
    ) -> ImportUndoImpact:
        if self._import_undo_service is None:
            raise ApplicationError(
                "IMPORT_UNDO_NOT_CONFIGURED", "Import undo is not configured"
            )
        return self._import_undo_service.preview(request)

    def undo_imported_item(
        self, request: UndoImportedItemRequest
    ) -> UndoImportedItemResult:
        self._assert_writable(request.project_id, request.database_path)
        if self._import_undo_service is None:
            raise ApplicationError(
                "IMPORT_UNDO_NOT_CONFIGURED", "Import undo is not configured"
            )
        return self._import_undo_service.undo(request)

    def create_workspace_folder(
        self, request: CreateWorkspaceFolderRequest
    ) -> WorkspaceMutationResult:
        self._assert_writable(request.project_id, request.database_path)
        return self._workspace_actions().create_folder(request)

    def move_workspace_item(
        self, request: MoveWorkspaceItemRequest
    ) -> WorkspaceMutationResult:
        self._assert_writable(request.project_id, request.database_path)
        return self._workspace_actions().move(request)

    def soft_delete_workspace_item(
        self, request: SoftDeleteWorkspaceItemRequest
    ) -> WorkspaceMutationResult:
        self._assert_writable(request.project_id, request.database_path)
        return self._workspace_actions().soft_delete(request)

    def restore_workspace_item(
        self, request: RestoreWorkspaceItemRequest
    ) -> WorkspaceMutationResult:
        self._assert_writable(request.project_id, request.database_path)
        return self._workspace_actions().restore(request)

    def add_workspace_inputs(
        self, request: AddWorkspaceInputsRequest
    ) -> AddWorkspaceInputsResult:
        imported = self.import_project_items(
            ImportProjectItemsRequest(
                project_id=request.project_id,
                database_path=request.database_path,
                input_paths=request.input_paths,
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                policy=request.snapshot_policy,
                target_workspace_parent_id=request.target_workspace_parent_id,
                expected_workspace_revision=request.expected_workspace_revision,
            )
        )
        inspected = None
        if imported.accepted_item_count > 0:
            if self._structure_service is None:
                raise ApplicationError(
                    code="STRUCTURE_INSPECTION_NOT_CONFIGURED",
                    message="Workbench structure inspection is not configured",
                )
            inspected = self._structure_service.inspect(
                InspectImportSessionRequest(
                    project_id=request.project_id,
                    database_path=request.database_path,
                    import_session_id=imported.import_session_id,
                    actor=request.actor,
                    policy=request.processing_policy,
                )
            )
        with self._database.unit_of_work(request.database_path) as uow:
            project = uow.projects.get(request.project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {request.project_id}")
            revision = project.workspace_revision
        return AddWorkspaceInputsResult(
            project_id=request.project_id,
            workspace_revision=revision,
            import_result=imported,
            inspection_result=inspected,
        )

    def inspect_project_recovery(
        self, request: InspectProjectRecoveryRequest
    ) -> InspectProjectRecoveryResult:
        if self._workbench_recovery_service is None:
            raise ApplicationError(
                "WORKBENCH_RECOVERY_NOT_CONFIGURED",
                "Workbench Recovery is not configured",
            )
        return self._workbench_recovery_service.inspect(request)

    def recover_workbench_project(
        self, request: RecoverWorkbenchProjectRequest
    ) -> RecoverWorkbenchProjectResult:
        if self._workbench_recovery_service is None:
            raise ApplicationError(
                "WORKBENCH_RECOVERY_NOT_CONFIGURED",
                "Workbench Recovery is not configured",
            )
        return self._workbench_recovery_service.recover(request)

    def _assert_writable(self, project_id: str, database_path: Path) -> None:
        if self._workbench_recovery_service is not None:
            self._workbench_recovery_service.assert_writable(
                project_id, database_path
            )

    def _workspace_actions(self) -> "WorkspaceActionService":
        if self._workspace_action_service is None:
            raise ApplicationError(
                code="WORKSPACE_ACTIONS_NOT_CONFIGURED",
                message="mutable Workspace actions are not configured",
            )
        return self._workspace_action_service

    def _working_files(self) -> "WorkingFileService":
        if self._working_file_service is None:
            raise ApplicationError(
                code="WORKING_FILE_ACTIONS_NOT_CONFIGURED",
                message="Working Artifact actions are not configured",
            )
        return self._working_file_service

    def _workspace_queries(self) -> "WorkspaceQueryService":
        if self._workspace_query_service is None:
            raise ApplicationError(
                code="WORKSPACE_QUERIES_NOT_CONFIGURED",
                message="Workspace read actions are not configured",
            )
        return self._workspace_query_service

    def create_project(self, request: CreateProjectRequest) -> CreateProjectResult:
        name = _required_text(request.name, "name")
        actor = _required_text(request.actor, "actor")
        description = request.description.strip() if request.description else None
        workspace_root = (
            None
            if request.workspace_root is None
            else self._absolute_path(request.workspace_root, "workspace_root")
        )
        project_id = self._new_id()
        correlation_id = self._new_id()
        reservation = self._workspace.reserve(project_id, name, workspace_root)
        try:
            self._database.migrate(reservation.temporary_database_path)
            occurred_at = self._clock()
            project = Project(
                id=project_id,
                name=name,
                description=description,
                status=ProjectStatus.CREATED,
                workspace_locator=reservation.final_path.resolve(strict=False).as_uri(),
                model_version=WORKBENCH_MODEL_VERSION,
                created_at=occurred_at,
                updated_at=occurred_at,
            )
            event = ProcessingEvent(
                id=self._new_id(),
                event_type=EventType.PROJECT_CREATED,
                project_id=project_id,
                actor=actor,
                occurred_at=occurred_at,
                severity=EventSeverity.INFO,
                new_status=ProjectStatus.CREATED.value,
                correlation_id=correlation_id,
                details={
                    "name": name,
                    "model_version": WORKBENCH_MODEL_VERSION,
                },
            )
            with self._database.unit_of_work(
                reservation.temporary_database_path
            ) as uow:
                uow.projects.add(project)
                uow.processing.append_event(event)
                uow.commit()
            self._workspace.publish(reservation)
        except BaseException:
            self._workspace.abandon(reservation)
            raise
        return CreateProjectResult(
            project_id=project_id,
            status=ProjectStatus.CREATED,
            workspace_path=reservation.final_path,
            database_path=reservation.final_database_path,
            workspace_revision=0,
        )

    def register_source(
        self, request: RegisterSourceRequest
    ) -> RegisterSourceResult:
        """Reject the superseded external-reference import contract."""

        raise ApplicationError(
            code="EXTERNAL_REFERENCE_IMPORT_RETIRED",
            message="use import_project_items to create an immutable snapshot",
            details={"replacement_action": "import_project_items"},
        )

    def get_project_overview(
        self, request: GetProjectOverviewRequest
    ) -> ProjectOverview:
        database_path = self._absolute_path(request.database_path, "database_path")
        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(request.project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {request.project_id}")
            self._require_supported_model(project)
            self._require_matching_workspace(project, database_path)
            source_views: list[SourceOverview] = []
            for source in uow.catalog.sources_for_project(project.id):
                if source.root_node_id is None:
                    raise EntityNotFoundError(
                        f"source root not found: {source.id}"
                    )
                root = uow.catalog.get_node(source.root_node_id)
                if root is None:
                    raise EntityNotFoundError(
                        f"source root node not found: {source.root_node_id}"
                    )
                source_views.append(
                    SourceOverview(
                        source=source,
                        root_node=root,
                        artifacts=tuple(uow.catalog.artifacts_for_node(root.id)),
                    )
                )
            events = tuple(uow.processing.events_for_project(project.id))
        return ProjectOverview(
            project=project,
            sources=tuple(source_views),
            events=events,
        )

    def load_project(self, request: LoadProjectRequest) -> ProjectOverview:
        """Load the single Project owned by a Project SQLite database."""

        database_path = self._absolute_path(request.database_path, "database_path")
        self._database.migrate(database_path)
        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get_singleton()
        if project is None:
            raise EntityNotFoundError("project not found in database")
        self._require_supported_model(project)
        self._require_matching_workspace(project, database_path)
        return self.get_project_overview(
            GetProjectOverviewRequest(
                project_id=project.id,
                database_path=database_path,
            )
        )

    def get_node(self, request: GetNodeRequest) -> NodeDetails:
        database_path = self._absolute_path(request.database_path, "database_path")
        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(request.project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {request.project_id}")
            self._require_matching_workspace(project, database_path)
            node = uow.catalog.get_node(request.node_id)
            if node is None or node.project_id != project.id:
                raise EntityNotFoundError(f"node not found: {request.node_id}")
            source = uow.catalog.get_source(node.source_id)
            if source is None:
                raise EntityNotFoundError(f"source not found: {node.source_id}")
            artifacts = tuple(uow.catalog.artifacts_for_node(node.id))
            metadata = tuple(uow.catalog.metadata_for_node(node.id))
            lineage = tuple(uow.catalog.lineage_for(node.id))
            children = tuple(uow.catalog.children_of(node.id))
        return NodeDetails(
            node=node,
            source=source,
            artifacts=artifacts,
            metadata=metadata,
            lineage=lineage,
            children=children,
        )

    def get_project_tree(
        self, request: GetProjectTreeRequest
    ) -> ProjectTreeResult:
        project_id = _required_text(request.project_id, "project_id")
        database_path = self._absolute_path(request.database_path, "database_path")
        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            self._require_matching_workspace(project, database_path)
            sources = tuple(uow.catalog.sources_for_project(project_id))
            relationships = {
                relationship.child_node_id: relationship
                for relationship in uow.catalog.relationships_for_project(project_id)
            }
            items = []
            for node in uow.catalog.nodes_for_project(project_id):
                relationship = relationships.get(node.id)
                items.append(
                    ProjectTreeItem(
                        node=node,
                        parent_node_id=(
                            None
                            if relationship is None
                            else relationship.parent_node_id
                        ),
                        relationship_type=(
                            None if relationship is None else relationship.type
                        ),
                        ordinal=(0 if relationship is None else relationship.ordinal),
                    )
                )
        return ProjectTreeResult(
            project=project,
            sources=sources,
            items=tuple(items),
        )

    def search_nodes(self, request: SearchNodesRequest) -> SearchNodesResult:
        project_id = _required_text(request.project_id, "project_id")
        database_path = self._absolute_path(request.database_path, "database_path")
        query = self._search_query(request.query)
        source_id = (
            None
            if request.source_id is None
            else _required_text(request.source_id, "source_id")
        )
        kinds = self._enum_filter(request.kinds, NodeKind, "kinds")
        formats = self._enum_filter(request.formats, NodeFormat, "formats")
        statuses = self._enum_filter(
            request.statuses, NodeProcessingStatus, "statuses"
        )
        if (
            isinstance(request.limit, bool)
            or not isinstance(request.limit, int)
            or request.limit <= 0
            or request.limit > self._catalog_policy.max_search_page_size
        ):
            raise ApplicationError(
                code="INVALID_REQUEST",
                message="limit is outside the configured search page range",
                details={
                    "field": "limit",
                    "maximum": self._catalog_policy.max_search_page_size,
                },
            )
        if (
            isinstance(request.offset, bool)
            or not isinstance(request.offset, int)
            or request.offset < 0
        ):
            raise ApplicationError(
                code="INVALID_REQUEST",
                message="offset must be a nonnegative integer",
                details={"field": "offset"},
            )

        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            self._require_matching_workspace(project, database_path)
            if source_id is not None:
                source = uow.catalog.get_source(source_id)
                if source is None or source.project_id != project_id:
                    raise EntityNotFoundError(f"source not found: {source_id}")
            nodes, total = uow.catalog.search_nodes(
                project_id,
                query=query,
                source_id=source_id,
                kinds=kinds,
                formats=formats,
                statuses=statuses,
                limit=request.limit,
                offset=request.offset,
            )
            hits = []
            for node in nodes:
                relationship = uow.catalog.relationship_for_child(node.id)
                hits.append(
                    SearchNodeHit(
                        node=node,
                        parent_node_id=(
                            None
                            if relationship is None
                            else relationship.parent_node_id
                        ),
                        relationship_type=(
                            None if relationship is None else relationship.type
                        ),
                    )
                )
        return SearchNodesResult(
            project_id=project_id,
            items=tuple(hits),
            total=total,
            limit=request.limit,
            offset=request.offset,
            has_more=request.offset + len(hits) < total,
        )

    def export_manifest(
        self, request: ExportManifestRequest
    ) -> ExportManifestResult:
        if self._manifest_store is None:
            raise ApplicationError(
                code="MANIFEST_EXPORT_NOT_CONFIGURED",
                message="manifest export is not configured for this application",
            )
        project_id = _required_text(request.project_id, "project_id")
        actor = _required_text(request.actor, "actor")
        database_path = self._absolute_path(request.database_path, "database_path")
        manifest_id = self._new_id()
        correlation_id = self._new_id()
        storage_key = PurePosixPath(
            "manifests", f"{manifest_id}.json"
        ).as_posix()
        requested_at = self._clock()

        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            self._require_matching_workspace(project, database_path)
            uow.processing.append_event(
                ProcessingEvent(
                    id=self._new_id(),
                    event_type=EventType.MANIFEST_EXPORT_REQUESTED,
                    project_id=project_id,
                    actor=actor,
                    occurred_at=requested_at,
                    severity=EventSeverity.INFO,
                    correlation_id=correlation_id,
                    details={
                        "manifest_id": manifest_id,
                        "schema_version": MANIFEST_SCHEMA_VERSION,
                        "storage_key": storage_key,
                    },
                )
            )
            uow.commit()

        generated_at = self._clock()
        try:
            with self._manifest_store.begin(
                database_path.parent, manifest_id
            ) as manifest_session:
                with self._database.unit_of_work(database_path) as uow:
                    project = uow.projects.get(project_id)
                    if project is None:
                        raise EntityNotFoundError(
                            f"project not found: {project_id}"
                        )
                    self._require_matching_workspace(project, database_path)
                    events = tuple(uow.processing.events_for_project(project_id))
                    document = build_manifest_document(
                        manifest_id=manifest_id,
                        generated_at=generated_at,
                        project=project,
                        sources=tuple(uow.catalog.sources_for_project(project_id)),
                        nodes=tuple(uow.catalog.nodes_for_project(project_id)),
                        artifacts=tuple(
                            uow.catalog.artifacts_for_project(project_id)
                        ),
                        relationships=tuple(
                            uow.catalog.relationships_for_project(project_id)
                        ),
                        lineage=tuple(
                            uow.catalog.lineage_for_project(project_id)
                        ),
                        metadata=tuple(
                            uow.catalog.metadata_for_project(project_id)
                        ),
                        jobs=tuple(uow.processing.jobs_for_project(project_id)),
                        attempts=tuple(
                            uow.processing.attempts_for_project(project_id)
                        ),
                        events=events,
                    )
                    stored = manifest_session.write(
                        manifest_id,
                        document.payload,
                        max_size=self._catalog_policy.max_manifest_size,
                    )
                    finished_at = self._clock()
                    uow.processing.append_event(
                        ProcessingEvent(
                            id=self._new_id(),
                            event_type=EventType.MANIFEST_EXPORTED,
                            project_id=project_id,
                            actor=actor,
                            occurred_at=finished_at,
                            severity=EventSeverity.INFO,
                            correlation_id=correlation_id,
                            details={
                                "manifest_id": manifest_id,
                                "schema_version": MANIFEST_SCHEMA_VERSION,
                                "storage_key": stored.storage_key,
                                "size": stored.size,
                                "sha256": stored.sha256,
                                "included_event_count": (
                                    document.included_event_count
                                ),
                                "last_included_event_id": (
                                    document.last_included_event_id
                                ),
                            },
                        )
                    )
                    manifest_session.publish()
                    uow.commit()
                    manifest_session.complete()
        except Exception as exc:
            self._record_manifest_failure(
                project_id=project_id,
                database_path=database_path,
                actor=actor,
                manifest_id=manifest_id,
                storage_key=storage_key,
                correlation_id=correlation_id,
                failure=exc,
            )
            if isinstance(exc, ApplicationError):
                raise
            raise ApplicationError(
                code="MANIFEST_EXPORT_FAILED",
                message="manifest export failed",
                details={"manifest_id": manifest_id},
            ) from exc

        return ExportManifestResult(
            project_id=project_id,
            manifest_id=manifest_id,
            schema_version=MANIFEST_SCHEMA_VERSION,
            generated_at=generated_at,
            storage_key=stored.storage_key,
            manifest_path=stored.path,
            size=stored.size,
            sha256=stored.sha256,
            included_event_count=document.included_event_count,
            last_included_event_id=document.last_included_event_id,
        )

    def process_node(self, request: ProcessNodeRequest) -> ProcessNodeResult:
        if self._processing_service is None:
            raise ApplicationError(
                code="PROCESSING_NOT_CONFIGURED",
                message="node processing is not configured for this application",
            )
        return self._processing_service.execute(request)

    def process_project(
        self, request: ProcessProjectRequest
    ) -> ProcessProjectResult:
        if self._processing_service is None:
            raise ApplicationError(
                code="PROCESSING_NOT_CONFIGURED",
                message="project processing is not configured for this application",
            )
        return self._processing_service.execute_project(request)

    def recover_project(
        self, request: RecoverProjectRequest
    ) -> RecoverProjectResult:
        if self._processing_service is None:
            raise ApplicationError(
                code="RECOVERY_NOT_CONFIGURED",
                message="Project recovery is not configured for this application",
            )
        return self._processing_service.recover_project(request)

    def open_node(self, request: OpenNodeRequest) -> OpenNodeResult:
        if self._open_service is None:
            raise ApplicationError(
                code="OPEN_NOT_CONFIGURED",
                message="controlled file opening is not configured",
            )
        return self._open_service.execute(request)

    @staticmethod
    def _absolute_path(path: Path, field_name: str) -> Path:
        value = Path(path)
        if not value.is_absolute():
            raise ApplicationError(
                code="INVALID_REQUEST",
                message=f"{field_name} must be absolute",
                details={"field": field_name, "value": str(value)},
            )
        return value

    @staticmethod
    def _require_matching_workspace(project: Project, database_path: Path) -> None:
        actual = database_path.resolve(strict=False).parent.as_uri()
        if actual != project.workspace_locator:
            raise ApplicationError(
                code="PROJECT_DATABASE_MISMATCH",
                message="database path is outside the Project workspace",
                details={"project_id": project.id},
            )

    @staticmethod
    def _require_supported_model(project: Project) -> None:
        if project.model_version != WORKBENCH_MODEL_VERSION:
            raise ApplicationError(
                code="UNSUPPORTED_PROJECT_MODEL_VERSION",
                message="project was created with an unsupported data model",
                details={
                    "project_id": project.id,
                    "actual_model_version": project.model_version,
                    "supported_model_version": WORKBENCH_MODEL_VERSION,
                },
            )

    def _validate_project_database(
        self, project_id: str, database_path: Path
    ) -> None:
        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            self._require_supported_model(project)
            self._require_matching_workspace(project, database_path)

    def _search_query(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > self._catalog_policy.max_search_query_length:
            raise ApplicationError(
                code="INVALID_REQUEST",
                message="query exceeds the configured length limit",
                details={
                    "field": "query",
                    "maximum": self._catalog_policy.max_search_query_length,
                },
            )
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise ApplicationError(
                code="INVALID_REQUEST",
                message="query contains control characters",
                details={"field": "query"},
            )
        return normalized

    @staticmethod
    def _enum_filter(
        values: Sequence[EnumType], enum_type: type[EnumType], field_name: str
    ) -> tuple[EnumType, ...]:
        if any(not isinstance(value, enum_type) for value in values):
            raise ApplicationError(
                code="INVALID_REQUEST",
                message=f"{field_name} contains an invalid value",
                details={"field": field_name},
            )
        return tuple(dict.fromkeys(values))

    def _record_manifest_failure(
        self,
        *,
        project_id: str,
        database_path: Path,
        actor: str,
        manifest_id: str,
        storage_key: str,
        correlation_id: str,
        failure: Exception,
    ) -> None:
        technical_reference = self._new_id()
        failure_code = (
            failure.code
            if isinstance(failure, ApplicationError)
            else "UNEXPECTED_ERROR"
        )
        event_error_code = (
            ErrorCode.MANIFEST_SIZE_EXCEEDED
            if failure_code == "MANIFEST_SIZE_EXCEEDED"
            else ErrorCode.MANIFEST_EXPORT_FAILED
        )
        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            self._require_matching_workspace(project, database_path)
            uow.processing.append_event(
                ProcessingEvent(
                    id=self._new_id(),
                    event_type=EventType.MANIFEST_EXPORT_FAILED,
                    project_id=project_id,
                    actor=actor,
                    occurred_at=self._clock(),
                    severity=EventSeverity.ERROR,
                    error_code=event_error_code,
                    correlation_id=correlation_id,
                    details={
                        "manifest_id": manifest_id,
                        "schema_version": MANIFEST_SCHEMA_VERSION,
                        "storage_key": storage_key,
                        "failure_code": failure_code,
                        "technical_reference": technical_reference,
                    },
                )
            )
            uow.commit()

class ProcessingService(Protocol):
    def execute(self, request: ProcessNodeRequest) -> ProcessNodeResult: ...

    def execute_project(
        self, request: ProcessProjectRequest
    ) -> ProcessProjectResult: ...

    def recover_project(
        self, request: RecoverProjectRequest
    ) -> RecoverProjectResult: ...


class OpenService(Protocol):
    def execute(self, request: OpenNodeRequest) -> OpenNodeResult: ...


class SnapshotImportService(Protocol):
    def import_items(
        self, request: ImportProjectItemsRequest
    ) -> ImportProjectItemsResult: ...

    def verify(
        self, request: VerifyOriginalSnapshotRequest
    ) -> VerifyOriginalSnapshotResult: ...


class WorkbenchStructureService(Protocol):
    def inspect(
        self, request: InspectImportSessionRequest
    ) -> InspectImportSessionResult: ...

    def materialize(
        self, request: MaterializeWorkspaceItemRequest
    ) -> MaterializeWorkspaceItemResult: ...

    def restore_content(self, **kwargs): ...


class WorkingFileService(Protocol):
    def refresh(
        self, request: RefreshWorkingArtifactRequest
    ) -> RefreshWorkingArtifactResult: ...

    def open(
        self, request: OpenWorkspaceItemRequest
    ) -> OpenWorkspaceItemResult: ...

    def restore(
        self, request: RestoreWorkingArtifactRequest
    ) -> RestoreWorkingArtifactResult: ...

    def rollback(
        self, request: RollbackWorkingArtifactRequest
    ) -> RollbackWorkingArtifactResult: ...


class WorkspaceQueryService(Protocol):
    def tree(self, request: GetWorkspaceTreeRequest) -> GetWorkspaceTreeResult: ...

    def item(self, request: GetWorkspaceItemRequest) -> GetWorkspaceItemResult: ...

    def search(
        self, request: SearchWorkspaceItemsRequest
    ) -> SearchWorkspaceItemsResult: ...


class WorkspaceExportService(Protocol):
    def export(
        self, request: ExportWorkspaceItemsRequest
    ) -> ExportWorkspaceItemsResult: ...


class WorkspaceActionService(Protocol):
    def create_folder(
        self, request: CreateWorkspaceFolderRequest
    ) -> WorkspaceMutationResult: ...

    def move(self, request: MoveWorkspaceItemRequest) -> WorkspaceMutationResult: ...

    def soft_delete(
        self, request: SoftDeleteWorkspaceItemRequest
    ) -> WorkspaceMutationResult: ...

    def restore(
        self, request: RestoreWorkspaceItemRequest
    ) -> WorkspaceMutationResult: ...


class WorkbenchRecoveryService(Protocol):
    def inspect(
        self, request: InspectProjectRecoveryRequest
    ) -> InspectProjectRecoveryResult: ...

    def assert_writable(self, project_id: str, database_path: Path) -> None: ...

    def recover(
        self, request: RecoverWorkbenchProjectRequest
    ) -> RecoverWorkbenchProjectResult: ...
