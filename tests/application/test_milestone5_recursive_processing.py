from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pig.application import (
    CreateProjectRequest,
    GetNodeRequest,
    GetProjectOverviewRequest,
    ProcessNodeRequest,
    ProcessProjectRequest,
    RegisterSourceRequest,
)
from pig.application.errors import ApplicationError
from pig.bootstrap import create_local_application
from pig.domain.entities import ProcessingAttempt, ProcessingJob
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    AttemptStatus,
    JobStatus,
    JobType,
    NodeProcessingStatus,
    ProjectStatus,
    ProcessingStage,
    SourceKind,
    SourceStatus,
)
from pig.domain.processing_policy import ProcessingPolicy
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase


class Sequence:
    def __init__(self) -> None:
        self.number = 0

    def __call__(self) -> str:
        self.number += 1
        return f"m5-id-{self.number}"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 14, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(microseconds=1)
        return current


@pytest.fixture
def app(tmp_path: Path):
    return create_local_application(
        (tmp_path / "workspace").absolute(),
        clock=Clock(),
        id_generator=Sequence(),
    )


def _project(app):
    return app.create_project(CreateProjectRequest(name="M5", actor="tester"))


def _register(app, project, source_path: Path, kind: SourceKind):
    return app.register_source(
        RegisterSourceRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            source_path=source_path.absolute(),
            source_kind=kind,
            actor="tester",
        )
    )


def _process_project(app, project, policy: ProcessingPolicy | None = None):
    return app.process_project(
        ProcessProjectRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            actor="tester",
            policy=policy or ProcessingPolicy(),
        )
    )


def _details(app, project, node_id: str):
    return app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=node_id,
        )
    )


