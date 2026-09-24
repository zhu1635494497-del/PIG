from __future__ import annotations

import hashlib
import stat
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pig.application import (
    CreateProjectRequest,
    GetNodeRequest,
    GetProjectOverviewRequest,
    ProcessNodeRequest,
    RegisterSourceRequest,
)
from pig.bootstrap import create_local_application
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    ArtifactRole,
    ArtifactScope,
    AttemptStatus,
    ErrorCode,
    EventType,
    JobStatus,
    NodeFormat,
    NodeKind,
    NodeProcessingStatus,
    RelationshipType,
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
        return f"id-{self.number}"


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


def create_project(app):
    return app.create_project(CreateProjectRequest(name="M4", actor="tester"))


def register(app, project, path: Path, kind: SourceKind):
    return app.register_source(
        RegisterSourceRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            source_path=path.absolute(),
            source_kind=kind,
            actor="tester",
        )
    )


def process(app, project, node_id: str, policy: ProcessingPolicy | None = None):
    return app.process_node(
        ProcessNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=node_id,
            actor="tester",
            policy=policy or ProcessingPolicy(),
        )
    )


def test_terminal_file_is_detected_and_completed_without_handler(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    source_path = tmp_path / "report.pdf"
    source_path.write_bytes(b"%PDF-1.7 evidence")
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(app, project, source.root_node_id)

    assert result.node_status == NodeProcessingStatus.SUCCESS
    assert result.job_status == JobStatus.SUCCESS
    assert result.child_node_ids == ()
    detail = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=source.root_node_id,
        )
    )
    assert detail.node.kind == NodeKind.FILE
    assert detail.node.format == NodeFormat.PDF
    assert detail.node.status == NodeProcessingStatus.SUCCESS
    assert detail.children == ()
    assert detail.source.status == SourceStatus.AVAILABLE
    assert detail.artifacts[0].integrity_status == ArtifactIntegrityStatus.VERIFIED

    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        job = uow.processing.get_job(result.job_id)
        attempt = uow.processing.get_attempt(result.attempt_id)
    assert job is not None and job.status == JobStatus.SUCCESS
    assert attempt is not None and attempt.status == AttemptStatus.COMPLETED
    assert attempt.error is None


def test_folder_handler_discovers_only_one_level_and_external_artifacts(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    folder = tmp_path / "采购资料"
    folder.mkdir()
    (folder / "报价.pdf").write_bytes(b"pdf")
    nested = folder / "邮件"
    nested.mkdir()
    (nested / "not-yet-discovered.txt").write_text("later", encoding="utf-8")
    nested_zip = folder / "附件.zip"
    with zipfile.ZipFile(nested_zip, "w") as archive:
        archive.writestr("inside.txt", "inside")
    source = register(app, project, folder, SourceKind.FOLDER)

    result = process(app, project, source.root_node_id)

    assert result.node_status == NodeProcessingStatus.SUCCESS
    assert len(result.child_node_ids) == 3
    root = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=source.root_node_id,
        )
    )
    children = {child.original_name: child for child in root.children}
    assert set(children) == {"报价.pdf", "邮件", "附件.zip"}
    assert children["报价.pdf"].format == NodeFormat.PDF
    assert children["附件.zip"].kind == NodeKind.CONTAINER
    assert children["附件.zip"].format == NodeFormat.ZIP
    assert children["附件.zip"].status == NodeProcessingStatus.DISCOVERED
    assert children["邮件"].format == NodeFormat.FOLDER
    assert "not-yet-discovered.txt" not in children

    file_detail = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=children["报价.pdf"].id,
        )
    )
    assert file_detail.artifacts[0].scope == ArtifactScope.EXTERNAL_SOURCE
    assert file_detail.artifacts[0].role == ArtifactRole.ORIGINAL_REFERENCE
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        relationship = uow.catalog.relationship_for_child(children["报价.pdf"].id)
    assert relationship is not None
    assert relationship.type == RelationshipType.FOLDER_CONTAINS
    assert [item.distance for item in file_detail.lineage] == [1, 0]


