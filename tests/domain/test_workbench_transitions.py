from __future__ import annotations

import pytest

from pig.domain.enums import (
    ArtifactIntegrityStatus,
    ImportSessionStatus,
    ImportItemStatus,
    OriginalSnapshotStatus,
    WorkingContentStatus,
    WorkspaceItemLifecycleStatus,
    WorkspaceMaterializationStatus,
)
from pig.domain.exceptions import InvariantViolationError
from pig.domain.transitions import (
    require_original_artifact_integrity_transition,
    require_import_session_transition,
    require_import_item_transition,
    require_original_snapshot_transition,
    require_working_content_transition,
    require_workspace_lifecycle_transition,
    require_workspace_materialization_transition,
)


def test_workbench_state_machines_accept_documented_paths() -> None:
    require_original_artifact_integrity_transition(
        ArtifactIntegrityStatus.VERIFIED,
        ArtifactIntegrityStatus.VERIFYING,
    )
    require_original_artifact_integrity_transition(
        ArtifactIntegrityStatus.VERIFYING,
        ArtifactIntegrityStatus.MISSING,
    )
    require_import_item_transition(
        ImportItemStatus.PENDING, ImportItemStatus.CAPTURING
    )
    require_import_item_transition(
        ImportItemStatus.CAPTURING, ImportItemStatus.CAPTURED
    )
    require_import_session_transition(
        ImportSessionStatus.QUEUED, ImportSessionStatus.SNAPSHOTTING
    )
    require_import_session_transition(
        ImportSessionStatus.SNAPSHOTTING, ImportSessionStatus.INSPECTING
    )
    require_import_session_transition(
        ImportSessionStatus.INSPECTING, ImportSessionStatus.SUCCESS
    )
    require_original_snapshot_transition(
        OriginalSnapshotStatus.COPYING, OriginalSnapshotStatus.VERIFYING
    )
    require_original_snapshot_transition(
        OriginalSnapshotStatus.VERIFYING, OriginalSnapshotStatus.READY
    )
    require_workspace_lifecycle_transition(
        WorkspaceItemLifecycleStatus.ACTIVE,
        WorkspaceItemLifecycleStatus.DELETED,
    )
    require_workspace_materialization_transition(
        WorkspaceMaterializationStatus.VIRTUAL,
        WorkspaceMaterializationStatus.MATERIALIZING,
    )
    require_working_content_transition(
        WorkingContentStatus.CLEAN, WorkingContentStatus.MODIFIED
    )
    require_working_content_transition(
        WorkingContentStatus.MODIFIED, WorkingContentStatus.CLEAN
    )
    require_working_content_transition(
        WorkingContentStatus.MISSING, WorkingContentStatus.MISSING
    )


@pytest.mark.parametrize(
    ("transition", "current", "target"),
    [
        (
            require_original_artifact_integrity_transition,
            ArtifactIntegrityStatus.VERIFIED,
            ArtifactIntegrityStatus.MISSING,
        ),
        (
            require_import_item_transition,
            ImportItemStatus.CAPTURED,
            ImportItemStatus.CAPTURING,
        ),
        (
            require_import_session_transition,
            ImportSessionStatus.SUCCESS,
            ImportSessionStatus.SNAPSHOTTING,
        ),
        (
            require_original_snapshot_transition,
            OriginalSnapshotStatus.READY,
            OriginalSnapshotStatus.COPYING,
        ),
        (
            require_workspace_lifecycle_transition,
            WorkspaceItemLifecycleStatus.ACTIVE,
            WorkspaceItemLifecycleStatus.ACTIVE,
        ),
        (
            require_workspace_materialization_transition,
            WorkspaceMaterializationStatus.VIRTUAL,
            WorkspaceMaterializationStatus.MATERIALIZED,
        ),
        (
            require_working_content_transition,
            WorkingContentStatus.MODIFIED,
            WorkingContentStatus.CHECKING,
        ),
    ],
)
def test_workbench_state_machines_reject_undocumented_transitions(
    transition, current, target
) -> None:
    with pytest.raises(InvariantViolationError):
        transition(current, target)
