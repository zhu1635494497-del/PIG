from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import platform
from typing import Callable
from uuid import uuid4

from pig.application.service import PigApplication
from pig.application.ports import FileOpener
from pig.application.open_service import OpenNodeService
from pig.application.processing_service import ProjectProcessingService
from pig.application.snapshot_import_service import SnapshotImportService
from pig.application.structure_service import WorkbenchStructureService
from pig.application.workspace_service import WorkspaceActionService
from pig.application.working_file_service import WorkingFileService
from pig.application.workspace_query_service import WorkspaceQueryService
from pig.application.workspace_export_service import WorkspaceExportService
from pig.application.import_undo_service import ImportUndoService
from pig.application.workbench_recovery_service import WorkbenchRecoveryService
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase
from pig.handlers import (
    ArchiveHandler,
    ContainerHandlerRegistry,
    EmlHandler,
    FolderHandler,
    MsgHandler,
    ZipHandler,
)
from pig.domain.enums import MaterializationLocatorKind, NodeFormat
from pig.domain.catalog_policy import CatalogPolicy
from pig.domain.open_policy import OpenPolicy
from pig.infrastructure.archives import Py7zrBackend, SevenZipRarBackend
from pig.infrastructure.email import ExtractMsgBackend
from pig.infrastructure.filesystem import (
    LocalArtifactStore,
    LocalManifestStore,
    LocalOpenHandoffStore,
    LocalOriginalSnapshotStore,
    LocalInspectionCacheStore,
    LocalWorkingArtifactStore,
    LocalWorkingVersionStore,
    LocalWorkspaceRecovery,
    LocalSourceInspector,
    LocalWorkspaceManager,
    LocalWorkspaceExportStore,
    LocalImportUndoStore,
    LocalWorkbenchRecoveryStore,
    SystemFileOpener,
)
from pig.handlers.workbench import (
    LegacyContainerWorkbenchAdapter,
    SnapshotFolderStructureHandler,
    WorkbenchStructureHandlerRegistry,
    ZipStructureHandler,
)


