from __future__ import annotations

import stat
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from pig.application.contracts import (
    CreateProjectRequest,
    ImportProjectItemsRequest,
    VerifyOriginalSnapshotRequest,
)
from pig.application.errors import ApplicationError
from pig.bootstrap import create_local_application
from pig.domain.enums import (
    ImportItemStatus,
    ImportSessionStatus,
    OriginalSnapshotEntryKind,
    OriginalSnapshotStatus,
)
from pig.domain.snapshot_policy import SnapshotImportPolicy
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase
from pig.infrastructure.database.engine import create_project_engine
from pig.infrastructure.filesystem.original_snapshot_store import (
    LocalOriginalSnapshotStore,
)


def _project(tmp_path: Path):
    application = create_local_application(tmp_path / "projects")
    created = application.create_project(
        CreateProjectRequest(name="W2 Project", actor="tester")
    )
    return application, created


def test_folder_snapshot_preserves_tree_and_registers_only_root_node(tmp_path) -> None:
    input_folder = tmp_path / "incoming" / "资料包"
    nested = input_folder / "报价" / "最终"
    nested.mkdir(parents=True)
    (input_folder / "readme.txt").write_text("root", encoding="utf-8")
    (nested / "报价.xlsx").write_bytes(b"xlsx-placeholder")
    application, project = _project(tmp_path)

    result = application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(input_folder,),
            actor="tester",
            idempotency_key="folder-import",
        )
    )

    assert result.session_status == ImportSessionStatus.INSPECTING
    assert result.accepted_item_count == 1
    assert result.failed_item_count == 0
    assert result.items[0].captured is True
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        snapshot = uow.imports.get_snapshot(result.items[0].snapshot_id)
        entries = uow.imports.entries_for_snapshot(snapshot.id)
        artifacts = uow.imports.original_artifacts_for_snapshot(snapshot.id)
        source = uow.catalog.source_for_snapshot(snapshot.id)
        nodes = uow.catalog.nodes_for_project(project.project_id)
        session_items = uow.imports.items_for_session(result.import_session_id)

    assert snapshot.status == OriginalSnapshotStatus.READY
    assert {(entry.original_name, entry.kind) for entry in entries} == {
        ("资料包", OriginalSnapshotEntryKind.FOLDER),
        ("readme.txt", OriginalSnapshotEntryKind.FILE),
        ("报价", OriginalSnapshotEntryKind.FOLDER),
        ("最终", OriginalSnapshotEntryKind.FOLDER),
        ("报价.xlsx", OriginalSnapshotEntryKind.FILE),
    }
    by_name = {entry.original_name: entry for entry in entries}
    assert by_name["最终"].parent_entry_id == by_name["报价"].id
    assert by_name["报价.xlsx"].parent_entry_id == by_name["最终"].id
    assert len(artifacts) == 2
    assert len(nodes) == 1
    assert source.root_node_id == nodes[0].id
    assert by_name["资料包"].source_node_id == nodes[0].id
    assert session_items[0].status == ImportItemStatus.CAPTURED


def test_failed_top_level_snapshot_rolls_back_but_other_input_continues(tmp_path) -> None:
    good = tmp_path / "good.txt"
    good.write_text("accepted", encoding="utf-8")
    missing = tmp_path / "missing.txt"
    application, project = _project(tmp_path)

    result = application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(missing, good),
            actor="tester",
            idempotency_key="partial-import",
        )
    )

    assert result.session_status == ImportSessionStatus.INSPECTING
    assert result.accepted_item_count == 1
    assert result.failed_item_count == 1
    assert result.items[0].error_code == "INPUT_NOT_FOUND"
    assert result.items[1].captured is True
    assert len(list((project.workspace_path / "originals").glob("*"))) == 1


def test_import_idempotency_returns_the_persisted_result(tmp_path) -> None:
    source = tmp_path / "one.txt"
    source.write_text("one", encoding="utf-8")
    application, project = _project(tmp_path)
    request = ImportProjectItemsRequest(
        project_id=project.project_id,
        database_path=project.database_path,
        input_paths=(source,),
        actor="tester",
        idempotency_key="same-request",
    )

    first = application.import_project_items(request)
    second = application.import_project_items(request)

    assert second == first
    assert len(list((project.workspace_path / "originals").glob("*"))) == 1


def test_idempotency_key_cannot_be_reused_for_different_inputs(tmp_path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    application, project = _project(tmp_path)
    application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(first,),
            actor="tester",
            idempotency_key="one-key",
        )
    )

    with pytest.raises(ApplicationError) as error:
        application.import_project_items(
            ImportProjectItemsRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                input_paths=(second,),
                actor="tester",
                idempotency_key="one-key",
            )
        )

    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_duplicate_top_level_input_is_rejected_before_session_creation(tmp_path) -> None:
    source = tmp_path / "duplicate.txt"
    source.write_text("same", encoding="utf-8")
    application, project = _project(tmp_path)

    with pytest.raises(ApplicationError) as error:
        application.import_project_items(
            ImportProjectItemsRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                input_paths=(source, source),
                actor="tester",
            )
        )

    assert error.value.code == "DUPLICATE_INPUT"


