from __future__ import annotations

from pathlib import Path

from pig.application import (
    CreateProjectRequest,
    CreateWorkspaceFolderRequest,
    GetWorkspaceItemRequest,
    GetWorkspaceTreeRequest,
    MoveWorkspaceItemRequest,
    SearchWorkspaceItemsRequest,
    SoftDeleteWorkspaceItemRequest,
)
from pig.application.contracts import (
    ImportProjectItemsRequest,
    InspectImportSessionRequest,
    MaterializeWorkspaceItemRequest,
)
from pig.bootstrap import create_local_application
from pig.domain.enums import NodeFormat, WorkingContentStatus


def _project_with_file(tmp_path: Path):
    source = tmp_path / "报价.txt"
    source.write_bytes(b"quote")
    app = create_local_application(tmp_path / "projects")
    project = app.create_project(CreateProjectRequest(name="W7", actor="tester"))
    imported = app.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
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
    tree = app.get_workspace_tree(
        GetWorkspaceTreeRequest(
            project_id=project.project_id, database_path=project.database_path
        )
    )
    return app, project, tree.items[0]


def test_workspace_query_projects_path_origin_working_state_and_revision(
    tmp_path: Path,
) -> None:
    app, project, file_view = _project_with_file(tmp_path)
    folder = app.create_workspace_folder(
        CreateWorkspaceFolderRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            display_name="最终资料",
            actor="tester",
            expected_workspace_revision=1,
        )
    )
    app.move_workspace_item(
        MoveWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=file_view.item.id,
            actor="tester",
            expected_workspace_revision=2,
            new_parent_workspace_item_id=folder.item.id,
        )
    )
    app.materialize_workspace_item(
        MaterializeWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=file_view.item.id,
            actor="tester",
        )
    )

    tree = app.get_workspace_tree(
        GetWorkspaceTreeRequest(
            project_id=project.project_id, database_path=project.database_path
        )
    )
    quote = next(view for view in tree.items if view.item.id == file_view.item.id)
    details = app.get_workspace_item(
        GetWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=file_view.item.id,
        )
    )

    assert tree.workspace_revision == 3
    assert quote.workspace_path == "最终资料/报价.txt"
    assert quote.source_node is not None
    assert quote.source_node.format == NodeFormat.TXT
    assert quote.working_artifact is not None
    assert quote.working_artifact.content_status == WorkingContentStatus.CLEAN
    assert details.view == quote


def test_workspace_search_and_deleted_projection_use_workspace_semantics(
    tmp_path: Path,
) -> None:
    app, project, file_view = _project_with_file(tmp_path)
    result = app.search_workspace_items(
        SearchWorkspaceItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            query="报价",
            formats=(NodeFormat.TXT,),
        )
    )
    assert result.total == 1
    assert result.items[0].item.id == file_view.item.id

    app.soft_delete_workspace_item(
        SoftDeleteWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=file_view.item.id,
            actor="tester",
            expected_workspace_revision=1,
            confirmed=True,
        )
    )
    tree = app.get_workspace_tree(
        GetWorkspaceTreeRequest(
            project_id=project.project_id, database_path=project.database_path
        )
    )
    result = app.search_workspace_items(
        SearchWorkspaceItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            query="报价",
        )
    )
    assert tree.items == ()
    assert [view.item.id for view in tree.deleted_items] == [file_view.item.id]
    assert result.total == 0