def create_local_application(
    workspace_root: Path,
    *,
    clock: Callable[[], datetime] | None = None,
    id_generator: Callable[[], str] | None = None,
    seven_zip_executable: Path | None = None,
    catalog_policy: CatalogPolicy = CatalogPolicy(),
    open_policy: OpenPolicy = OpenPolicy(),
    file_opener: FileOpener | None = None,
) -> PigApplication:
    """Composition root for the local-filesystem, one-SQLite-per-Project runtime."""

    effective_clock = clock or (lambda: datetime.now(timezone.utc))
    effective_id_generator = id_generator or (lambda: str(uuid4()))
    database = SqlAlchemyProjectDatabase()
    source_inspector = LocalSourceInspector(clock=effective_clock)
    artifact_store = LocalArtifactStore()
    eml_handler = EmlHandler()
    msg_handler = MsgHandler(ExtractMsgBackend())
    seven_z_handler = ArchiveHandler(NodeFormat.SEVEN_Z, Py7zrBackend())
    rar_handler = ArchiveHandler(
        NodeFormat.RAR,
        SevenZipRarBackend(seven_zip_executable),
    )
    processing_service = ProjectProcessingService(
        database=database,
        source_inspector=source_inspector,
        handlers=ContainerHandlerRegistry(
            [
                FolderHandler(source_inspector),
                ZipHandler(),
                eml_handler,
                msg_handler,
                seven_z_handler,
                rar_handler,
            ]
        ),
        artifact_store=artifact_store,
        workspace_recovery=LocalWorkspaceRecovery(),
        clock=effective_clock,
        id_generator=effective_id_generator,
    )
    effective_opener = file_opener or SystemFileOpener()
    open_service = OpenNodeService(
        database=database,
        source_inspector=source_inspector,
        artifact_store=artifact_store,
        handoff_store=LocalOpenHandoffStore(),
        opener=effective_opener,
        policy=open_policy,
        clock=effective_clock,
        id_generator=effective_id_generator,
    )
    original_snapshot_store = LocalOriginalSnapshotStore(
        clock=effective_clock,
        id_generator=effective_id_generator,
    )
    snapshot_import_service = SnapshotImportService(
        database=database,
        store=original_snapshot_store,
        clock=effective_clock,
        id_generator=effective_id_generator,
    )
    working_store = LocalWorkingArtifactStore()
    version_store = LocalWorkingVersionStore()
    structure_service = WorkbenchStructureService(
        database=database,
        originals=original_snapshot_store,
        inspection_cache=LocalInspectionCacheStore(),
        working_store=working_store,
        version_store=version_store,
        folder_handler=SnapshotFolderStructureHandler(),
        handlers=WorkbenchStructureHandlerRegistry(
            [
                ZipStructureHandler(),
                LegacyContainerWorkbenchAdapter(
                    eml_handler,
                    locator_kind=MaterializationLocatorKind.EML_PART,
                    hierarchical=False,
                    backend_name="python-email",
                    backend_version=platform.python_version(),
                ),
                LegacyContainerWorkbenchAdapter(
                    msg_handler,
                    locator_kind=MaterializationLocatorKind.MSG_ATTACHMENT,
                    hierarchical=False,
                    backend_name="extract-msg",
                    backend_version=msg_handler.version,
                ),
                LegacyContainerWorkbenchAdapter(
                    seven_z_handler,
                    locator_kind=MaterializationLocatorKind.SEVEN_Z_MEMBER,
                    hierarchical=True,
                    backend_name="py7zr",
                    backend_version=seven_z_handler.version,
                ),
                LegacyContainerWorkbenchAdapter(
                    rar_handler,
                    locator_kind=MaterializationLocatorKind.RAR_MEMBER,
                    hierarchical=True,
                    backend_name="7zip-system",
                    backend_version="unvalidated",
                ),
            ]
        ),
        clock=effective_clock,
        id_generator=effective_id_generator,
    )
    workspace_action_service = WorkspaceActionService(
        database=database,
        clock=effective_clock,
        id_generator=effective_id_generator,
    )
    working_file_service = WorkingFileService(
        database=database,
        working_store=working_store,
        version_store=version_store,
        structure_service=structure_service,
        opener=effective_opener,
        policy=open_policy,
        clock=effective_clock,
        id_generator=effective_id_generator,
    )
    workspace_query_service = WorkspaceQueryService(database=database)
    workspace_export_service = WorkspaceExportService(
        database=database,
        structure_service=structure_service,
        working_file_service=working_file_service,
        store=LocalWorkspaceExportStore(),
        clock=effective_clock,
        id_generator=effective_id_generator,
    )
    import_undo_service = ImportUndoService(
        database=database,
        store=LocalImportUndoStore(),
        clock=effective_clock,
        id_generator=effective_id_generator,
    )
    workbench_recovery_service = WorkbenchRecoveryService(
        database=database,
        store=LocalWorkbenchRecoveryStore(),
        clock=effective_clock,
        id_generator=effective_id_generator,
    )
    return PigApplication(
        workspace=LocalWorkspaceManager(workspace_root),
        database=database,
        source_inspector=source_inspector,
        manifest_store=LocalManifestStore(),
        catalog_policy=catalog_policy,
        processing_service=processing_service,
        open_service=open_service,
        snapshot_import_service=snapshot_import_service,
        structure_service=structure_service,
        workspace_action_service=workspace_action_service,
        working_file_service=working_file_service,
        workspace_query_service=workspace_query_service,
        workspace_export_service=workspace_export_service,
        import_undo_service=import_undo_service,
        workbench_recovery_service=workbench_recovery_service,
        clock=effective_clock,
        id_generator=effective_id_generator,
    )