def test_zip_handler_extracts_to_artifact_id_layout_and_keeps_direct_lineage(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    source_path = tmp_path / "采购资料.zip"
    with zipfile.ZipFile(source_path, "w") as archive:
        archive.writestr("邮件资料/供应商报价.pdf", b"first")
        archive.writestr("邮件资料/最终报价.xlsx", b"PK\x03\x04office")
        archive.writestr("供应商报价.pdf", b"second")
    original_bytes = source_path.read_bytes()
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(app, project, source.root_node_id)

    assert result.node_status == NodeProcessingStatus.SUCCESS
    assert result.job_status == JobStatus.SUCCESS
    assert len(result.child_node_ids) == 4
    assert source_path.read_bytes() == original_bytes
    root = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=source.root_node_id,
        )
    )
    assert root.node.format == NodeFormat.ZIP
    assert {child.logical_path for child in root.children} == {
        "/采购资料.zip!/邮件资料",
        "/采购资料.zip!/供应商报价.pdf",
    }
    archive_folder = next(
        child for child in root.children if child.format == NodeFormat.FOLDER
    )
    folder_detail = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=archive_folder.id,
        )
    )
    assert {child.logical_path for child in folder_detail.children} == {
        "/采购资料.zip!/邮件资料/供应商报价.pdf",
        "/采购资料.zip!/邮件资料/最终报价.xlsx",
    }
    nested_xlsx = next(
        child for child in folder_detail.children if child.original_name.endswith("xlsx")
    )
    assert nested_xlsx.format == NodeFormat.XLSX
    assert nested_xlsx.kind == NodeKind.FILE

    all_children = tuple(root.children) + tuple(folder_detail.children)
    for child in all_children:
        detail = app.get_node(
            GetNodeRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                node_id=child.id,
            )
        )
        expected_distances = (
            [1, 0]
            if child.id in {item.id for item in root.children}
            else [2, 1, 0]
        )
        assert [item.distance for item in detail.lineage] == expected_distances
        if child.format == NodeFormat.FOLDER:
            assert detail.artifacts == ()
            continue
        artifact = detail.artifacts[0]
        assert artifact.scope == ArtifactScope.PROJECT_WORKSPACE
        assert artifact.role == ArtifactRole.EXTRACTED_ARTIFACT
        parts = Path(artifact.locator).parts
        assert parts[0] == "artifacts"
        assert parts[-1] == "content"
        physical = project.workspace_path.joinpath(*parts)
        assert physical.is_file()
        assert hashlib.sha256(physical.read_bytes()).hexdigest() == artifact.sha256
    assert not (project.workspace_path / "邮件资料").exists()
    assert not (project.workspace_path / ".staging").exists()


def test_zip_persists_explicit_and_implicit_directories_as_real_hierarchy(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    source_path = tmp_path / "nested.zip"
    with zipfile.ZipFile(source_path, "w") as archive:
        archive.writestr("level-one/", b"")
        archive.writestr("level-one/level-two/report.pdf", b"%PDF")
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(app, project, source.root_node_id)

    assert len(result.child_node_ids) == 3
    root = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=source.root_node_id,
        )
    )
    assert [child.display_name for child in root.children] == ["level-one"]
    level_one = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=root.children[0].id,
        )
    )
    assert [child.display_name for child in level_one.children] == ["level-two"]
    level_two = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=level_one.children[0].id,
        )
    )
    assert [child.display_name for child in level_two.children] == ["report.pdf"]
    document = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=level_two.children[0].id,
        )
    )
    assert document.node.depth == 3
    assert [item.distance for item in document.lineage] == [3, 2, 1, 0]
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        root_relationship = uow.catalog.relationship_for_child(level_one.node.id)
        nested_relationship = uow.catalog.relationship_for_child(level_two.node.id)
    assert root_relationship is not None
    assert root_relationship.type == RelationshipType.ARCHIVE_ENTRY
    assert nested_relationship is not None
    assert nested_relationship.type == RelationshipType.FOLDER_CONTAINS


