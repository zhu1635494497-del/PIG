from __future__ import annotations

from pathlib import Path

import pytest

from pig.application import (
    AddWorkspaceInputsRequest,
    CreateProjectRequest,
    ExportWorkspaceItemsRequest,
    GetWorkspaceTreeRequest,
    PreviewImportUndoRequest,
    UndoImportedItemRequest,
)
from pig.application.contracts import MaterializeWorkspaceItemRequest
from pig.application.errors import ApplicationError
from pig.bootstrap import create_local_application
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    EventType,
    OriginalSnapshotStatus,
    SourceStatus,
    WorkspaceExportKind,
    WorkspaceItemLifecycleStatus,
)
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase


def _project(tmp_path: Path, name: str = "W7.2 Project"):
    application = create_local_application(tmp_path / "projects")
    project = application.create_project(
        CreateProjectRequest(name=name, actor="tester")
    )
    return application, project


def _add(application, project, paths: tuple[Path, ...]):
    return application.add_workspace_inputs(
        AddWorkspaceInputsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=paths,
            actor="tester",
            expected_workspace_revision=0,
        )
    )


def _tree(application, project):
    return application.get_workspace_tree(
        GetWorkspaceTreeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )


def test_project_uses_human_named_directory_and_keeps_uuid_as_identity(
    tmp_path: Path,
) -> None:
    application, project = _project(tmp_path, "测试000")

    assert project.database_path == tmp_path / "projects" / "测试000" / "project.sqlite"
    assert project.workspace_path == tmp_path / "projects" / "测试000"
    assert project.project_id not in str(project.database_path)

    with pytest.raises(ApplicationError) as collision:
        application.create_project(
            CreateProjectRequest(name="测试000", actor="tester")
        )
    assert collision.value.code == "WORKSPACE_COLLISION"


def test_undo_one_accidentally_selected_top_level_input_only(tmp_path: Path) -> None:
    folder = tmp_path / "A"
    folder.mkdir()
    (folder / "kept.txt").write_bytes(b"keep me")
    accidental = tmp_path / "A.txt"
    accidental.write_bytes(b"remove only from PIG")
    application, project = _project(tmp_path)
    _add(application, project, (folder, accidental))
    roots = {
        view.item.display_name: view
        for view in _tree(application, project).items
        if view.placement.parent_workspace_item_id is None
    }
    accidental_view = roots["A.txt"]

    impact = application.preview_import_undo(
        PreviewImportUndoRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=accidental_view.item.id,
        )
    )
    assert impact.workspace_item_count == 1
    assert impact.display_name == "A.txt"

    result = application.undo_imported_item(
        UndoImportedItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=accidental_view.item.id,
            actor="tester",
            expected_workspace_revision=1,
            confirmed=True,
        )
    )
    assert result.workspace_revision == 2
    assert accidental.read_bytes() == b"remove only from PIG"
    remaining = _tree(application, project)
    assert {view.item.display_name for view in remaining.items} == {"A", "kept.txt"}
    assert not remaining.deleted_items
    assert not (project.workspace_path / "originals" / impact.snapshot_id).exists()

    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        snapshot = uow.imports.get_snapshot(impact.snapshot_id)
        source = uow.catalog.get_source(impact.source_id)
        artifacts = uow.imports.original_artifacts_for_snapshot(impact.snapshot_id)
        purged_item = uow.workspace.get_item(accidental_view.item.id)
        events = uow.processing.events_for_project(project.project_id)
    assert snapshot.status == OriginalSnapshotStatus.PURGED
    assert source.status == SourceStatus.PURGED
    assert {value.integrity_status for value in artifacts} == {
        ArtifactIntegrityStatus.PURGED
    }
    assert purged_item.lifecycle_status == WorkspaceItemLifecycleStatus.PURGED
    assert [event.event_type for event in events][-2:] == [
        EventType.IMPORT_ITEM_UNDO_REQUESTED,
        EventType.IMPORT_ITEM_UNDO_COMPLETED,
    ]


def test_import_undo_rejects_an_embedded_member(tmp_path: Path) -> None:
    folder = tmp_path / "Folder"
    folder.mkdir()
    (folder / "member.txt").write_bytes(b"member")
    application, project = _project(tmp_path)
    _add(application, project, (folder,))
    member = next(
        view for view in _tree(application, project).items
        if view.item.display_name == "member.txt"
    )

    with pytest.raises(ApplicationError) as denied:
        application.preview_import_undo(
            PreviewImportUndoRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                workspace_item_id=member.item.id,
            )
        )
    assert denied.value.code == "IMPORT_ITEM_NOT_UNDOABLE"


def test_folder_export_preserves_structure_empty_folders_and_current_bytes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "交付资料"
    nested = source / "报价" / "最终"
    nested.mkdir(parents=True)
    (source / "空文件夹").mkdir()
    report = nested / "报价.txt"
    report.write_bytes(b"original")
    application, project = _project(tmp_path)
    _add(application, project, (source,))
    tree = _tree(application, project)
    root = next(
        view for view in tree.items
        if view.item.display_name == "交付资料"
        and view.placement.parent_workspace_item_id is None
    )
    report_view = next(
        view for view in tree.items if view.item.display_name == "报价.txt"
    )
    materialized = application.materialize_workspace_item(
        MaterializeWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=report_view.item.id,
            actor="tester",
        )
    )
    materialized.path.write_bytes(b"approved")

    destination = tmp_path / "deliverables" / "交付资料"
    destination.parent.mkdir()
    result = application.export_workspace_items(
        ExportWorkspaceItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_ids=(root.item.id,),
            destination_path=destination,
            actor="tester",
        )
    )

    assert result.export_kind == WorkspaceExportKind.DIRECTORY
    assert result.entry_count == 1
    assert (destination / "报价" / "最终" / "报价.txt").read_bytes() == b"approved"
    assert (destination / "空文件夹").is_dir()
    assert report.read_bytes() == b"original"

    with pytest.raises(ApplicationError) as exists:
        application.export_workspace_items(
            ExportWorkspaceItemsRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                workspace_item_ids=(root.item.id,),
                destination_path=destination,
                actor="tester",
                confirmed_replace=True,
            )
        )
    assert exists.value.code == "EXPORT_DESTINATION_INVALID"
