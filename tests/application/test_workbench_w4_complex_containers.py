from __future__ import annotations

import io
import zipfile
from email.message import EmailMessage
from pathlib import Path

import py7zr

import pig.bootstrap as bootstrap_module
from pig.application.contracts import (
    CreateProjectRequest,
    ImportProjectItemsRequest,
    InspectImportSessionRequest,
    MaterializeWorkspaceItemRequest,
)
from pig.bootstrap import create_local_application
from pig.domain.enums import (
    AttemptStatus,
    ErrorCode,
    ImportSessionStatus,
    MaterializationLocatorKind,
    NodeFormat,
    NodeProcessingStatus,
)
from pig.domain.processing_policy import ProcessingPolicy
from pig.handlers.archive import (
    ArchiveBackendVersionError,
    ArchiveInspection,
    ArchiveMemberInfo,
    ArchiveMemberToken,
)
from pig.handlers.msg import (
    MsgAttachmentInfo,
    MsgAttachmentKind,
    MsgAttachmentToken,
    MsgInspection,
)
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase


def _project(tmp_path: Path):
    application = create_local_application(tmp_path / "projects")
    project = application.create_project(
        CreateProjectRequest(name="W4 Project", actor="tester")
    )
    return application, project


def _import_and_inspect(
    application,
    project,
    source: Path,
    *,
    policy: ProcessingPolicy = ProcessingPolicy(),
):
    imported = application.import_project_items(
        ImportProjectItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="tester",
            idempotency_key=f"w4-{source.name}",
        )
    )
    inspected = application.inspect_import_session(
        InspectImportSessionRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            import_session_id=imported.import_session_id,
            actor="tester",
            policy=policy,
        )
    )
    return imported, inspected


def _zip_bytes(name: str, payload: bytes) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(name, payload)
    return stream.getvalue()


def _eml_bytes(attachments: list[tuple[str, bytes]]) -> bytes:
    message = EmailMessage()
    message["Subject"] = "Supplier quote"
    message["From"] = "supplier@example.test"
    message["To"] = "buyer@example.test"
    message.set_content("Body content is not projected as a file.")
    for name, payload in attachments:
        message.add_attachment(
            payload,
            maintype="application",
            subtype="octet-stream",
            filename=name,
        )
    return message.as_bytes()


def _seven_z_bytes(tmp_path: Path, name: str, payload: bytes) -> bytes:
    path = tmp_path / "fixture.7z"
    with py7zr.SevenZipFile(path, "w") as archive:
        archive.writestr(payload, name)
    return path.read_bytes()


def _workspace_item_for_name(database_path: Path, project_id: str, name: str):
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project_id))
        node = next(node for node in nodes if node.display_name == name)
        item = next(
            item
            for item in uow.workspace.items_for_project(project_id)
            if item.origin_source_node_id == node.id
        )
    return node, item


def test_mixed_zip_eml_zip_chain_is_eager_and_terminal_is_lazy(
    tmp_path: Path,
) -> None:
    email_payload = _eml_bytes(
        [("报价附件.zip", _zip_bytes("最终报价.txt", b"accepted quote"))]
    )
    source = tmp_path / "采购资料.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("供应商报价.eml", email_payload)
    application, project = _project(tmp_path)

    _, result = _import_and_inspect(application, project, source)

    assert result.session_status == ImportSessionStatus.SUCCESS
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
        attempts = tuple(uow.processing.attempts_for_project(project.project_id))
        working_count = sum(
            uow.workspace.working_artifact_for_item(item.id) is not None
            for item in uow.workspace.items_for_project(project.project_id)
        )
        email_node = next(node for node in nodes if node.format == NodeFormat.EML)
        metadata = tuple(uow.catalog.metadata_for_node(email_node.id))

    assert {node.display_name for node in nodes} == {
        "采购资料.zip",
        "供应商报价.eml",
        "报价附件.zip",
        "最终报价.txt",
    }
    assert working_count == 0
    assert {attempt.backend_name for attempt in attempts} >= {
        "python-zipfile",
        "python-email",
    }
    assert all(attempt.status == AttemptStatus.COMPLETED for attempt in attempts)
    assert any(value.key == "subject" for value in metadata)

    _, terminal_item = _workspace_item_for_name(
        project.database_path, project.project_id, "最终报价.txt"
    )
    materialized = application.materialize_workspace_item(
        MaterializeWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=terminal_item.id,
            actor="tester",
        )
    )
    assert materialized.path.read_bytes() == b"accepted quote"
    assert not (project.workspace_path / ".inspection").exists()


