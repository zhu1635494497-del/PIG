from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from pig.application import (
    CreateProjectRequest,
    ExportWorkspaceItemsRequest,
    OpenWorkspaceItemRequest,
    RefreshWorkingArtifactRequest,
    RollbackWorkingArtifactRequest,
)
from pig.application.contracts import (
    ImportProjectItemsRequest,
    InspectImportSessionRequest,
)
from pig.application.errors import ApplicationError
from pig.bootstrap import create_local_application
from pig.domain.enums import EventType, WorkingRevisionRole
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase


class RecordingOpener:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def open(self, path: Path) -> None:
        self.paths.append(path)


def _project(tmp_path: Path, sources: tuple[Path, ...]):
    opener = RecordingOpener()
    app = create_local_application(tmp_path / "projects", file_opener=opener)
    project = app.create_project(CreateProjectRequest(name="W7.1", actor="tester"))
    imported = app.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=sources,
            actor="tester",
        )
    )
    app.inspect_import_session(
        InspectImportSessionRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            import_session_id=imported.import_session_id,
            actor="tester",
        )
    )
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        items = tuple(uow.workspace.items_for_project(project.project_id))
    return app, project, items, opener


def _open(app, project, item):
    return app.open_workspace_item(
        OpenWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
        )
    )


def test_friendly_working_name_keeps_only_current_and_previous_and_rolls_back(
    tmp_path: Path,
) -> None:
    source = tmp_path / "最终报价.txt"
    source.write_bytes(b"baseline")
    app, project, (item,), opener = _project(tmp_path, (source,))

    opened = _open(app, project, item)
    assert opened.path.name == "最终报价.txt"
    assert opener.paths == [opened.path]
    opened.path.write_bytes(b"save one")
    app.refresh_working_artifact(
        RefreshWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
        )
    )
    opened.path.write_bytes(b"save two")
    app.refresh_working_artifact(
        RefreshWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
        )
    )

    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        artifact = uow.workspace.working_artifact_for_item(item.id)
        revisions = uow.workspace.working_revisions_for_artifact(artifact.id)
    assert len(revisions) == 2
    by_role = {value.role: value for value in revisions}
    assert by_role[WorkingRevisionRole.CURRENT_CHECKPOINT].sha256 == hashlib.sha256(
        b"save two"
    ).hexdigest()
    assert by_role[WorkingRevisionRole.PREVIOUS].sha256 == hashlib.sha256(
        b"save one"
    ).hexdigest()

    rolled_back = app.rollback_working_artifact(
        RollbackWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
            confirmed_replace=True,
        )
    )
    assert rolled_back.path.read_bytes() == b"save one"
    assert rolled_back.previous_revision.sha256 == hashlib.sha256(
        b"save two"
    ).hexdigest()

    toggled = app.rollback_working_artifact(
        RollbackWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
            confirmed_replace=True,
        )
    )
    assert toggled.path.read_bytes() == b"save two"
    assert source.read_bytes() == b"baseline"
    with database.unit_of_work(project.database_path) as uow:
        events = uow.processing.events_for_project(project.project_id)
    event_types = [event.event_type for event in events]
    assert event_types.count(EventType.WORKING_VERSION_CAPTURED) == 2
    assert event_types.count(EventType.WORKING_FILE_ROLLED_BACK) == 2


def test_single_exports_current_bytes_and_multiple_exports_workspace_named_zip(
    tmp_path: Path,
) -> None:
    first = tmp_path / "报价.txt"
    second = tmp_path / "说明.csv"
    first.write_bytes(b"original quote")
    second.write_bytes(b"code,value\nA,1\n")
    app, project, items, _opener = _project(tmp_path, (first, second))
    by_name = {item.display_name: item for item in items}
    opened = _open(app, project, by_name["报价.txt"])
    opened.path.write_bytes(b"approved quote")

    single_target = tmp_path / "deliverables" / "最终报价.txt"
    single_target.parent.mkdir()
    single = app.export_workspace_items(
        ExportWorkspaceItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_ids=(by_name["报价.txt"].id,),
            destination_path=single_target,
            actor="tester",
        )
    )
    assert single.archive is False
    assert single_target.read_bytes() == b"approved quote"

    zip_target = tmp_path / "deliverables" / "交付包.zip"
    bundle = app.export_workspace_items(
        ExportWorkspaceItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_ids=(
                by_name["报价.txt"].id,
                by_name["说明.csv"].id,
            ),
            destination_path=zip_target,
            actor="tester",
        )
    )
    assert bundle.archive is True and bundle.entry_count == 2
    with zipfile.ZipFile(zip_target) as archive:
        assert set(archive.namelist()) == {"报价.txt", "说明.csv"}
        assert archive.read("报价.txt") == b"approved quote"
        assert archive.read("说明.csv") == b"code,value\nA,1\n"
    assert first.read_bytes() == b"original quote"
    assert second.read_bytes() == b"code,value\nA,1\n"


def test_multi_export_rejects_same_workspace_relative_path(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "same.txt").write_bytes(b"left")
    (right / "same.txt").write_bytes(b"right")
    app, project, items, _opener = _project(
        tmp_path, (left / "same.txt", right / "same.txt")
    )

    with pytest.raises(ApplicationError) as collision:
        app.export_workspace_items(
            ExportWorkspaceItemsRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                workspace_item_ids=tuple(item.id for item in items),
                destination_path=tmp_path / "collision.zip",
                actor="tester",
            )
        )
    assert collision.value.code == "EXPORT_PATH_COLLISION"
    assert not (tmp_path / "collision.zip").exists()