def test_archive_internal_directory_depth_is_enforced(app, tmp_path: Path) -> None:
    project = create_project(app)
    source_path = tmp_path / "deep.zip"
    with zipfile.ZipFile(source_path, "w") as archive:
        archive.writestr("one/two/report.pdf", b"%PDF")
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(
        app,
        project,
        source.root_node_id,
        ProcessingPolicy(max_depth=2),
    )

    assert result.node_status == NodeProcessingStatus.PARTIAL_SUCCESS
    assert result.warning_count == 1
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
    document = next(node for node in nodes if node.display_name == "report.pdf")
    assert document.depth == 3
    assert document.status == NodeProcessingStatus.LIMIT_EXCEEDED
    details = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=document.id,
        )
    )
    assert details.artifacts == ()


def test_duplicate_zip_names_get_distinct_nodes_and_artifacts(app, tmp_path: Path) -> None:
    project = create_project(app)
    source_path = tmp_path / "duplicate.zip"
    with pytest.warns(UserWarning):
        with zipfile.ZipFile(source_path, "w") as archive:
            archive.writestr("报价.txt", b"one")
            archive.writestr("报价.txt", b"two")
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(app, project, source.root_node_id)

    assert len(result.child_node_ids) == 2
    root = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=source.root_node_id,
        )
    )
    assert [child.discovery_key for child in root.children] == [
        "zip-entry:0",
        "zip-entry:1",
    ]
    artifacts = []
    for child in root.children:
        detail = app.get_node(
            GetNodeRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                node_id=child.id,
            )
        )
        artifacts.append(detail.artifacts[0])
    assert artifacts[0].id != artifacts[1].id
    assert artifacts[0].locator != artifacts[1].locator


@pytest.mark.parametrize(
    ("unsafe_name", "expected_code"),
    [
        ("../../outside.txt", ErrorCode.PATH_TRAVERSAL_BLOCKED),
        ("/etc/passwd", ErrorCode.ABSOLUTE_PATH_BLOCKED),
        ("C:\\Windows\\system.ini", ErrorCode.ABSOLUTE_PATH_BLOCKED),
        ("\\\\?\\C:\\device.txt", ErrorCode.DEVICE_PATH_BLOCKED),
    ],
)
def test_unsafe_zip_entry_is_cataloged_as_blocked_but_never_written(
    app, tmp_path: Path, unsafe_name: str, expected_code: ErrorCode
) -> None:
    project = create_project(app)
    source_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(source_path, "w") as archive:
        archive.writestr(unsafe_name, b"unsafe")
        archive.writestr("safe.txt", b"safe")
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(app, project, source.root_node_id)

    assert result.node_status == NodeProcessingStatus.PARTIAL_SUCCESS
    assert result.warning_count == 1
    root = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=source.root_node_id,
        )
    )
    blocked = next(
        child
        for child in root.children
        if child.status == NodeProcessingStatus.SECURITY_BLOCKED
    )
    assert blocked.status == NodeProcessingStatus.SECURITY_BLOCKED
    assert ".." not in blocked.logical_path.split("!/")[-1].split("/")
    detail = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=blocked.id,
        )
    )
    assert detail.artifacts == ()
    assert not (project.workspace_path.parent / "outside.txt").exists()
    overview = app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )
    blocked_events = [
        event
        for event in overview.events
        if event.node_id == blocked.id
        and event.event_type == EventType.NODE_PROCESSING_BLOCKED
    ]
    assert blocked_events[-1].error_code == expected_code


