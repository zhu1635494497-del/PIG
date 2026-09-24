from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pig.application import (
    CreateProjectRequest,
    GetNodeRequest,
    GetProjectTreeRequest,
    LoadProjectRequest,
    OpenNodeRequest,
    ProcessProjectRequest,
    RegisterSourceRequest,
    SearchNodesRequest,
)
from pig.application.errors import ApplicationError
from pig.bootstrap import create_local_application
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    EventType,
    NodeFormat,
    SourceKind,
    SourceStatus,
)


@dataclass
class RecordingOpener:
    paths: list[Path] = field(default_factory=list)
    failure: Exception | None = None

    def open(self, path: Path) -> None:
        if self.failure is not None:
            raise self.failure
        self.paths.append(path)


@pytest.fixture
def runtime(tmp_path: Path):
    opener = RecordingOpener()
    app = create_local_application(
        (tmp_path / "workspace").absolute(), file_opener=opener
    )
    project = app.create_project(
        CreateProjectRequest(name="M9", actor="desktop-test")
    )
    return app, project, opener


def _register_and_process(app, project, path: Path):
    registered = app.register_source(
        RegisterSourceRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            source_path=path.absolute(),
            source_kind=SourceKind.FILE,
            actor="desktop-test",
        )
    )
    app.process_project(
        ProcessProjectRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            actor="desktop-test",
        )
    )
    return registered


def _open(app, project, node_id: str):
    return app.open_node(
        OpenNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=node_id,
            actor="desktop-test",
        )
    )


def test_load_project_and_tree_are_read_only_application_queries(
    runtime, tmp_path: Path
) -> None:
    app, project, _ = runtime
    archive = tmp_path / "evidence.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("folder/report.pdf", b"%PDF-1.7 evidence")
    registered = _register_and_process(app, project, archive)

    overview = app.load_project(
        LoadProjectRequest(database_path=project.database_path)
    )
    tree = app.get_project_tree(
        GetProjectTreeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )
    after = app.load_project(
        LoadProjectRequest(database_path=project.database_path)
    )

    assert overview.project.id == project.project_id
    assert tree.project.id == project.project_id
    assert tree.items[0].node.id == registered.root_node_id
    child_items = [item for item in tree.items if item.parent_node_id is not None]
    assert len(child_items) == 2
    archive_folder = next(
        item for item in child_items if item.node.format == NodeFormat.FOLDER
    )
    document = next(
        item for item in child_items if item.node.format == NodeFormat.PDF
    )
    assert archive_folder.parent_node_id == registered.root_node_id
    assert archive_folder.relationship_type.value == "ARCHIVE_ENTRY"
    assert document.parent_node_id == archive_folder.node.id
    assert document.relationship_type.value == "FOLDER_CONTAINS"
    assert len(after.events) == len(overview.events)


def test_allowed_original_pdf_is_reverified_audited_and_opened(
    runtime, tmp_path: Path
) -> None:
    app, project, opener = runtime
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.7 evidence")
    registered = _register_and_process(app, project, source)

    result = _open(app, project, registered.root_node_id)

    assert result.path == source.absolute()
    assert opener.paths == [source.absolute()]
    overview = app.load_project(
        LoadProjectRequest(database_path=project.database_path)
    )
    event_types = [event.event_type for event in overview.events]
    assert EventType.FILE_OPEN_REQUESTED in event_types
    assert EventType.SOURCE_VERIFICATION_STARTED in event_types
    assert EventType.ARTIFACT_VERIFIED in event_types
    assert event_types[-1] == EventType.FILE_OPENED
    details = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=registered.root_node_id,
        )
    )
    assert details.source.status == SourceStatus.AVAILABLE
    assert details.artifacts[0].integrity_status == ArtifactIntegrityStatus.VERIFIED


def test_unknown_format_is_denied_before_handoff(runtime, tmp_path: Path) -> None:
    app, project, opener = runtime
    source = tmp_path / "payload.exe"
    source.write_bytes(b"MZ-not-executable")
    registered = _register_and_process(app, project, source)

    with pytest.raises(ApplicationError) as denied:
        _open(app, project, registered.root_node_id)

    assert denied.value.code == "OPEN_FORMAT_DENIED"
    assert opener.paths == []
    overview = app.load_project(
        LoadProjectRequest(database_path=project.database_path)
    )
    assert [event.event_type for event in overview.events][-2:] == [
        EventType.FILE_OPEN_REQUESTED,
        EventType.FILE_OPEN_DENIED,
    ]