def test_project_action_recursively_processes_folder_and_nested_archives_in_one_job(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_folder = tmp_path / "package"
    source_folder.mkdir()
    nested_folder = source_folder / "mail"
    nested_folder.mkdir()
    inner_bytes = io.BytesIO()
    with zipfile.ZipFile(inner_bytes, "w") as inner:
        inner.writestr("final.xlsx", b"PK\x03\x04workbook")
    with zipfile.ZipFile(nested_folder / "quote.zip", "w") as outer:
        outer.writestr("attachment.zip", inner_bytes.getvalue())
    source = _register(app, project, source_folder, SourceKind.FOLDER)

    result = _process_project(app, project)

    assert result.job_status == JobStatus.SUCCESS
    assert result.project_status == ProjectStatus.READY
    assert len(result.processed_node_ids) == 5
    assert len(result.attempt_ids) == 5
    assert result.total_expanded_size > 0
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
        jobs = tuple(uow.processing.jobs_for_project(project.project_id))
        attempts = tuple(uow.processing.get_attempt(item) for item in result.attempt_ids)
    assert len(jobs) == 1
    assert {attempt.job_id for attempt in attempts if attempt is not None} == {result.job_id}
    final = next(node for node in nodes if node.original_name == "final.xlsx")
    lineage = _details(app, project, final.id).lineage
    assert [(item.distance) for item in lineage] == [4, 3, 2, 1, 0]
    assert source.root_node_id == result.processed_node_ids[0]


def test_total_expanded_size_is_shared_across_all_nodes_in_the_job(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_folder = tmp_path / "two-archives"
    source_folder.mkdir()
    for name in ("a.zip", "b.zip"):
        with zipfile.ZipFile(source_folder / name, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(f"{name}.txt", b"1234")
    _register(app, project, source_folder, SourceKind.FOLDER)

    result = _process_project(
        app, project, ProcessingPolicy(max_total_expanded_size=6)
    )

    assert result.total_expanded_size == 4
    assert result.job_status == JobStatus.PARTIAL_SUCCESS
    assert result.project_status == ProjectStatus.READY_WITH_WARNINGS
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
    blocked = [node for node in nodes if node.status == NodeProcessingStatus.LIMIT_EXCEEDED]
    assert len(blocked) == 1
    assert _details(app, project, blocked[0].id).artifacts == ()


def test_depth_limit_catalogues_boundary_child_but_does_not_schedule_it(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_folder = tmp_path / "deep"
    source_folder.mkdir()
    level_one = source_folder / "level-one"
    level_one.mkdir()
    (level_one / "too-deep.txt").write_text("evidence", encoding="utf-8")
    _register(app, project, source_folder, SourceKind.FOLDER)

    result = _process_project(app, project, ProcessingPolicy(max_depth=1))

    assert len(result.processed_node_ids) == 2
    assert result.project_status == ProjectStatus.READY_WITH_WARNINGS
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
    boundary = next(node for node in nodes if node.original_name == "too-deep.txt")
    assert boundary.depth == 2
    assert boundary.status == NodeProcessingStatus.LIMIT_EXCEEDED
    assert boundary.id not in result.processed_node_ids
    assert _details(app, project, boundary.id).artifacts == ()


def test_external_descendant_is_revalidated_without_changing_folder_source_state(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_folder = tmp_path / "mutable-folder"
    source_folder.mkdir()
    child_path = source_folder / "evidence.pdf"
    child_path.write_bytes(b"%PDF-original")
    source = _register(app, project, source_folder, SourceKind.FOLDER)
    first = app.process_node(
        ProcessNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=source.root_node_id,
            actor="tester",
        )
    )
    child_path.write_bytes(b"%PDF-changed")

    result = _process_project(app, project)

    child = _details(app, project, first.child_node_ids[0])
    assert child.node.status == NodeProcessingStatus.SOURCE_CHANGED
    assert child.artifacts[0].integrity_status == ArtifactIntegrityStatus.MISMATCH
    assert child.source.status == SourceStatus.AVAILABLE
    assert result.project_status == ProjectStatus.READY_WITH_WARNINGS


def test_workspace_artifact_tampering_is_a_durable_integrity_failure(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_path = tmp_path / "archive.zip"
    with zipfile.ZipFile(source_path, "w") as archive:
        archive.writestr("evidence.pdf", b"%PDF-original")
    source = _register(app, project, source_path, SourceKind.FILE)
    first = app.process_node(
        ProcessNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=source.root_node_id,
            actor="tester",
        )
    )
    child_before = _details(app, project, first.child_node_ids[0])
    artifact_path = project.workspace_path.joinpath(*Path(child_before.artifacts[0].locator).parts)
    artifact_path.write_bytes(b"tampered")

    result = _process_project(app, project)

    child_after = _details(app, project, first.child_node_ids[0])
    assert child_after.node.status == NodeProcessingStatus.FAILED
    assert child_after.artifacts[0].integrity_status == ArtifactIntegrityStatus.MISMATCH
    assert result.error_count == 1
    assert result.project_status == ProjectStatus.READY_WITH_WARNINGS


def test_active_job_blocks_new_processing_until_recovery_is_implemented(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_path = tmp_path / "evidence.pdf"
    source_path.write_bytes(b"%PDF")
    _register(app, project, source_path, SourceKind.FILE)
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        uow.processing.add_job(
            ProcessingJob(
                id="interrupted-job",
                project_id=project.project_id,
                type=JobType.PROCESS_PROJECT,
                status=JobStatus.RUNNING,
                requested_by="tester",
                policy_snapshot={},
                created_at=now,
                started_at=now,
            )
        )
        uow.commit()

    with pytest.raises(ApplicationError) as captured:
        _process_project(app, project)

    assert captured.value.code == "RECOVERY_REQUIRED"
    assert captured.value.details["job_ids"] == ["interrupted-job"]


def test_active_attempt_alone_also_requires_explicit_recovery(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_path = tmp_path / "attempt-evidence.pdf"
    source_path.write_bytes(b"%PDF")
    source = _register(app, project, source_path, SourceKind.FILE)
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        uow.processing.add_job(
            ProcessingJob(
                id="finished-job",
                project_id=project.project_id,
                type=JobType.PROCESS_PROJECT,
                status=JobStatus.SUCCESS,
                requested_by="tester",
                policy_snapshot={},
                created_at=now,
                started_at=now,
                finished_at=now,
            )
        )
        uow.processing.add_attempt(
            ProcessingAttempt(
                id="interrupted-attempt",
                project_id=project.project_id,
                job_id="finished-job",
                node_id=source.root_node_id,
                attempt_number=1,
                status=AttemptStatus.RUNNING,
                stage=ProcessingStage.DETECT_FORMAT,
                queued_at=now,
                started_at=now,
            )
        )
        uow.commit()

    with pytest.raises(ApplicationError) as captured:
        _process_project(app, project)

    assert captured.value.code == "RECOVERY_REQUIRED"
    assert captured.value.details["attempt_ids"] == ["interrupted-attempt"]


def test_project_job_policy_snapshot_keeps_the_requested_global_budget(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_path = tmp_path / "plain.txt"
    source_path.write_text("plain", encoding="utf-8")
    _register(app, project, source_path, SourceKind.FILE)
    policy = ProcessingPolicy(max_total_expanded_size=17)

    result = _process_project(app, project, policy)

    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        job = uow.processing.get_job(result.job_id)
    assert job is not None
    assert job.policy_snapshot["max_total_expanded_size"] == 17
    overview = app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )
    job_events = [event for event in overview.events if event.job_id == result.job_id]
    assert sum(event.event_type.value == "JOB_CREATED" for event in job_events) == 1
    assert sum(event.event_type.value == "JOB_FINISHED" for event in job_events) == 1
