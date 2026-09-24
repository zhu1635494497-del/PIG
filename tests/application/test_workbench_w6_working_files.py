from __future__ import annotations

from pathlib import Path

import pytest

from pig.application.contracts import (
    CreateProjectRequest,
    ImportProjectItemsRequest,
    InspectImportSessionRequest,
    OpenWorkspaceItemRequest,
    RefreshWorkingArtifactRequest,
    RestoreWorkingArtifactRequest,
)
from pig.application.errors import ApplicationError
from pig.bootstrap import create_local_application
from pig.domain.enums import EventType, WorkingContentStatus, WorkingRefreshReason
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase


class RecordingOpener:
    def __init__(self, *, fail: bool = False) -> None:
        self.paths: list[Path] = []
        self.fail = fail

    def open(self, path: Path) -> None:
        self.paths.append(path)
        if self.fail:
            raise OSError("host association failed")


def _ready_file(tmp_path: Path, content: bytes = b"original"):
    source = tmp_path / "evidence.txt"
    source.write_bytes(content)
    opener = RecordingOpener()
    app = create_local_application(tmp_path / "projects", file_opener=opener)
    project = app.create_project(CreateProjectRequest(name="W6", actor="tester"))
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
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        item = uow.workspace.items_for_project(project.project_id)[0]
    return app, project, item, opener


def _open(app, project, item):
    return app.open_workspace_item(
        OpenWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
        )
    )


def test_open_materializes_once_then_refreshes_and_opens_same_modified_path(
    tmp_path: Path,
) -> None:
    app, project, item, opener = _ready_file(tmp_path)

    first = _open(app, project, item)
    materialized_at = first.working_artifact.materialized_at
    first.path.write_bytes(b"user edit")
    second = _open(app, project, item)

    assert first.materialized is True
    assert second.materialized is False
    assert first.path == second.path == opener.paths[0] == opener.paths[1]
    assert second.path.read_bytes() == b"user edit"
    assert second.working_artifact.content_status == WorkingContentStatus.MODIFIED
    assert second.working_artifact.materialized_at == materialized_at


def test_materialized_working_file_reopens_after_application_restart(
    tmp_path: Path,
) -> None:
    app, project, item, _opener = _ready_file(tmp_path)
    first = _open(app, project, item)
    first.path.write_bytes(b"persisted edit")
    restarted_opener = RecordingOpener()
    restarted = create_local_application(
        tmp_path / "unused-root", file_opener=restarted_opener
    )

    reopened = _open(restarted, project, item)

    assert reopened.materialized is False
    assert reopened.path == first.path == restarted_opener.paths[0]
    assert reopened.path.read_bytes() == b"persisted edit"
    assert reopened.working_artifact.content_status == WorkingContentStatus.MODIFIED


def test_refresh_is_deduplicated_and_save_as_elsewhere_is_not_tracked(
    tmp_path: Path,
) -> None:
    app, project, item, _opener = _ready_file(tmp_path)
    opened = _open(app, project, item)
    (tmp_path / "save-as.txt").write_bytes(b"untracked")
    first = app.refresh_working_artifact(
        RefreshWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
            reason=WorkingRefreshReason.FOCUS_GAINED,
        )
    )
    second = app.refresh_working_artifact(
        RefreshWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
        )
    )
    assert opened.path.read_bytes() == b"original"
    assert first.working_artifact.content_status == WorkingContentStatus.CLEAN
    assert first.changed is False and second.changed is False
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        content_events = [
            event
            for event in uow.processing.events_for_project(project.project_id)
            if event.event_type
            in {
                EventType.WORKING_FILE_MODIFIED,
                EventType.WORKING_FILE_MISSING,
                EventType.WORKING_FILE_UNREADABLE,
                EventType.WORKING_FILE_RESTORED_CLEAN,
            }
        ]
    assert content_events == []


def test_refresh_detects_return_to_baseline_and_records_trigger_reason(
    tmp_path: Path,
) -> None:
    app, project, item, _opener = _ready_file(tmp_path)
    opened = _open(app, project, item)
    opened.path.write_bytes(b"edited")
    modified = app.refresh_working_artifact(
        RefreshWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
            reason=WorkingRefreshReason.FOCUS_GAINED,
        )
    )
    opened.path.write_bytes(b"original")
    clean = app.refresh_working_artifact(
        RefreshWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
        )
    )
    assert modified.working_artifact.content_status == WorkingContentStatus.MODIFIED
    assert clean.working_artifact.content_status == WorkingContentStatus.CLEAN
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        events = uow.processing.events_for_project(project.project_id)
    changed = next(
        event for event in events if event.event_type == EventType.WORKING_FILE_MODIFIED
    )
    assert changed.details["reason"] == WorkingRefreshReason.FOCUS_GAINED.value
    assert EventType.WORKING_FILE_RESTORED_CLEAN in {
        event.event_type for event in events
    }


