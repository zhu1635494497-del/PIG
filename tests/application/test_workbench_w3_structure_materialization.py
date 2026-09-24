from __future__ import annotations

import io
import zipfile
from pathlib import Path

from pig.application.contracts import (
    CreateProjectRequest,
    ImportProjectItemsRequest,
    InspectImportSessionRequest,
    MaterializeWorkspaceItemRequest,
)
from pig.bootstrap import create_local_application
from pig.domain.enums import (
    ImportSessionStatus,
    MaterializationLocatorKind,
    NodeFormat,
    NodeProcessingStatus,
    WorkspaceItemKind,
    WorkspaceMaterializationStatus,
)
from pig.domain.processing_policy import ProcessingPolicy
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase


def _project(tmp_path: Path):
    application = create_local_application(tmp_path / "projects")
    project = application.create_project(
        CreateProjectRequest(name="W3 Project", actor="tester")
    )
    return application, project


def _import_and_inspect(application, project, source: Path):
    imported = application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="tester",
            idempotency_key=f"import-{source.name}",
        )
    )
    inspected = application.inspect_import_session(
        InspectImportSessionRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            import_session_id=imported.import_session_id,
            actor="tester",
        )
    )
    return imported, inspected


def test_nested_zip_structure_is_eager_but_terminal_working_files_are_lazy(
    tmp_path: Path,
) -> None:
    inner_bytes = io.BytesIO()
    with zipfile.ZipFile(inner_bytes, "w") as inner:
        inner.writestr("报价/最终报价.txt", b"accepted quote")
    source = tmp_path / "采购资料.zip"
    with zipfile.ZipFile(source, "w") as outer:
        outer.writestr("邮件资料/readme.txt", b"read me")
        outer.writestr("邮件资料/报价附件.zip", inner_bytes.getvalue())
    application, project = _project(tmp_path)

    imported, inspected = _import_and_inspect(application, project, source)

    assert inspected.session_status == ImportSessionStatus.SUCCESS
    assert inspected.node_count == 6
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
        relationships = tuple(
            uow.catalog.relationships_for_project(project.project_id)
        )
        items = tuple(uow.workspace.items_for_project(project.project_id))
        working = tuple(
            artifact
            for item in items
            if (artifact := uow.workspace.working_artifact_for_item(item.id))
            is not None
        )
        session = uow.imports.get_session(imported.import_session_id)

    assert session.status == ImportSessionStatus.SUCCESS
    assert {node.display_name for node in nodes} == {
        "采购资料.zip",
        "邮件资料",
        "readme.txt",
        "报价附件.zip",
        "报价",
        "最终报价.txt",
    }
    # The ZIP contains six visible occurrences; the test also verifies the
    # declared result count against persisted facts rather than display-name
    # uniqueness.
    assert len(nodes) == 6
    assert len(relationships) == 5
    assert len(items) == 6
    assert not working
    assert not (project.workspace_path / "working").exists()
    by_origin = {item.origin_source_node_id: item for item in items}
    nested_zip = next(node for node in nodes if node.display_name == "报价附件.zip")
    terminal = next(node for node in nodes if node.display_name == "最终报价.txt")
    assert by_origin[nested_zip.id].item_kind == WorkspaceItemKind.CONTAINER_VIEW
    assert by_origin[terminal.id].materialization_status == WorkspaceMaterializationStatus.VIRTUAL


def test_materialize_one_nested_terminal_creates_one_stable_working_artifact(
    tmp_path: Path,
) -> None:
    inner_bytes = io.BytesIO()
    with zipfile.ZipFile(inner_bytes, "w") as inner:
        inner.writestr("final.txt", b"only this file")
        inner.writestr("other.txt", b"must remain virtual")
    source = tmp_path / "outer.zip"
    with zipfile.ZipFile(source, "w") as outer:
        outer.writestr("inner.zip", inner_bytes.getvalue())
    application, project = _project(tmp_path)
    _import_and_inspect(application, project, source)
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
        items = tuple(uow.workspace.items_for_project(project.project_id))
    final_node = next(node for node in nodes if node.display_name == "final.txt")
    final_item = next(item for item in items if item.origin_source_node_id == final_node.id)

    first = application.materialize_workspace_item(
        MaterializeWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=final_item.id,
            actor="tester",
        )
    )
    second = application.materialize_workspace_item(
        MaterializeWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=final_item.id,
            actor="tester",
        )
    )

    assert first.reused is False
    assert second.reused is True
    assert first.path == second.path
    assert first.path.read_bytes() == b"only this file"
    assert first.path.name == "final.txt"
    with database.unit_of_work(project.database_path) as uow:
        all_items = tuple(uow.workspace.items_for_project(project.project_id))
        artifacts = [
            artifact
            for item in all_items
            if (artifact := uow.workspace.working_artifact_for_item(item.id))
            is not None
        ]
    assert len(artifacts) == 1
    assert not (project.workspace_path / ".inspection").exists()


def test_folder_snapshot_nodes_use_explicit_snapshot_entry_locators(
    tmp_path: Path,
) -> None:
    source = tmp_path / "folder"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "evidence.pdf").write_bytes(b"%PDF evidence")
    application, project = _project(tmp_path)
    _, inspected = _import_and_inspect(application, project, source)

    assert inspected.session_status == ImportSessionStatus.SUCCESS
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
        terminal = next(node for node in nodes if node.format == NodeFormat.PDF)
        relationship = uow.catalog.relationship_for_child(terminal.id)
        locator = uow.catalog.entry_locator_for_child(terminal.id)
    assert relationship is not None
    assert locator is not None
    assert locator.kind == MaterializationLocatorKind.SNAPSHOT_ENTRY
    assert locator.snapshot_entry_id is not None