def test_resource_limit_failure_leaves_no_published_snapshot(tmp_path) -> None:
    source = tmp_path / "large.bin"
    source.write_bytes(b"too large")
    application, project = _project(tmp_path)

    result = application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="tester",
            idempotency_key="limited",
            policy=SnapshotImportPolicy(max_single_file_size=1),
        )
    )

    assert result.session_status == ImportSessionStatus.FAILED
    assert result.items[0].error_code == "MAX_SINGLE_FILE_SIZE_EXCEEDED"
    originals = project.workspace_path / "originals"
    assert not originals.exists() or not any(originals.iterdir())


def test_snapshot_verification_uses_project_copy_after_external_input_removed(
    tmp_path,
) -> None:
    source = tmp_path / "evidence.txt"
    source.write_text("immutable", encoding="utf-8")
    application, project = _project(tmp_path)
    imported = application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="tester",
            idempotency_key="verify-copy",
        )
    )
    snapshot_id = imported.items[0].snapshot_id
    source.unlink()

    verified = application.verify_original_snapshot(
        VerifyOriginalSnapshotRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            snapshot_id=snapshot_id,
            actor="tester",
        )
    )
    assert verified.status == OriginalSnapshotStatus.READY

    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        artifact = uow.imports.original_artifacts_for_snapshot(snapshot_id)[0]
    stored = project.workspace_path.joinpath(*artifact.storage_key.split("/"))
    stored.chmod(stat.S_IWRITE)
    stored.unlink()
    missing = application.verify_original_snapshot(
        VerifyOriginalSnapshotRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            snapshot_id=snapshot_id,
            actor="tester",
        )
    )
    assert missing.status == OriginalSnapshotStatus.MISSING
    with database.unit_of_work(project.database_path) as uow:
        assert uow.catalog.source_for_snapshot(snapshot_id).status.value == "MISSING"
        assert (
            uow.imports.original_artifacts_for_snapshot(snapshot_id)[0]
            .integrity_status.value
            == "MISSING"
        )


class _InterruptingWrite:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def capture(self, source, *, policy, prior_session_size):
        raise KeyboardInterrupt()

    def publish(self):
        raise AssertionError("publish must not be reached")

    def complete(self):
        raise AssertionError("complete must not be reached")


class _InterruptingStore(LocalOriginalSnapshotStore):
    def begin(self, project_path, import_session_id, snapshot_id):
        return _InterruptingWrite()


class _FailingWrite(_InterruptingWrite):
    def __init__(self, code: str) -> None:
        self._code = code

    def capture(self, source, *, policy, prior_session_size):
        raise ApplicationError(self._code, "injected snapshot failure")


class _FailingStore(LocalOriginalSnapshotStore):
    def __init__(self, code: str) -> None:
        super().__init__()
        self._code = code

    def begin(self, project_path, import_session_id, snapshot_id):
        return _FailingWrite(self._code)


def test_interrupted_capture_persists_interrupted_item_snapshot_and_session(
    tmp_path,
) -> None:
    source = tmp_path / "interrupt.txt"
    source.write_text("interrupt", encoding="utf-8")
    application, project = _project(tmp_path)
    application._snapshot_import_service._store = _InterruptingStore()

    with pytest.raises(KeyboardInterrupt):
        application.import_project_items(
            ImportProjectItemsRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                input_paths=(source,),
                actor="tester",
                idempotency_key="interrupted",
            )
        )

    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        session = uow.imports.get_session_by_correlation(
            project.project_id, "interrupted"
        )
        item = uow.imports.items_for_session(session.id)[0]
        snapshot = uow.imports.get_snapshot(item.snapshot_id)
    assert session.status == ImportSessionStatus.INTERRUPTED
    assert item.status == ImportItemStatus.INTERRUPTED
    assert snapshot.status == OriginalSnapshotStatus.INTERRUPTED


@pytest.mark.parametrize(
    "code", ["INPUT_CHANGED_DURING_COPY", "INPUT_UNREADABLE"]
)
def test_capture_fault_is_persisted_and_does_not_publish_originals(
    tmp_path, code
) -> None:
    source = tmp_path / f"{code}.txt"
    source.write_text("fault", encoding="utf-8")
    application, project = _project(tmp_path)
    application._snapshot_import_service._store = _FailingStore(code)

    result = application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="tester",
            idempotency_key=code.lower(),
        )
    )

    assert result.session_status == ImportSessionStatus.FAILED
    assert result.items[0].error_code == code
    assert not (project.workspace_path / "originals").exists()


def test_snapshot_entry_identity_is_database_immutable(tmp_path) -> None:
    source = tmp_path / "immutable.txt"
    source.write_text("immutable", encoding="utf-8")
    application, project = _project(tmp_path)
    imported = application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="tester",
            idempotency_key="immutable-entry",
        )
    )
    snapshot_id = imported.items[0].snapshot_id
    engine = create_project_engine(project.database_path)
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE original_snapshot_entries "
                        "SET original_name = 'rewritten.txt' "
                        "WHERE snapshot_id = :snapshot_id"
                    ),
                    {"snapshot_id": snapshot_id},
                )
    finally:
        engine.dispose()


def test_symlink_inside_folder_rejects_the_whole_snapshot(tmp_path) -> None:
    source = tmp_path / "linked-folder"
    source.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    try:
        (source / "link.txt").symlink_to(target)
    except OSError:
        pytest.skip("host does not permit creating a test symlink")
    application, project = _project(tmp_path)

    result = application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="tester",
            idempotency_key="link-blocked",
        )
    )

    assert result.session_status == ImportSessionStatus.FAILED
    assert result.items[0].error_code == "SYMLINK_BLOCKED"
    assert not (project.workspace_path / "originals").exists()
