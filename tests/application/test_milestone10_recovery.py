from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pig.application import (
    CreateProjectRequest,
    GetNodeRequest,
    GetProjectOverviewRequest,
    ProcessProjectRequest,
    RecoverProjectRequest,
    RegisterSourceRequest,
)
from pig.application.errors import ApplicationError
from pig.bootstrap import create_local_application
from pig.domain.entities import ProcessingAttempt, ProcessingJob
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    AttemptStatus,
    EventType,
    JobStatus,
    JobType,
    NodeProcessingStatus,
    ProcessingStage,
    ProjectStatus,
    SourceKind,
    SourceStatus,
)
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase


NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


def _create_stale_project(tmp_path: Path):
    application = create_local_application((tmp_path / "workspace").absolute())
    project = application.create_project(
        CreateProjectRequest(name="Recovery", actor="tester")
    )
    source_path = tmp_path / "report.pdf"
    source_path.write_bytes(b"%PDF recovery")
    registered = application.register_source(
        RegisterSourceRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            source_path=source_path.absolute(),
            source_kind=SourceKind.FILE,
            actor="tester",
        )
    )
    database = SqlAlchemyProjectDatabase()
    old_job_id = "stale-job"
    old_attempt_id = "stale-attempt"
    with database.unit_of_work(project.database_path) as uow:
        uow.projects.update_status(
            project.project_id,
            ProjectStatus.IMPORTING,
            ProjectStatus.PROCESSING,
            NOW,
        )
        uow.processing.add_job(
            ProcessingJob(
                id=old_job_id,
                project_id=project.project_id,
                type=JobType.PROCESS_PROJECT,
                status=JobStatus.RUNNING,
                requested_by="crashed-process",
                policy_snapshot={},
                created_at=NOW,
                started_at=NOW,
            )
        )
        uow.processing.add_attempt(
            ProcessingAttempt(
                id=old_attempt_id,
                project_id=project.project_id,
                job_id=old_job_id,
                node_id=registered.root_node_id,
                attempt_number=1,
                status=AttemptStatus.RUNNING,
                stage=ProcessingStage.VERIFY_SOURCE,
                queued_at=NOW,
                started_at=NOW,
            )
        )
        uow.catalog.update_node_status(
            registered.root_node_id,
            NodeProcessingStatus.DISCOVERED,
            NodeProcessingStatus.PENDING,
            NOW,
        )
        uow.catalog.update_node_status(
            registered.root_node_id,
            NodeProcessingStatus.PENDING,
            NodeProcessingStatus.PROCESSING,
            NOW,
        )
        uow.catalog.update_source_status(
            registered.source_id,
            SourceStatus.AVAILABLE,
            SourceStatus.VERIFYING,
            None,
        )
        uow.catalog.update_artifact_integrity(
            registered.artifact_id,
            ArtifactIntegrityStatus.VERIFIED,
            ArtifactIntegrityStatus.VERIFYING,
            None,
        )
        uow.commit()
    return application, project, registered, old_job_id, old_attempt_id


def test_explicit_recovery_preserves_old_history_and_creates_new_attempt(
    tmp_path: Path,
) -> None:
    app, project, registered, old_job_id, old_attempt_id = _create_stale_project(
        tmp_path
    )
    orphan = (
        project.workspace_path
        / "artifacts"
        / "or"
        / "orphan-artifact"
        / "content"
    )
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"uncommitted")
    staging = project.workspace_path / ".staging" / "stale-attempt"
    staging.mkdir(parents=True)
    (staging / "partial.part").write_bytes(b"partial")

    result = app.recover_project(
        RecoverProjectRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            actor="recovery-operator",
        )
    )

    assert result.interrupted_job_ids == (old_job_id,)
    assert result.interrupted_attempt_ids == (old_attempt_id,)
    assert result.recovered_node_ids == (registered.root_node_id,)
    assert result.processed_node_ids == (registered.root_node_id,)
    assert result.attempt_ids and result.attempt_ids[0] != old_attempt_id
    assert result.project_status == ProjectStatus.READY
    assert result.job_status == JobStatus.PARTIAL_SUCCESS
    assert len(result.quarantine_records) == 2
    assert not orphan.exists()
    assert not (project.workspace_path / ".staging").exists()

    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        assert uow.processing.get_job(old_job_id).status == JobStatus.INTERRUPTED
        assert (
            uow.processing.get_attempt(old_attempt_id).status
            == AttemptStatus.INTERRUPTED
        )
        assert (
            uow.processing.get_job(result.recovery_job_id).type
            == JobType.RECOVER_INTERRUPTED
        )
    details = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=registered.root_node_id,
        )
    )
    assert details.node.status == NodeProcessingStatus.SUCCESS
    assert details.source.status == SourceStatus.AVAILABLE
    assert details.artifacts[0].integrity_status == ArtifactIntegrityStatus.VERIFIED
    overview = app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )
    event_types = {event.event_type for event in overview.events}
    assert {
        EventType.JOB_INTERRUPTED,
        EventType.ATTEMPT_INTERRUPTED,
        EventType.NODE_PROCESSING_INTERRUPTED,
        EventType.ARTIFACT_VERIFICATION_INTERRUPTED,
        EventType.RECOVERY_STARTED,
        EventType.ORPHAN_QUARANTINED,
        EventType.RECOVERY_FINISHED,
    } <= event_types


def test_normal_processing_is_blocked_until_explicit_recovery(
    tmp_path: Path,
) -> None:
    app, project, _, _, _ = _create_stale_project(tmp_path)

    with pytest.raises(ApplicationError) as blocked:
        app.process_project(
            ProcessProjectRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                actor="tester",
            )
        )

    assert blocked.value.code == "RECOVERY_REQUIRED"


def test_workspace_integrity_failure_is_durable_recovery_failure(
    tmp_path: Path,
) -> None:
    app, project, _, _, _ = _create_stale_project(tmp_path)
    (project.workspace_path / "artifacts").write_bytes(b"not-a-directory")

    with pytest.raises(ApplicationError) as failure:
        app.recover_project(
            RecoverProjectRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                actor="recovery-operator",
            )
        )

    assert failure.value.code == "WORKSPACE_INTEGRITY_FAILED"
    overview = app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )
    assert overview.project.status == ProjectStatus.FAILED
    assert overview.events[-1].event_type == EventType.RECOVERY_FAILED