def test_unsafe_zip_member_is_visible_as_blocked_and_session_is_partial(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../outside.txt", b"blocked")
        archive.writestr("safe.txt", b"safe")
    application, project = _project(tmp_path)
    _, inspected = _import_and_inspect(application, project, source)

    assert inspected.session_status == ImportSessionStatus.PARTIAL_SUCCESS
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
    blocked = next(node for node in nodes if node.original_name == "../outside.txt")
    assert blocked.status == NodeProcessingStatus.SECURITY_BLOCKED
    assert next(node for node in nodes if node.display_name == "safe.txt").status == NodeProcessingStatus.SUCCESS


def test_corrupt_root_zip_finishes_as_failed_without_working_bytes(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.zip"
    source.write_bytes(b"PK\x03\x04not-a-zip")
    application, project = _project(tmp_path)
    _, inspected = _import_and_inspect(application, project, source)

    assert inspected.session_status == ImportSessionStatus.FAILED
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        root = uow.catalog.nodes_for_project(project.project_id)[0]
    assert root.status == NodeProcessingStatus.CORRUPTED
    assert not (project.workspace_path / "working").exists()


def test_duplicate_zip_names_remain_distinct_source_occurrences(tmp_path: Path) -> None:
    source = tmp_path / "duplicates.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("quote.txt", b"first")
        archive.writestr("quote.txt", b"second")
    application, project = _project(tmp_path)
    _, inspected = _import_and_inspect(application, project, source)

    assert inspected.session_status == ImportSessionStatus.SUCCESS
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        duplicates = [
            node
            for node in uow.catalog.nodes_for_project(project.project_id)
            if node.display_name == "quote.txt"
        ]
        ordinals = {
            uow.catalog.entry_locator_for_child(node.id).zip_member_ordinal
            for node in duplicates
        }
    assert len(duplicates) == 2
    assert ordinals == {0, 1}


def test_password_and_compression_ratio_are_structured_blocked_results(
    tmp_path: Path,
) -> None:
    encrypted = tmp_path / "encrypted.zip"
    with zipfile.ZipFile(encrypted, "w") as archive:
        archive.writestr("secret.txt", b"secret")
    payload = bytearray(encrypted.read_bytes())
    local = payload.index(b"PK\x03\x04")
    central = payload.index(b"PK\x01\x02")
    payload[local + 6 : local + 8] = (
        int.from_bytes(payload[local + 6 : local + 8], "little") | 1
    ).to_bytes(2, "little")
    payload[central + 8 : central + 10] = (
        int.from_bytes(payload[central + 8 : central + 10], "little") | 1
    ).to_bytes(2, "little")
    encrypted.write_bytes(payload)
    application, project = _project(tmp_path)
    _, encrypted_result = _import_and_inspect(application, project, encrypted)
    assert encrypted_result.session_status == ImportSessionStatus.PARTIAL_SUCCESS

    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        secret = next(
            node
            for node in uow.catalog.nodes_for_project(project.project_id)
            if node.display_name == "secret.txt"
        )
    assert secret.status == NodeProcessingStatus.PASSWORD_REQUIRED

    bomb = tmp_path / "ratio.zip"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("repeated.txt", b"0" * 10_000)
    second = application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(bomb,),
            actor="tester",
            idempotency_key="ratio",
        )
    )
    ratio_result = application.inspect_import_session(
        InspectImportSessionRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            import_session_id=second.import_session_id,
            actor="tester",
            policy=ProcessingPolicy(max_compression_ratio=2.0),
        )
    )
    assert ratio_result.session_status == ImportSessionStatus.PARTIAL_SUCCESS
    with database.unit_of_work(project.database_path) as uow:
        repeated = next(
            node
            for node in uow.catalog.nodes_for_project(project.project_id)
            if node.display_name == "repeated.txt"
        )
    assert repeated.status == NodeProcessingStatus.LIMIT_EXCEEDED


def test_completed_inspection_is_idempotent_after_application_restart(
    tmp_path: Path,
) -> None:
    source = tmp_path / "restart.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("one.txt", b"one")
    application, project = _project(tmp_path)
    imported, first = _import_and_inspect(application, project, source)
    restarted = create_local_application(tmp_path / "unused-default-root")

    second = restarted.inspect_import_session(
        InspectImportSessionRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            import_session_id=imported.import_session_id,
            actor="tester",
        )
    )

    assert second == first


def test_folder_depth_limit_stops_discovery_below_the_blocked_node(
    tmp_path: Path,
) -> None:
    source = tmp_path / "deep"
    (source / "one" / "two").mkdir(parents=True)
    (source / "one" / "two" / "file.txt").write_text("deep", encoding="utf-8")
    application, project = _project(tmp_path)
    imported = application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="tester",
            idempotency_key="depth",
        )
    )

    result = application.inspect_import_session(
        InspectImportSessionRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            import_session_id=imported.import_session_id,
            actor="tester",
            policy=ProcessingPolicy(max_depth=1),
        )
    )

    assert result.session_status == ImportSessionStatus.PARTIAL_SUCCESS
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
    assert next(node for node in nodes if node.display_name == "two").status == NodeProcessingStatus.LIMIT_EXCEEDED
    assert all(node.display_name != "file.txt" for node in nodes)
