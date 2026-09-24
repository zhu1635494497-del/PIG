from __future__ import annotations

from pig.domain.enums import (
    AttemptStatus,
    ArtifactIntegrityStatus,
    ImportSessionStatus,
    ImportItemStatus,
    JobStatus,
    NodeProcessingStatus,
    ProjectStatus,
    SourceStatus,
    OriginalSnapshotStatus,
    WorkingContentStatus,
    WorkspaceItemLifecycleStatus,
    WorkspaceMaterializationStatus,
)
from pig.domain.exceptions import InvariantViolationError


_PROJECT_TRANSITIONS: dict[ProjectStatus, frozenset[ProjectStatus]] = {
    ProjectStatus.CREATED: frozenset({ProjectStatus.IMPORTING}),
    ProjectStatus.IMPORTING: frozenset(
        {ProjectStatus.PROCESSING, ProjectStatus.FAILED}
    ),
    ProjectStatus.PROCESSING: frozenset(
        {
            ProjectStatus.READY,
            ProjectStatus.READY_WITH_WARNINGS,
            ProjectStatus.FAILED,
        }
    ),
    ProjectStatus.READY: frozenset(
        {ProjectStatus.IMPORTING, ProjectStatus.PROCESSING}
    ),
    ProjectStatus.READY_WITH_WARNINGS: frozenset(
        {ProjectStatus.IMPORTING, ProjectStatus.PROCESSING}
    ),
    ProjectStatus.FAILED: frozenset(
        {ProjectStatus.IMPORTING, ProjectStatus.PROCESSING}
    ),
}


def require_project_transition(
    current: ProjectStatus, target: ProjectStatus
) -> None:
    """Reject a Project status transition not defined by the V1 state machine."""

    if target not in _PROJECT_TRANSITIONS[current]:
        raise InvariantViolationError(
            f"invalid project status transition: {current.value} -> {target.value}"
        )


_SOURCE_TRANSITIONS: dict[SourceStatus, frozenset[SourceStatus]] = {
    SourceStatus.REGISTERED: frozenset({SourceStatus.VERIFYING}),
    SourceStatus.VERIFYING: frozenset(
        {
            SourceStatus.AVAILABLE,
            SourceStatus.MISSING,
            SourceStatus.CHANGED,
            SourceStatus.UNREADABLE,
        }
    ),
    SourceStatus.AVAILABLE: frozenset({SourceStatus.VERIFYING, SourceStatus.PURGED}),
    SourceStatus.MISSING: frozenset({SourceStatus.VERIFYING, SourceStatus.PURGED}),
    SourceStatus.CHANGED: frozenset({SourceStatus.VERIFYING, SourceStatus.PURGED}),
    SourceStatus.UNREADABLE: frozenset({SourceStatus.VERIFYING, SourceStatus.PURGED}),
    SourceStatus.PURGED: frozenset(),
}


_NODE_TRANSITIONS: dict[NodeProcessingStatus, frozenset[NodeProcessingStatus]] = {
    NodeProcessingStatus.DISCOVERED: frozenset({NodeProcessingStatus.PENDING}),
    NodeProcessingStatus.PENDING: frozenset(
        {NodeProcessingStatus.PROCESSING, NodeProcessingStatus.INTERRUPTED}
    ),
    NodeProcessingStatus.PROCESSING: frozenset(
        {
            NodeProcessingStatus.SUCCESS,
            NodeProcessingStatus.PARTIAL_SUCCESS,
            NodeProcessingStatus.UNSUPPORTED,
            NodeProcessingStatus.PASSWORD_REQUIRED,
            NodeProcessingStatus.CORRUPTED,
            NodeProcessingStatus.LIMIT_EXCEEDED,
            NodeProcessingStatus.SECURITY_BLOCKED,
            NodeProcessingStatus.SOURCE_MISSING,
            NodeProcessingStatus.SOURCE_CHANGED,
            NodeProcessingStatus.FAILED,
            NodeProcessingStatus.SKIPPED,
            NodeProcessingStatus.INTERRUPTED,
        }
    ),
    NodeProcessingStatus.INTERRUPTED: frozenset(
        {NodeProcessingStatus.PENDING}
    ),
}


_JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.SUCCESS,
            JobStatus.PARTIAL_SUCCESS,
            JobStatus.FAILED,
            JobStatus.INTERRUPTED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.INTERRUPTED: frozenset({JobStatus.RUNNING}),
    JobStatus.SUCCESS: frozenset(),
    JobStatus.PARTIAL_SUCCESS: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


_ATTEMPT_TRANSITIONS: dict[AttemptStatus, frozenset[AttemptStatus]] = {
    AttemptStatus.QUEUED: frozenset(
        {AttemptStatus.RUNNING, AttemptStatus.CANCELLED}
    ),
    AttemptStatus.RUNNING: frozenset(
        {
            AttemptStatus.COMPLETED,
            AttemptStatus.FAILED,
            AttemptStatus.INTERRUPTED,
            AttemptStatus.CANCELLED,
        }
    ),
    AttemptStatus.COMPLETED: frozenset(),
    AttemptStatus.FAILED: frozenset(),
    AttemptStatus.INTERRUPTED: frozenset(),
    AttemptStatus.CANCELLED: frozenset(),
}


def _require_transition(current: object, target: object, allowed: dict) -> None:
    if target not in allowed[current]:
        raise InvariantViolationError(
            f"invalid status transition: {current.value} -> {target.value}"
        )


def require_source_transition(current: SourceStatus, target: SourceStatus) -> None:
    _require_transition(current, target, _SOURCE_TRANSITIONS)


def require_node_transition(
    current: NodeProcessingStatus, target: NodeProcessingStatus
) -> None:
    _require_transition(current, target, _NODE_TRANSITIONS)


def require_job_transition(current: JobStatus, target: JobStatus) -> None:
    _require_transition(current, target, _JOB_TRANSITIONS)


def require_attempt_transition(
    current: AttemptStatus, target: AttemptStatus
) -> None:
    _require_transition(current, target, _ATTEMPT_TRANSITIONS)


_IMPORT_SESSION_TRANSITIONS: dict[
    ImportSessionStatus, frozenset[ImportSessionStatus]
] = {
    ImportSessionStatus.QUEUED: frozenset(
        {ImportSessionStatus.SNAPSHOTTING, ImportSessionStatus.INTERRUPTED}
    ),
    ImportSessionStatus.SNAPSHOTTING: frozenset(
        {
            ImportSessionStatus.INSPECTING,
            ImportSessionStatus.PARTIAL_SUCCESS,
            ImportSessionStatus.FAILED,
            ImportSessionStatus.INTERRUPTED,
        }
    ),
    ImportSessionStatus.INSPECTING: frozenset(
        {
            ImportSessionStatus.SUCCESS,
            ImportSessionStatus.PARTIAL_SUCCESS,
            ImportSessionStatus.FAILED,
            ImportSessionStatus.INTERRUPTED,
        }
    ),
    ImportSessionStatus.SUCCESS: frozenset(),
    ImportSessionStatus.PARTIAL_SUCCESS: frozenset(),
    ImportSessionStatus.FAILED: frozenset(),
    ImportSessionStatus.INTERRUPTED: frozenset(),
}


_IMPORT_ITEM_TRANSITIONS: dict[ImportItemStatus, frozenset[ImportItemStatus]] = {
    ImportItemStatus.PENDING: frozenset(
        {
            ImportItemStatus.CAPTURING,
            ImportItemStatus.FAILED,
            ImportItemStatus.INTERRUPTED,
        }
    ),
    ImportItemStatus.CAPTURING: frozenset(
        {
            ImportItemStatus.CAPTURED,
            ImportItemStatus.FAILED,
            ImportItemStatus.INTERRUPTED,
        }
    ),
    ImportItemStatus.CAPTURED: frozenset(),
    ImportItemStatus.FAILED: frozenset(),
    ImportItemStatus.INTERRUPTED: frozenset(),
}