def test_missing_is_denied_on_open_and_restore_recreates_without_confirmation(
    tmp_path: Path,
) -> None:
    app, project, item, opener = _ready_file(tmp_path)
    opened = _open(app, project, item)
    baseline_key = opened.working_artifact.storage_key
    opened.path.unlink()

    refreshed = app.refresh_working_artifact(
        RefreshWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
        )
    )
    assert refreshed.working_artifact.content_status == WorkingContentStatus.MISSING
    assert refreshed.working_artifact.current_sha256 == opened.working_artifact.current_sha256
    with pytest.raises(ApplicationError) as denied:
        _open(app, project, item)
    assert denied.value.code == "ARTIFACT_MISSING"
    assert len(opener.paths) == 1
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        missing_events = [
            event
            for event in uow.processing.events_for_project(project.project_id)
            if event.event_type == EventType.WORKING_FILE_MISSING
        ]
    assert len(missing_events) == 1

    restored = app.restore_working_artifact(
        RestoreWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
        )
    )
    assert restored.path.read_bytes() == b"original"
    assert restored.working_artifact.content_status == WorkingContentStatus.CLEAN
    assert restored.working_artifact.storage_key == baseline_key
    assert restored.replaced is False


def test_modified_restore_requires_confirmation_and_preserves_baseline_identity(
    tmp_path: Path,
) -> None:
    app, project, item, _opener = _ready_file(tmp_path)
    opened = _open(app, project, item)
    opened.path.write_bytes(b"edited")
    before = app.refresh_working_artifact(
        RefreshWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
        )
    ).working_artifact

    with pytest.raises(ApplicationError) as confirmation:
        app.restore_working_artifact(
            RestoreWorkingArtifactRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                workspace_item_id=item.id,
                actor="tester",
            )
        )
    assert confirmation.value.code == "RESTORE_CONFIRMATION_REQUIRED"

    restored = app.restore_working_artifact(
        RestoreWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
            confirmed_replace=True,
        )
    )
    assert restored.replaced is True
    assert restored.path.read_bytes() == b"original"
    assert restored.working_artifact.baseline_sha256 == before.baseline_sha256
    assert restored.working_artifact.materialized_at == before.materialized_at


def test_non_regular_working_destination_is_unreadable_and_never_replaced(
    tmp_path: Path,
) -> None:
    app, project, item, _opener = _ready_file(tmp_path)
    opened = _open(app, project, item)
    opened.path.unlink()
    opened.path.mkdir()
    refreshed = app.refresh_working_artifact(
        RefreshWorkingArtifactRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
        )
    )
    assert refreshed.working_artifact.content_status == WorkingContentStatus.UNREADABLE
    with pytest.raises(ApplicationError) as unsafe:
        app.restore_working_artifact(
            RestoreWorkingArtifactRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                workspace_item_id=item.id,
                actor="tester",
                confirmed_replace=True,
            )
        )
    assert unsafe.value.code == "WORKSPACE_INTEGRITY_FAILED"
    assert opened.path.is_dir()


def test_host_open_failure_is_recorded_without_changing_clean_state(tmp_path: Path) -> None:
    source = tmp_path / "evidence.txt"
    source.write_bytes(b"original")
    opener = RecordingOpener(fail=True)
    app = create_local_application(tmp_path / "projects", file_opener=opener)
    project = app.create_project(CreateProjectRequest(name="W6", actor="tester"))
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
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        item = uow.workspace.items_for_project(project.project_id)[0]
    with pytest.raises(ApplicationError) as failed:
        _open(app, project, item)
    assert failed.value.code == "OPEN_HANDOFF_FAILED"
    with database.unit_of_work(project.database_path) as uow:
        artifact = uow.workspace.working_artifact_for_item(item.id)
        events = uow.processing.events_for_project(project.project_id)
    assert artifact.content_status == WorkingContentStatus.CLEAN
    assert EventType.FILE_OPEN_FAILED in {event.event_type for event in events}


def test_unknown_format_is_denied_before_materialization(tmp_path: Path) -> None:
    source = tmp_path / "payload.unknown"
    source.write_bytes(b"opaque")
    opener = RecordingOpener()
    app = create_local_application(tmp_path / "projects", file_opener=opener)
    project = app.create_project(CreateProjectRequest(name="W6", actor="tester"))
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
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        item = uow.workspace.items_for_project(project.project_id)[0]
    with pytest.raises(ApplicationError) as denied:
        _open(app, project, item)
    assert denied.value.code == "OPEN_FORMAT_DENIED"
    assert opener.paths == []
    assert not (project.workspace_path / "working").exists()