def test_duplicate_email_attachment_names_keep_distinct_typed_locators(
    tmp_path: Path,
) -> None:
    source = tmp_path / "duplicates.eml"
    source.write_bytes(
        _eml_bytes([("quote.txt", b"first"), ("quote.txt", b"second")])
    )
    application, project = _project(tmp_path)
    _import_and_inspect(application, project, source)

    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        nodes = [
            node
            for node in uow.catalog.nodes_for_project(project.project_id)
            if node.display_name == "quote.txt"
        ]
        items = {
            item.origin_source_node_id: item
            for item in uow.workspace.items_for_project(project.project_id)
        }
        locators = [uow.catalog.entry_locator_for_child(node.id) for node in nodes]

    assert len(nodes) == 2
    assert {locator.kind for locator in locators if locator is not None} == {
        MaterializationLocatorKind.EML_PART
    }
    assert {locator.member_ordinal for locator in locators if locator is not None} == {
        0,
        1,
    }
    outputs = {
        application.materialize_workspace_item(
            MaterializeWorkspaceItemRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                workspace_item_id=items[node.id].id,
                actor="tester",
            )
        ).path.read_bytes()
        for node in nodes
    }
    assert outputs == {b"first", b"second"}


class _FakeMsgBackend:
    name = "fake-extract-msg"
    version = "0.56.test"

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def inspect(self, path: Path, *, max_attachments: int) -> MsgInspection:
        return MsgInspection(
            headers={"subject": "Nested archive"},
            attachments=(
                MsgAttachmentInfo(
                    ordinal=0,
                    name="nested.7z",
                    kind=MsgAttachmentKind.DATA,
                ),
            ),
        )

    def read_attachment(self, path: Path, token: MsgAttachmentToken) -> bytes:
        assert token.ordinal == 0
        return self.payload


def test_msg_to_seven_z_chain_uses_the_same_registry_and_recipe_replay(
    tmp_path: Path, monkeypatch
) -> None:
    backend = _FakeMsgBackend(
        _seven_z_bytes(tmp_path, "folder/report.pdf", b"%PDF report")
    )
    monkeypatch.setattr(
        bootstrap_module, "ExtractMsgBackend", lambda: backend
    )
    source = tmp_path / "mail.msg"
    source.write_bytes(b"fake-msg-owned-by-test-adapter")
    application, project = _project(tmp_path)

    _, result = _import_and_inspect(application, project, source)

    assert result.session_status == ImportSessionStatus.SUCCESS
    terminal, item = _workspace_item_for_name(
        project.database_path, project.project_id, "report.pdf"
    )
    assert terminal.format == NodeFormat.PDF
    materialized = application.materialize_workspace_item(
        MaterializeWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
        )
    )
    assert materialized.path.read_bytes() == b"%PDF report"


class _FakeRarBackend:
    name = "7zip-system"
    version = "1.0"

    def inspect(self, path: Path, *, policy) -> ArchiveInspection:
        return ArchiveInspection(
            members=(
                ArchiveMemberInfo(
                    ordinal=0,
                    name="quote/final.txt",
                    is_directory=False,
                    is_symbolic_link=False,
                    size=9,
                    compressed_size=9,
                    encrypted=False,
                    token=ArchiveMemberToken(
                        ordinal=0, name="quote/final.txt"
                    ),
                ),
            ),
            details={
                "backend": "7zip-system",
                "backend_version": "25.01",
                "executable_sha256": "a" * 64,
            },
        )

    def write_member(self, path, token, output, *, policy) -> None:
        output.write(b"rar quote")


class _RejectedRarBackend(_FakeRarBackend):
    def inspect(self, path: Path, *, policy) -> ArchiveInspection:
        raise ArchiveBackendVersionError("configured 7-Zip version is rejected")


def test_rar_backend_identity_is_persisted_without_executable_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        bootstrap_module,
        "SevenZipRarBackend",
        lambda configured: _FakeRarBackend(),
    )
    source = tmp_path / "quotes.rar"
    source.write_bytes(b"fake-rar")
    application, project = _project(tmp_path)
    _, result = _import_and_inspect(application, project, source)

    assert result.session_status == ImportSessionStatus.SUCCESS
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        attempt = next(
            attempt
            for attempt in uow.processing.attempts_for_project(project.project_id)
            if attempt.backend_name == "7zip-system"
        )
        events = tuple(uow.processing.events_for_project(project.project_id))
    assert attempt.backend_version == "25.01"
    assert attempt.backend_sha256 == "a" * 64
    assert all("executable" not in str(event.details).lower() for event in events)
    _, item = _workspace_item_for_name(
        project.database_path, project.project_id, "final.txt"
    )
    materialized = application.materialize_workspace_item(
        MaterializeWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=item.id,
            actor="tester",
        )
    )
    assert materialized.path.read_bytes() == b"rar quote"


