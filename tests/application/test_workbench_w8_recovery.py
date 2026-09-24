from __future__ import annotations

import os
from pathlib import Path

import pytest

from pig.application import (
    AddWorkspaceInputsRequest,
    CreateProjectRequest,
    CreateWorkspaceFolderRequest,
    GetWorkspaceTreeRequest,
    InspectProjectRecoveryRequest,
    RecoverWorkbenchProjectRequest,
)
from pig.application.contracts import (
    ImportProjectItemsRequest,
    MaterializeWorkspaceItemRequest,
)
from pig.application.errors import ApplicationError
from pig.bootstrap import create_local_application
from pig.domain.enums import (
    EventType,
    RecoveryAction,
    RecoveryItemStatus,
    RecoveryRunStatus,
    WorkspaceMaterializationStatus,
)
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase
from pig.infrastructure.filesystem.staging_manifest import StagingOperationManifest


def _project(tmp_path: Path):
    application = create_local_application(tmp_path / "projects")
    project = application.create_project(
        CreateProjectRequest(name="W8 Recovery", actor="tester")
    )
    return application, project


def _inspect(application, project):
    return application.inspect_project_recovery(
        InspectProjectRecoveryRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )


def _recover(application, project, inspection):
    return application.recover_workbench_project(
        RecoverWorkbenchProjectRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            actor="tester",
            inspection_token=inspection.inspection_token,
            confirmed=True,
        )
    )


def test_healthy_project_scan_is_read_only_and_silent(tmp_path: Path) -> None:
    application, project = _project(tmp_path)
    before = project.database_path.stat().st_mtime_ns

    result = _inspect(application, project)

    assert not result.recovery_required
    assert result.candidates == ()
    assert project.database_path.stat().st_mtime_ns == before


def test_snapshot_inspecting_is_a_valid_resumable_state(tmp_path: Path) -> None:
    source = tmp_path / "pending-inspection.txt"
    source.write_text("captured", encoding="utf-8")
    application, project = _project(tmp_path)
    application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="tester",
            idempotency_key="pending-inspection",
        )
    )

    result = _inspect(application, project)

    assert not result.recovery_required
    assert result.candidates == ()


def test_reproducible_inspection_cache_blocks_writes_until_confirmed_recovery(
    tmp_path: Path,
) -> None:
    application, project = _project(tmp_path)
    cache = project.workspace_path / ".inspection" / "interrupted" / "objects"
    cache.mkdir(parents=True)
    (cache / "content").write_bytes(b"derived")

    inspection = _inspect(application, project)
    assert inspection.recovery_required
    assert inspection.candidates[0].action == RecoveryAction.REMOVE_REPRODUCIBLE

    with pytest.raises(ApplicationError) as blocked:
        application.create_workspace_folder(
            CreateWorkspaceFolderRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                display_name="blocked",
                actor="tester",
                expected_workspace_revision=0,
            )
        )
    assert blocked.value.code == "RECOVERY_REQUIRED"
    assert cache.exists()

    result = _recover(application, project, inspection)
    assert result.recovery_run.status == RecoveryRunStatus.SUCCESS
    assert result.remaining_candidate_count == 0
    assert not (project.workspace_path / ".inspection" / "interrupted").exists()
    assert {item.status for item in result.recovery_items} == {
        RecoveryItemStatus.REMOVED_REPRODUCIBLE
    }
    assert result.recovery_items[0].size == len(b"derived")
    assert result.recovery_items[0].sha256 is not None
    assert len(result.recovery_items[0].sha256) == 64

    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        runs = uow.recovery.runs_for_project(project.project_id)
        events = uow.processing.events_for_project(project.project_id)
    assert runs[-1].status == RecoveryRunStatus.SUCCESS
    assert EventType.RECOVERY_STARTED in {value.event_type for value in events}
    assert EventType.RECOVERY_FINISHED in {value.event_type for value in events}


