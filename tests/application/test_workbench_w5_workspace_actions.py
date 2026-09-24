from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from pig.application.contracts import (
    AddWorkspaceInputsRequest,
    CreateProjectRequest,
    CreateWorkspaceFolderRequest,
    ImportProjectItemsRequest,
    InspectImportSessionRequest,
    MoveWorkspaceItemRequest,
    RestoreWorkspaceItemRequest,
    SoftDeleteWorkspaceItemRequest,
)
from pig.application.errors import ApplicationError
from pig.bootstrap import create_local_application
from pig.domain.enums import (
    EventType,
    WorkspaceItemKind,
    WorkspaceItemLifecycleStatus,
    ImportSessionStatus,
    ProjectStatus,
)
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase


def _project(tmp_path: Path):
    application = create_local_application(tmp_path / "projects")
    project = application.create_project(
        CreateProjectRequest(name="W5 Project", actor="tester")
    )
    return application, project


def _folder(application, project, name, revision, *, parent=None, ordinal=None):
    return application.create_workspace_folder(
        CreateWorkspaceFolderRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            display_name=name,
            parent_workspace_item_id=parent,
            ordinal=ordinal,
            actor="tester",
            expected_workspace_revision=revision,
        )
    )


def test_create_move_delete_restore_is_revisioned_and_survives_restart(
    tmp_path: Path,
) -> None:
    application, project = _project(tmp_path)
    first = _folder(application, project, "资料", 0)
    second = _folder(application, project, "资料", 1, ordinal=0)
    child = _folder(
        application,
        project,
        "分析",
        2,
        parent=first.item.id,
    )

    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        roots = uow.workspace.children_for_parent(project.project_id, None)
    assert [item.id for item, _ in roots] == [second.item.id, first.item.id]
    assert [placement.ordinal for _, placement in roots] == [0, 1]
    assert first.item.display_name == second.item.display_name

    with pytest.raises(ApplicationError, match="cycle"):
        application.move_workspace_item(
            MoveWorkspaceItemRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                workspace_item_id=first.item.id,
                new_parent_workspace_item_id=child.item.id,
                new_ordinal=0,
                actor="tester",
                expected_workspace_revision=3,
            )
        )

    moved = application.move_workspace_item(
        MoveWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=child.item.id,
            new_parent_workspace_item_id=second.item.id,
            new_ordinal=0,
            actor="tester",
            expected_workspace_revision=3,
        )
    )
    assert moved.workspace_revision == 4

    with pytest.raises(ApplicationError) as confirmation:
        application.soft_delete_workspace_item(
            SoftDeleteWorkspaceItemRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                workspace_item_id=second.item.id,
                actor="tester",
                expected_workspace_revision=4,
            )
        )
    assert confirmation.value.code == "DELETE_CONFIRMATION_REQUIRED"

    deleted = application.soft_delete_workspace_item(
        SoftDeleteWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=second.item.id,
            actor="tester",
            expected_workspace_revision=4,
            confirmed=True,
        )
    )
    assert deleted.item.lifecycle_status == WorkspaceItemLifecycleStatus.DELETED
    assert deleted.workspace_revision == 5
    with database.unit_of_work(project.database_path) as uow:
        assert uow.workspace.get_item(child.item.id).lifecycle_status == (
            WorkspaceItemLifecycleStatus.ACTIVE
        )
        assert uow.workspace.is_effectively_active(child.item.id) is False

    restored = application.restore_workspace_item(
        RestoreWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=second.item.id,
            actor="tester",
            expected_workspace_revision=5,
        )
    )
    assert restored.workspace_revision == 6
    assert restored.restore_fallback is False

    restarted = create_local_application(tmp_path / "unused")
    # A restarted composition root reads the same durable tree and revision.
    del restarted
    with database.unit_of_work(project.database_path) as uow:
        persisted = uow.projects.get(project.project_id)
        placement = uow.workspace.get_placement(child.item.id)
        events = uow.processing.events_for_project(project.project_id)
    assert persisted.workspace_revision == 6
    assert placement.parent_workspace_item_id == second.item.id
    assert {
        EventType.WORKSPACE_ITEM_MOVED,
        EventType.WORKSPACE_ITEM_DELETED,
        EventType.WORKSPACE_ITEM_RESTORED,
    } <= {event.event_type for event in events}


def test_restore_falls_back_to_root_when_prior_parent_is_deleted(tmp_path: Path) -> None:
    application, project = _project(tmp_path)
    parent = _folder(application, project, "Parent", 0)
    child = _folder(
        application, project, "Child", 1, parent=parent.item.id
    )
    application.soft_delete_workspace_item(
        SoftDeleteWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=child.item.id,
            actor="tester",
            expected_workspace_revision=2,
            confirmed=True,
        )
    )
    application.soft_delete_workspace_item(
        SoftDeleteWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=parent.item.id,
            actor="tester",
            expected_workspace_revision=3,
            confirmed=True,
        )
    )

    restored = application.restore_workspace_item(
        RestoreWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=child.item.id,
            actor="tester",
            expected_workspace_revision=4,
        )
    )

    assert restored.restore_fallback is True
    assert restored.placement.parent_workspace_item_id is None
    assert restored.workspace_revision == 5