def test_missing_system_seven_zip_is_a_durable_unsupported_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        bootstrap_module.SevenZipRarBackend,
        "discover_standard_windows_installation",
        staticmethod(lambda: None),
    )
    source = tmp_path / "missing-backend.rar"
    source.write_bytes(b"not-opened-without-config")
    application, project = _project(tmp_path)
    _, result = _import_and_inspect(application, project, source)

    assert result.session_status == ImportSessionStatus.FAILED
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        root = next(uow.catalog.nodes_for_project(project.project_id).__iter__())
        attempt = next(
            attempt
            for attempt in uow.processing.attempts_for_project(project.project_id)
            if attempt.node_id == root.id
        )
    assert root.status == NodeProcessingStatus.UNSUPPORTED
    assert attempt.status == AttemptStatus.FAILED
    assert attempt.error is not None
    assert attempt.error.code == ErrorCode.DEPENDENCY_UNAVAILABLE


def test_rejected_system_seven_zip_version_is_a_durable_result(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        bootstrap_module,
        "SevenZipRarBackend",
        lambda configured: _RejectedRarBackend(),
    )
    source = tmp_path / "rejected-backend.rar"
    source.write_bytes(b"fake-rar")
    application, project = _project(tmp_path)
    _, result = _import_and_inspect(application, project, source)

    assert result.session_status == ImportSessionStatus.FAILED
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        attempt = next(
            attempt
            for attempt in uow.processing.attempts_for_project(project.project_id)
            if attempt.backend_name == "7zip-system"
        )
    assert attempt.error is not None
    assert attempt.error.code == ErrorCode.DEPENDENCY_VERSION_UNSUPPORTED


def test_malformed_msg_is_persisted_as_corrupted_without_aborting_the_app(
    tmp_path: Path,
) -> None:
    source = tmp_path / "malformed.msg"
    source.write_bytes(b"this is not an OLE compound file")
    application, project = _project(tmp_path)
    _, result = _import_and_inspect(application, project, source)

    assert result.session_status == ImportSessionStatus.FAILED
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        root = next(
            node
            for node in uow.catalog.nodes_for_project(project.project_id)
            if node.depth == 0
        )
        attempt = next(
            attempt
            for attempt in uow.processing.attempts_for_project(project.project_id)
            if attempt.node_id == root.id
        )
    assert root.status == NodeProcessingStatus.CORRUPTED
    assert attempt.error is not None
    assert attempt.error.code == ErrorCode.CORRUPTED_CONTAINER


def test_password_protected_seven_z_is_blocked_without_password_workflow(
    tmp_path: Path,
) -> None:
    source = tmp_path / "secret.7z"
    with py7zr.SevenZipFile(source, "w", password="secret") as archive:
        archive.writestr(b"evidence", "secret.txt")
    application, project = _project(tmp_path)
    _, result = _import_and_inspect(application, project, source)

    assert result.session_status == ImportSessionStatus.FAILED
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        root = next(
            node
            for node in uow.catalog.nodes_for_project(project.project_id)
            if node.depth == 0
        )
        attempt = next(
            attempt
            for attempt in uow.processing.attempts_for_project(project.project_id)
            if attempt.node_id == root.id
        )
    assert root.status == NodeProcessingStatus.PASSWORD_REQUIRED
    assert attempt.error is not None
    assert attempt.error.code == ErrorCode.PASSWORD_REQUIRED


def test_seven_z_member_limit_is_visible_and_siblings_do_not_crash(
    tmp_path: Path,
) -> None:
    source = tmp_path / "limited.7z"
    with py7zr.SevenZipFile(source, "w") as archive:
        archive.writestr(b"too large", "large.txt")
        archive.writestr(b"ok", "small.txt")
    application, project = _project(tmp_path)
    _, result = _import_and_inspect(
        application,
        project,
        source,
        policy=ProcessingPolicy(
            max_single_file_size=4,
            max_total_expanded_size=1024,
        ),
    )

    assert result.session_status == ImportSessionStatus.PARTIAL_SUCCESS
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        nodes = {
            node.display_name: node
            for node in uow.catalog.nodes_for_project(project.project_id)
        }
    assert nodes["large.txt"].status == NodeProcessingStatus.LIMIT_EXCEEDED
    assert nodes["small.txt"].status == NodeProcessingStatus.SUCCESS
