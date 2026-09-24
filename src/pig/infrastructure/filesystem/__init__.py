"""Local filesystem adapters for workspace and read-only source access."""

from pig.infrastructure.filesystem.source_inspector import LocalSourceInspector
from pig.infrastructure.filesystem.artifact_store import LocalArtifactStore
from pig.infrastructure.filesystem.manifest_store import LocalManifestStore
from pig.infrastructure.filesystem.system_opener import SystemFileOpener
from pig.infrastructure.filesystem.open_handoff import LocalOpenHandoffStore
from pig.infrastructure.filesystem.recovery import LocalWorkspaceRecovery
from pig.infrastructure.filesystem.workspace import LocalWorkspaceManager
from pig.infrastructure.filesystem.original_snapshot_store import (
    LocalOriginalSnapshotStore,
)
from pig.infrastructure.filesystem.workbench_storage import (
    LocalInspectionCache,
    LocalInspectionCacheStore,
    LocalWorkingArtifactStore,
)
from pig.infrastructure.filesystem.working_version_store import LocalWorkingVersionStore
from pig.infrastructure.filesystem.import_undo_store import LocalImportUndoStore
from pig.infrastructure.filesystem.workspace_export_store import LocalWorkspaceExportStore
from pig.infrastructure.filesystem.workbench_recovery import LocalWorkbenchRecoveryStore

__all__ = [
    "LocalArtifactStore",
    "LocalManifestStore",
    "LocalOpenHandoffStore",
    "LocalOriginalSnapshotStore",
    "LocalInspectionCache",
    "LocalInspectionCacheStore",
    "LocalWorkingArtifactStore",
    "LocalWorkingVersionStore",
    "LocalImportUndoStore",
    "LocalWorkspaceExportStore",
    "LocalSourceInspector",
    "LocalWorkspaceManager",
    "SystemFileOpener",
    "LocalWorkspaceRecovery",
    "LocalWorkbenchRecoveryStore",
]