def test_single_file_limit_blocks_entry_without_partial_artifact(app, tmp_path: Path) -> None:
    project = create_project(app)
    source_path = tmp_path / "limit.zip"
    with zipfile.ZipFile(source_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("large.bin", b"12345")
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(
        app,
        project,
        source.root_node_id,
        ProcessingPolicy(max_single_file_size=4),
    )

    assert result.node_status == NodeProcessingStatus.PARTIAL_SUCCESS
    child = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=result.child_node_ids[0],
        )
    )
    assert child.node.status == NodeProcessingStatus.LIMIT_EXCEEDED
    assert child.artifacts == ()
    artifacts_root = project.workspace_path / "artifacts"
    assert not artifacts_root.exists() or not any(artifacts_root.rglob("content"))


def test_corrupted_zip_is_a_durable_expected_processing_outcome(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    source_path = tmp_path / "corrupted.zip"
    source_path.write_bytes(b"not a zip")
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(app, project, source.root_node_id)

    assert result.node_status == NodeProcessingStatus.CORRUPTED
    assert result.job_status == JobStatus.FAILED
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        attempt = uow.processing.get_attempt(result.attempt_id)
    assert attempt is not None
    assert attempt.status == AttemptStatus.COMPLETED
    assert attempt.error is not None
    assert attempt.error.code == ErrorCode.CORRUPTED_CONTAINER


def test_changed_external_source_is_blocked_and_accepted_fingerprint_is_preserved(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    source_path = tmp_path / "changed.zip"
    with zipfile.ZipFile(source_path, "w") as archive:
        archive.writestr("before.txt", "before")
    registered = register(app, project, source_path, SourceKind.FILE)
    overview_before = app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )
    accepted_hash = overview_before.sources[0].source.observed_sha256
    source_path.write_bytes(b"changed bytes")

    result = process(app, project, registered.root_node_id)

    assert result.node_status == NodeProcessingStatus.SOURCE_CHANGED
    detail = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=registered.root_node_id,
        )
    )
    assert detail.source.status == SourceStatus.CHANGED
    assert detail.source.observed_sha256 == accepted_hash
    assert detail.artifacts[0].sha256 == accepted_hash
    assert detail.artifacts[0].integrity_status == ArtifactIntegrityStatus.MISMATCH


def test_missing_external_source_is_durable_and_no_handler_runs(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    source_path = tmp_path / "missing-after-registration.pdf"
    source_path.write_bytes(b"evidence")
    registered = register(app, project, source_path, SourceKind.FILE)
    source_path.unlink()

    result = process(app, project, registered.root_node_id)

    assert result.node_status == NodeProcessingStatus.SOURCE_MISSING
    detail = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=registered.root_node_id,
        )
    )
    assert detail.source.status == SourceStatus.MISSING
    assert detail.artifacts[0].integrity_status == ArtifactIntegrityStatus.MISSING
    assert detail.node.format == NodeFormat.UNKNOWN
    overview = app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )
    assert EventType.SOURCE_MISSING_DETECTED in {
        event.event_type for event in overview.events
    }
    assert EventType.ARTIFACT_INTEGRITY_FAILED in {
        event.event_type for event in overview.events
    }


def test_zip_symbolic_link_entry_is_evidence_but_is_never_materialized(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    source_path = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("link-to-secret")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(source_path, "w") as archive:
        archive.writestr(link, "../../secret.txt")
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(app, project, source.root_node_id)

    assert result.node_status == NodeProcessingStatus.PARTIAL_SUCCESS
    child = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=result.child_node_ids[0],
        )
    )
    assert child.node.status == NodeProcessingStatus.SECURITY_BLOCKED
    assert child.artifacts == ()
    overview = app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )
    event = next(
        event
        for event in overview.events
        if event.node_id == child.node.id
        and event.event_type == EventType.NODE_PROCESSING_BLOCKED
    )
    assert event.error_code == ErrorCode.SYMLINK_BLOCKED
    assert event.details["handler"] == "zip-stdlib"
    assert event.details["retryable"] is False