_ORIGINAL_SNAPSHOT_TRANSITIONS: dict[
    OriginalSnapshotStatus, frozenset[OriginalSnapshotStatus]
] = {
    OriginalSnapshotStatus.COPYING: frozenset(
        {
            OriginalSnapshotStatus.VERIFYING,
            OriginalSnapshotStatus.FAILED,
            OriginalSnapshotStatus.INTERRUPTED,
        }
    ),
    OriginalSnapshotStatus.VERIFYING: frozenset(
        {
            OriginalSnapshotStatus.READY,
            OriginalSnapshotStatus.FAILED,
            OriginalSnapshotStatus.INTERRUPTED,
            OriginalSnapshotStatus.MISSING,
            OriginalSnapshotStatus.MISMATCH,
            OriginalSnapshotStatus.UNREADABLE,
        }
    ),
    OriginalSnapshotStatus.READY: frozenset(
        {OriginalSnapshotStatus.VERIFYING, OriginalSnapshotStatus.PURGED}
    ),
    OriginalSnapshotStatus.FAILED: frozenset(),
    OriginalSnapshotStatus.INTERRUPTED: frozenset(),
    OriginalSnapshotStatus.MISSING: frozenset(
        {OriginalSnapshotStatus.VERIFYING, OriginalSnapshotStatus.PURGED}
    ),
    OriginalSnapshotStatus.MISMATCH: frozenset(
        {OriginalSnapshotStatus.VERIFYING, OriginalSnapshotStatus.PURGED}
    ),
    OriginalSnapshotStatus.UNREADABLE: frozenset(
        {OriginalSnapshotStatus.VERIFYING, OriginalSnapshotStatus.PURGED}
    ),
    OriginalSnapshotStatus.PURGED: frozenset(),
}


_ORIGINAL_ARTIFACT_INTEGRITY_TRANSITIONS: dict[
    ArtifactIntegrityStatus, frozenset[ArtifactIntegrityStatus]
] = {
    ArtifactIntegrityStatus.UNVERIFIED: frozenset(
        {ArtifactIntegrityStatus.VERIFYING}
    ),
    ArtifactIntegrityStatus.VERIFIED: frozenset(
        {ArtifactIntegrityStatus.VERIFYING, ArtifactIntegrityStatus.PURGED}
    ),
    ArtifactIntegrityStatus.MISSING: frozenset(
        {ArtifactIntegrityStatus.VERIFYING, ArtifactIntegrityStatus.PURGED}
    ),
    ArtifactIntegrityStatus.MISMATCH: frozenset(
        {ArtifactIntegrityStatus.VERIFYING, ArtifactIntegrityStatus.PURGED}
    ),
    ArtifactIntegrityStatus.UNREADABLE: frozenset(
        {ArtifactIntegrityStatus.VERIFYING, ArtifactIntegrityStatus.PURGED}
    ),
    ArtifactIntegrityStatus.VERIFYING: frozenset(
        {
            ArtifactIntegrityStatus.VERIFIED,
            ArtifactIntegrityStatus.MISSING,
            ArtifactIntegrityStatus.MISMATCH,
            ArtifactIntegrityStatus.UNREADABLE,
        }
    ),
    ArtifactIntegrityStatus.PURGED: frozenset(),
}


_WORKSPACE_LIFECYCLE_TRANSITIONS: dict[
    WorkspaceItemLifecycleStatus, frozenset[WorkspaceItemLifecycleStatus]
] = {
    WorkspaceItemLifecycleStatus.ACTIVE: frozenset(
        {WorkspaceItemLifecycleStatus.DELETED, WorkspaceItemLifecycleStatus.PURGED}
    ),
    WorkspaceItemLifecycleStatus.DELETED: frozenset(
        {WorkspaceItemLifecycleStatus.ACTIVE, WorkspaceItemLifecycleStatus.PURGED}
    ),
    WorkspaceItemLifecycleStatus.PURGED: frozenset(),
}