def test_changed_original_is_denied_and_integrity_state_is_persisted(
    runtime, tmp_path: Path
) -> None:
    app, project, opener = runtime
    source = tmp_path / "changed.pdf"
    source.write_bytes(b"%PDF original")
    registered = _register_and_process(app, project, source)
    source.write_bytes(b"%PDF changed and longer")

    with pytest.raises(ApplicationError) as denied:
        _open(app, project, registered.root_node_id)

    assert denied.value.code == "SOURCE_FINGERPRINT_MISMATCH"
    assert opener.paths == []
    details = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=registered.root_node_id,
        )
    )
    assert details.source.status == SourceStatus.CHANGED
    assert details.artifacts[0].integrity_status == ArtifactIntegrityStatus.MISMATCH


def test_folder_descendant_is_resolved_through_persisted_relationships(
    runtime, tmp_path: Path
) -> None:
    app, project, opener = runtime
    source_folder = tmp_path / "采购资料"
    nested = source_folder / "邮件资料"
    nested.mkdir(parents=True)
    document = nested / "报价.pdf"
    document.write_bytes(b"%PDF folder evidence")
    app.register_source(
        RegisterSourceRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            source_path=source_folder.absolute(),
            source_kind=SourceKind.FOLDER,
            actor="desktop-test",
        )
    )
    app.process_project(
        ProcessProjectRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            actor="desktop-test",
        )
    )
    hit = app.search_nodes(
        SearchNodesRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            formats=(NodeFormat.PDF,),
        )
    ).items[0]

    result = _open(app, project, hit.node.id)

    assert result.path == document.absolute()
    assert opener.paths == [document.absolute()]


def test_extracted_pdf_is_verified_in_workspace_before_open(
    runtime, tmp_path: Path
) -> None:
    app, project, opener = runtime
    archive = tmp_path / "nested.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("report.pdf", b"%PDF nested")
    _register_and_process(app, project, archive)
    search = app.search_nodes(
        SearchNodesRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            formats=(NodeFormat.PDF,),
        )
    )

    result = _open(app, project, search.items[0].node.id)

    assert result.path.is_file()
    assert project.workspace_path in result.path.parents
    assert result.path.suffix == ".pdf"
    assert ".open-handoff" in result.path.parts
    assert opener.paths == [result.path]


def test_tampered_workspace_artifact_is_denied_before_handoff(
    runtime, tmp_path: Path
) -> None:
    app, project, opener = runtime
    archive = tmp_path / "tamper.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("report.pdf", b"%PDF accepted")
    _register_and_process(app, project, archive)
    hit = app.search_nodes(
        SearchNodesRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            formats=(NodeFormat.PDF,),
        )
    ).items[0]
    details = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=hit.node.id,
        )
    )
    artifact_path = project.workspace_path.joinpath(
        *details.artifacts[0].locator.split("/")
    )
    artifact_path.write_bytes(b"tampered")

    with pytest.raises(ApplicationError) as denied:
        _open(app, project, hit.node.id)

    assert denied.value.code == "ARTIFACT_HASH_MISMATCH"
    assert opener.paths == []
    after = app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=hit.node.id,
        )
    )
    assert after.artifacts[0].integrity_status == ArtifactIntegrityStatus.MISMATCH


def test_host_handoff_failure_is_structured_and_audited(
    runtime, tmp_path: Path
) -> None:
    app, project, opener = runtime
    source = tmp_path / "handoff.pdf"
    source.write_bytes(b"%PDF")
    registered = _register_and_process(app, project, source)
    opener.failure = OSError("association unavailable")

    with pytest.raises(ApplicationError) as failure:
        _open(app, project, registered.root_node_id)

    assert failure.value.code == "OPEN_HANDOFF_FAILED"
    overview = app.load_project(
        LoadProjectRequest(database_path=project.database_path)
    )
    assert overview.events[-1].event_type == EventType.FILE_OPEN_FAILED
    assert overview.events[-1].error_code.value == "OPEN_HANDOFF_FAILED"