def test_archive_entry_count_limit_finishes_root_without_children(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    source_path = tmp_path / "entries.zip"
    with zipfile.ZipFile(source_path, "w") as archive:
        archive.writestr("one.txt", "one")
        archive.writestr("two.txt", "two")
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(
        app,
        project,
        source.root_node_id,
        ProcessingPolicy(max_archive_entries=1),
    )

    assert result.node_status == NodeProcessingStatus.LIMIT_EXCEEDED
    assert result.child_node_ids == ()
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        attempt = uow.processing.get_attempt(result.attempt_id)
        job = uow.processing.get_job(result.job_id)
    assert attempt is not None and attempt.error is not None
    assert attempt.error.code == ErrorCode.MAX_ARCHIVE_ENTRIES_EXCEEDED
    assert job is not None
    assert job.policy_snapshot["max_archive_entries"] == 1


def test_empty_zip_is_detected_by_end_record_signature_and_succeeds(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    source_path = tmp_path / "empty.data"
    with zipfile.ZipFile(source_path, "w"):
        pass
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(app, project, source.root_node_id)

    assert result.node_status == NodeProcessingStatus.SUCCESS
    detail = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=source.root_node_id,
        )
    )
    assert detail.node.format == NodeFormat.ZIP
    assert detail.children == ()


def test_encrypted_zip_entry_is_password_required_and_never_extracted(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    source_path = tmp_path / "encrypted.zip"
    with zipfile.ZipFile(source_path, "w") as archive:
        archive.writestr("secret.txt", "secret")
    payload = bytearray(source_path.read_bytes())
    local = payload.index(b"PK\x03\x04")
    central = payload.index(b"PK\x01\x02")
    payload[local + 6 : local + 8] = (
        int.from_bytes(payload[local + 6 : local + 8], "little") | 1
    ).to_bytes(2, "little")
    payload[central + 8 : central + 10] = (
        int.from_bytes(payload[central + 8 : central + 10], "little") | 1
    ).to_bytes(2, "little")
    source_path.write_bytes(payload)
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(app, project, source.root_node_id)

    assert result.node_status == NodeProcessingStatus.PARTIAL_SUCCESS
    assert result.warning_count == 1
    child = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=result.child_node_ids[0],
        )
    )
    assert child.node.status == NodeProcessingStatus.PASSWORD_REQUIRED
    assert child.artifacts == ()
    assert not (project.workspace_path / "artifacts").exists()


def test_compression_ratio_policy_blocks_probable_zip_bomb_entry(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    source_path = tmp_path / "ratio.zip"
    with zipfile.ZipFile(
        source_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr("repeated.txt", b"0" * 10_000)
    source = register(app, project, source_path, SourceKind.FILE)

    result = process(
        app,
        project,
        source.root_node_id,
        ProcessingPolicy(max_compression_ratio=2.0),
    )

    child = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=result.child_node_ids[0],
        )
    )
    assert child.node.status == NodeProcessingStatus.LIMIT_EXCEEDED
    assert child.artifacts == ()
    overview = app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )
    event = next(
        event
        for event in overview.events
        if event.node_id == child.node.id
        and event.event_type == EventType.NODE_PROCESSING_BLOCKED
    )
    assert event.error_code == ErrorCode.MAX_COMPRESSION_RATIO_EXCEEDED


def test_project_node_limit_counts_existing_root_before_accepting_children(
    app, tmp_path: Path
) -> None:
    project = create_project(app)
    folder = tmp_path / "one-child"
    folder.mkdir()
    (folder / "child.txt").write_text("child", encoding="utf-8")
    source = register(app, project, folder, SourceKind.FOLDER)

    result = process(
        app,
        project,
        source.root_node_id,
        ProcessingPolicy(max_node_count=1),
    )

    assert result.node_status == NodeProcessingStatus.LIMIT_EXCEEDED
    assert result.child_node_ids == ()
    detail = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=source.root_node_id,
        )
    )
    assert detail.children == ()