_WORKSPACE_MATERIALIZATION_TRANSITIONS: dict[
    WorkspaceMaterializationStatus,
    frozenset[WorkspaceMaterializationStatus],
] = {
    WorkspaceMaterializationStatus.VIRTUAL: frozenset(
        {WorkspaceMaterializationStatus.MATERIALIZING}
    ),
    WorkspaceMaterializationStatus.MATERIALIZING: frozenset(
        {
            WorkspaceMaterializationStatus.MATERIALIZED,
            WorkspaceMaterializationStatus.FAILED,
            WorkspaceMaterializationStatus.INTERRUPTED,
        }
    ),
    WorkspaceMaterializationStatus.MATERIALIZED: frozenset(
        {WorkspaceMaterializationStatus.MATERIALIZING}
    ),
    WorkspaceMaterializationStatus.FAILED: frozenset(
        {WorkspaceMaterializationStatus.MATERIALIZING}
    ),
    WorkspaceMaterializationStatus.INTERRUPTED: frozenset(
        {WorkspaceMaterializationStatus.MATERIALIZING}
    ),
}


_WORKING_CONTENT_TRANSITIONS: dict[
    WorkingContentStatus, frozenset[WorkingContentStatus]
] = {
    # CHECKING is an operation-local phase. Durable observations move directly
    # between terminal states so a crash cannot strand a Working Artifact.
    WorkingContentStatus.CLEAN: frozenset(
        {
            WorkingContentStatus.CLEAN,
            WorkingContentStatus.MODIFIED,
            WorkingContentStatus.MISSING,
            WorkingContentStatus.UNREADABLE,
        }
    ),
    WorkingContentStatus.MODIFIED: frozenset(
        {
            WorkingContentStatus.CLEAN,
            WorkingContentStatus.MODIFIED,
            WorkingContentStatus.MISSING,
            WorkingContentStatus.UNREADABLE,
        }
    ),
    WorkingContentStatus.MISSING: frozenset(
        {
            WorkingContentStatus.CLEAN,
            WorkingContentStatus.MODIFIED,
            WorkingContentStatus.MISSING,
            WorkingContentStatus.UNREADABLE,
        }
    ),
    WorkingContentStatus.UNREADABLE: frozenset(
        {
            WorkingContentStatus.CLEAN,
            WorkingContentStatus.MODIFIED,
            WorkingContentStatus.MISSING,
            WorkingContentStatus.UNREADABLE,
        }
    ),
    WorkingContentStatus.CHECKING: frozenset(
        {
            WorkingContentStatus.CLEAN,
            WorkingContentStatus.MODIFIED,
            WorkingContentStatus.MISSING,
            WorkingContentStatus.UNREADABLE,
        }
    ),
}


def require_import_session_transition(
    current: ImportSessionStatus, target: ImportSessionStatus
) -> None:
    _require_transition(current, target, _IMPORT_SESSION_TRANSITIONS)


def require_import_item_transition(
    current: ImportItemStatus, target: ImportItemStatus
) -> None:
    _require_transition(current, target, _IMPORT_ITEM_TRANSITIONS)


def require_original_snapshot_transition(
    current: OriginalSnapshotStatus, target: OriginalSnapshotStatus
) -> None:
    _require_transition(current, target, _ORIGINAL_SNAPSHOT_TRANSITIONS)


def require_original_artifact_integrity_transition(
    current: ArtifactIntegrityStatus, target: ArtifactIntegrityStatus
) -> None:
    _require_transition(current, target, _ORIGINAL_ARTIFACT_INTEGRITY_TRANSITIONS)


def require_workspace_lifecycle_transition(
    current: WorkspaceItemLifecycleStatus,
    target: WorkspaceItemLifecycleStatus,
) -> None:
    _require_transition(current, target, _WORKSPACE_LIFECYCLE_TRANSITIONS)


def require_workspace_materialization_transition(
    current: WorkspaceMaterializationStatus,
    target: WorkspaceMaterializationStatus,
) -> None:
    _require_transition(current, target, _WORKSPACE_MATERIALIZATION_TRANSITIONS)


def require_working_content_transition(
    current: WorkingContentStatus, target: WorkingContentStatus
) -> None:
    _require_transition(current, target, _WORKING_CONTENT_TRANSITIONS)