def test_unregistered_working_root_is_quarantined_without_touching_known_working(
    tmp_path: Path,
) -> None:
    source = tmp_path / "known.txt"
    source.write_bytes(b"known")
    application, project = _project(tmp_path)
    added = application.add_workspace_inputs(
        AddWorkspaceInputsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="tester",
            expected_workspace_revision=0,
        )
    )
    tree = application.get_workspace_tree(
        GetWorkspaceTreeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )
    item_id = tree.items[0].item.id
    materialized = application.materialize_workspace_item(
        MaterializeWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item_id,
            actor="tester",
        )
    )
    known_path = materialized.path
    known_path.write_bytes(b"user-modified-working-copy")
    rogue = project.workspace_path / "working" / "not-registered" / "content.txt"
    rogue.parent.mkdir(parents=True)
    rogue.write_bytes(b"rogue")

    inspection = _inspect(application, project)
    candidate = next(
        value for value in inspection.candidates if "not-registered" in value.storage_key
    )
    assert candidate.action == RecoveryAction.QUARANTINE
    result = _recover(application, project, inspection)

    assert known_path.read_bytes() == b"user-modified-working-copy"
    assert not rogue.exists()
    quarantined = next(
        value.recovery_storage_key
        for value in result.recovery_items
        if value.status == RecoveryItemStatus.QUARANTINED
    )
    assert quarantined is not None
    assert (
        project.workspace_path.joinpath(*quarantined.split("/")) / "content.txt"
    ).read_bytes() == b"rogue"


def test_uncommitted_import_undo_is_restored_in_place(tmp_path: Path) -> None:
    source = tmp_path / "undo.txt"
    source.write_bytes(b"restore me")
    application, project = _project(tmp_path)
    added = application.add_workspace_inputs(
        AddWorkspaceInputsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="tester",
            expected_workspace_revision=0,
        )
    )
    snapshot_id = added.import_result.items[0].snapshot_id
    operation_id = "forced-import-undo"
    source_key = f"originals/{snapshot_id}"
    staging_key = f".staging/import-undo/{operation_id}/item-0"
    manifest = StagingOperationManifest(
        project.workspace_path,
        operation_id,
        "IMPORT_UNDO",
        project.project_id,
        source_keys=(source_key,),
        entries=({"source_key": source_key, "staging_key": staging_key},),
    )
    manifest.update("STAGED")
    original = project.workspace_path.joinpath(*source_key.split("/"))
    staged = project.workspace_path.joinpath(*staging_key.split("/"))
    staged.parent.mkdir(parents=True)
    os.replace(original, staged)

    inspection = _inspect(application, project)
    assert any(value.action == RecoveryAction.RESTORE for value in inspection.candidates)
    result = _recover(application, project, inspection)

    assert result.recovery_run.status == RecoveryRunStatus.SUCCESS
    assert original.exists()
    assert not staged.exists()
    assert not (
        project.workspace_path / ".staging" / "operations" / f"{operation_id}.json"
    ).exists()


def test_recovery_rejects_a_stale_inspection_token(tmp_path: Path) -> None:
    application, project = _project(tmp_path)
    first = project.workspace_path / ".inspection" / "first"
    first.mkdir(parents=True)
    inspection = _inspect(application, project)
    second = project.workspace_path / ".inspection" / "second"
    second.mkdir(parents=True)

    with pytest.raises(ApplicationError) as changed:
        _recover(application, project, inspection)
    assert changed.value.code == "RECOVERY_PLAN_CHANGED"
    assert first.exists()
    assert second.exists()


def test_recovery_marks_stranded_materialization_interrupted(tmp_path: Path) -> None:
    source = tmp_path / "stranded.txt"
    source.write_bytes(b"stranded")
    application, project = _project(tmp_path)
    application.add_workspace_inputs(
        AddWorkspaceInputsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="tester",
            expected_workspace_revision=0,
        )
    )
    tree = application.get_workspace_tree(
        GetWorkspaceTreeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )
    item_id = tree.items[0].item.id
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        uow.workspace.update_materialization_status(
            item_id,
            WorkspaceMaterializationStatus.VIRTUAL,
            WorkspaceMaterializationStatus.MATERIALIZING,
            updated_at=tree.project.updated_at,
        )
        uow.commit()

    inspection = _inspect(application, project)
    assert any("workspace-items" in value.storage_key for value in inspection.candidates)
    _recover(application, project, inspection)

    with database.unit_of_work(project.database_path) as uow:
        item = uow.workspace.get_item(item_id)
    assert item.materialization_status == WorkspaceMaterializationStatus.INTERRUPTED