def test_revision_conflict_and_invalid_logical_names_do_not_mutate_tree(
    tmp_path: Path,
) -> None:
    application, project = _project(tmp_path)
    _folder(application, project, "Valid", 0)

    with pytest.raises(ApplicationError) as stale:
        _folder(application, project, "Stale", 0)
    assert stale.value.code == "WORKSPACE_REVISION_CONFLICT"

    for invalid in ("", ".", "..", "a/b", "a\\b", "bad\x00name"):
        with pytest.raises(ApplicationError) as bad_name:
            _folder(application, project, invalid, 1)
        assert bad_name.value.code == "INVALID_WORKSPACE_NAME"

    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        assert uow.projects.get(project.project_id).workspace_revision == 1
        assert len(uow.workspace.items_for_project(project.project_id)) == 1


def test_move_cannot_resolve_a_target_from_another_project_database(
    tmp_path: Path,
) -> None:
    first_app, first_project = _project(tmp_path / "first")
    second_app, second_project = _project(tmp_path / "second")
    first_folder = _folder(first_app, first_project, "First", 0)
    second_folder = _folder(second_app, second_project, "Second", 0)

    with pytest.raises(ApplicationError) as rejected:
        first_app.move_workspace_item(
            MoveWorkspaceItemRequest(
                project_id=first_project.project_id,
                database_path=first_project.database_path,
                workspace_item_id=first_folder.item.id,
                new_parent_workspace_item_id=second_folder.item.id,
                new_ordinal=0,
                actor="tester",
                expected_workspace_revision=1,
            )
        )
    assert rejected.value.code == "INVALID_WORKSPACE_ACTION"

    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(first_project.database_path) as uow:
        assert uow.projects.get(first_project.project_id).workspace_revision == 1
        assert uow.workspace.get_placement(
            first_folder.item.id
        ).parent_workspace_item_id is None


def test_add_snapshotted_input_projects_directly_under_target_and_preserves_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "incoming.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("nested/report.txt", b"original report")
    application, project = _project(tmp_path)
    target = _folder(application, project, "Target", 0)

    add_request = AddWorkspaceInputsRequest(
        project_id=project.project_id,
        database_path=project.database_path,
        input_paths=(source,),
        target_workspace_parent_id=target.item.id,
        actor="tester",
        expected_workspace_revision=1,
        idempotency_key="targeted-add",
    )
    added = application.add_workspace_inputs(add_request)

    assert added.inspection_result is not None
    assert added.workspace_revision == 2
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        target_children = uow.workspace.children_for_parent(
            project.project_id, target.item.id
        )
        sources = tuple(uow.catalog.sources_for_project(project.project_id))
        relationships = tuple(
            uow.catalog.relationships_for_project(project.project_id)
        )
        originals = tuple(
            artifact
            for snapshot in uow.imports.snapshots_for_project(project.project_id)
            for artifact in uow.imports.original_artifacts_for_snapshot(snapshot.id)
        )
    assert len(target_children) == 1
    archive_item, archive_placement = target_children[0]
    assert archive_item.item_kind == WorkspaceItemKind.CONTAINER_VIEW
    assert archive_placement.ordinal == 0
    assert len(sources) == 1
    assert relationships
    assert originals[0].sha256
    assert source.read_bytes() != b"original report"

    other = _folder(application, project, "Other", 2)
    moved = application.move_workspace_item(
        MoveWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=archive_item.id,
            new_parent_workspace_item_id=other.item.id,
            new_ordinal=0,
            actor="tester",
            expected_workspace_revision=3,
        )
    )
    assert moved.workspace_revision == 4
    with database.unit_of_work(project.database_path) as uow:
        after_relationships = tuple(
            uow.catalog.relationships_for_project(project.project_id)
        )
        after_originals = tuple(
            artifact
            for snapshot in uow.imports.snapshots_for_project(project.project_id)
            for artifact in uow.imports.original_artifacts_for_snapshot(snapshot.id)
        )
    assert after_relationships == relationships
    assert after_originals == originals

    with pytest.raises(ApplicationError) as invalid_target:
        application.move_workspace_item(
            MoveWorkspaceItemRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                workspace_item_id=target.item.id,
                new_parent_workspace_item_id=archive_item.id,
                new_ordinal=0,
                actor="tester",
                expected_workspace_revision=4,
            )
        )
    assert invalid_target.value.code == "INVALID_WORKSPACE_ACTION"
    replayed = application.add_workspace_inputs(add_request)
    assert replayed.import_result.import_session_id == (
        added.import_result.import_session_id
    )
    assert replayed.workspace_revision == 4


def test_pending_add_rejects_concurrent_revision_and_records_interruption(
    tmp_path: Path,
) -> None:
    source = tmp_path / "late.txt"
    source.write_text("late", encoding="utf-8")
    application, project = _project(tmp_path)
    target = _folder(application, project, "Target", 0)
    imported = application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            target_workspace_parent_id=target.item.id,
            expected_workspace_revision=1,
            actor="tester",
            idempotency_key="concurrent-add",
        )
    )
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        uow.projects.advance_workspace_revision(
            project.project_id,
            1,
            updated_at=uow.projects.get(project.project_id).updated_at,
        )
        uow.commit()

    with pytest.raises(ApplicationError) as conflict:
        application.inspect_import_session(
            InspectImportSessionRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                import_session_id=imported.import_session_id,
                actor="tester",
            )
        )
    assert conflict.value.code == "WORKSPACE_REVISION_CONFLICT"
    with database.unit_of_work(project.database_path) as uow:
        session = uow.imports.get_session(imported.import_session_id)
        persisted_project = uow.projects.get(project.project_id)
        target_children = uow.workspace.children_for_parent(
            project.project_id, target.item.id
        )
    assert session.status == ImportSessionStatus.INTERRUPTED
    assert persisted_project.status == ProjectStatus.FAILED
    assert target_children == []
