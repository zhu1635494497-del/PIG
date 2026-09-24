from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone
from email import policy as email_policy
from email.message import EmailMessage
from pathlib import Path

import pytest
from extract_msg.enums import AttachmentType

import pig.bootstrap as bootstrap_module
from pig.application import (
    CreateProjectRequest,
    GetNodeRequest,
    ProcessProjectRequest,
    RegisterSourceRequest,
)
from pig.domain.enums import (
    ErrorCode,
    JobStatus,
    NodeFormat,
    NodeProcessingStatus,
    ProjectStatus,
    RelationshipType,
    SourceKind,
)
from pig.domain.processing_policy import ProcessingPolicy
from pig.handlers.msg import (
    MsgAttachmentInfo,
    MsgAttachmentKind,
    MsgAttachmentToken,
    MsgInspection,
)
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase
from pig.infrastructure.email import ExtractMsgBackend


class Sequence:
    def __init__(self) -> None:
        self.number = 0

    def __call__(self) -> str:
        self.number += 1
        return f"m6-id-{self.number}"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 14, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(microseconds=1)
        return current


@pytest.fixture
def app(tmp_path: Path):
    return bootstrap_module.create_local_application(
        (tmp_path / "workspace").absolute(),
        clock=Clock(),
        id_generator=Sequence(),
    )


def _project(app):
    return app.create_project(CreateProjectRequest(name="M6", actor="tester"))


def _register(app, project, path: Path):
    return app.register_source(
        RegisterSourceRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            source_path=path.absolute(),
            source_kind=SourceKind.FILE,
            actor="tester",
        )
    )


def _process(app, project, policy: ProcessingPolicy | None = None):
    return app.process_project(
        ProcessProjectRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            actor="tester",
            policy=policy or ProcessingPolicy(),
        )
    )


def _details(app, project, node_id: str):
    return app.get_node(
        GetNodeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            node_id=node_id,
        )
    )


def _nested_eml_bytes() -> bytes:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("最终报价.xlsx", b"PK\x03\x04workbook")

    forwarded = EmailMessage()
    forwarded["Subject"] = "Forwarded quote"
    forwarded["From"] = "supplier@example.test"
    forwarded["To"] = "buyer@example.test"
    forwarded.set_content("This body is not a V1 child node.")
    forwarded.add_attachment(
        archive_bytes.getvalue(),
        maintype="application",
        subtype="zip",
        filename="报价附件.zip",
    )

    root = EmailMessage()
    root["Subject"] = "采购报价"
    root["From"] = "buyer@example.test"
    root["To"] = "audit@example.test"
    root["Message-ID"] = "<root@example.test>"
    root.set_content("This body is also deliberately not extracted in V1.")
    root.add_attachment(
        b"%PDF-evidence",
        maintype="application",
        subtype="pdf",
        filename="报价.pdf",
    )
    root.add_attachment(forwarded, filename="转发邮件.eml")
    return root.as_bytes(policy=email_policy.default)


def test_eml_recurses_through_embedded_message_and_zip_with_durable_lineage(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_path = tmp_path / "采购邮件.eml"
    source_path.write_bytes(_nested_eml_bytes())
    source = _register(app, project, source_path)

    result = _process(app, project)

    assert result.job_status == JobStatus.SUCCESS
    assert result.project_status == ProjectStatus.READY
    assert len(result.processed_node_ids) == 5
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
        relationships = {
            node.original_name: uow.catalog.relationship_for_child(node.id)
            for node in nodes
            if node.id != source.root_node_id
        }
    by_name = {node.original_name: node for node in nodes}
    assert set(by_name) == {
        "采购邮件.eml",
        "报价.pdf",
        "转发邮件.eml",
        "报价附件.zip",
        "最终报价.xlsx",
    }
    assert relationships["报价.pdf"].type == RelationshipType.EMAIL_ATTACHMENT
    assert relationships["转发邮件.eml"].type == RelationshipType.EMBEDDED_MESSAGE
    assert relationships["报价附件.zip"].type == RelationshipType.EMAIL_ATTACHMENT
    assert relationships["最终报价.xlsx"].type == RelationshipType.ARCHIVE_ENTRY
    final = _details(app, project, by_name["最终报价.xlsx"].id)
    assert [item.distance for item in final.lineage] == [3, 2, 1, 0]
    metadata = {
        item.key: item.value_text
        for item in _details(app, project, source.root_node_id).metadata
    }
    assert metadata["subject"] == "采购报价"
    assert metadata["message_id"] == "<root@example.test>"
    assert all("body" not in node.original_name.lower() for node in nodes)


def test_eml_mime_part_limit_is_a_durable_resource_outcome(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_path = tmp_path / "parts.eml"
    message = EmailMessage()
    message.set_content("body")
    message.add_attachment(
        b"one", maintype="application", subtype="octet-stream", filename="one.bin"
    )
    source_path.write_bytes(message.as_bytes(policy=email_policy.default))
    source = _register(app, project, source_path)

    result = _process(app, project, ProcessingPolicy(max_email_parts=2))

    root = _details(app, project, source.root_node_id)
    assert root.node.status == NodeProcessingStatus.LIMIT_EXCEEDED
    assert root.children == ()
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        attempt = uow.processing.get_attempt(result.attempt_ids[0])
        job = uow.processing.get_job(result.job_id)
    assert attempt is not None and attempt.error is not None
    assert attempt.error.code == ErrorCode.MAX_NODE_COUNT_EXCEEDED
    assert job is not None and job.policy_snapshot["max_email_parts"] == 2


def test_unsafe_eml_attachment_name_is_cataloged_but_not_materialized(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_path = tmp_path / "unsafe.eml"
    message = EmailMessage()
    message.set_content("body")
    message.add_attachment(
        b"unsafe",
        maintype="application",
        subtype="octet-stream",
        filename="../../outside.txt",
    )
    source_path.write_bytes(message.as_bytes(policy=email_policy.default))
    _register(app, project, source_path)

    result = _process(app, project)

    assert result.job_status == JobStatus.PARTIAL_SUCCESS
    child = _details(app, project, result.processed_node_ids[0]).children[0]
    detail = _details(app, project, child.id)
    assert child.status == NodeProcessingStatus.SECURITY_BLOCKED
    assert detail.artifacts == ()
    assert not (project.workspace_path.parent / "outside.txt").exists()


def test_eml_attachments_share_the_job_expanded_size_budget(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_path = tmp_path / "budget.eml"
    message = EmailMessage()
    message.set_content("body")
    for name in ("one.bin", "two.bin"):
        message.add_attachment(
            b"1234",
            maintype="application",
            subtype="octet-stream",
            filename=name,
        )
    source_path.write_bytes(message.as_bytes(policy=email_policy.default))
    source = _register(app, project, source_path)

    result = _process(
        app, project, ProcessingPolicy(max_total_expanded_size=6)
    )

    root = _details(app, project, source.root_node_id)
    assert result.total_expanded_size == 4
    assert result.job_status == JobStatus.PARTIAL_SUCCESS
    child_details = [_details(app, project, child.id) for child in root.children]
    assert [item.node.status for item in child_details] == [
        NodeProcessingStatus.SUCCESS,
        NodeProcessingStatus.LIMIT_EXCEEDED,
    ]
    assert len(child_details[0].artifacts) == 1
    assert child_details[1].artifacts == ()


class FakeMsgBackend:
    name = "fake"
    version = "1.0"

    def __init__(self, embedded_eml: bytes) -> None:
        self.payloads = {
            0: b"%PDF-msg-attachment",
            1: b"nested-msg-empty",
            2: embedded_eml,
        }
        self.read_ordinals: list[int] = []

    def inspect(self, path: Path, *, max_attachments: int) -> MsgInspection:
        if path.read_bytes() == b"nested-msg-empty":
            return MsgInspection(
                headers={"subject": "Embedded MSG"}, attachments=()
            )
        attachments = (
            MsgAttachmentInfo(
                ordinal=0,
                name="msg-quote.pdf",
                kind=MsgAttachmentKind.DATA,
                media_type="application/pdf",
            ),
            MsgAttachmentInfo(
                ordinal=1,
                name="forwarded.msg",
                kind=MsgAttachmentKind.EMBEDDED_MESSAGE,
                media_type="application/vnd.ms-outlook",
            ),
            MsgAttachmentInfo(
                ordinal=2,
                name="attached.eml",
                kind=MsgAttachmentKind.DATA,
                media_type="message/rfc822",
            ),
            MsgAttachmentInfo(
                ordinal=3,
                name="remote.url",
                kind=MsgAttachmentKind.WEB_REFERENCE,
            ),
        )
        if len(attachments) > max_attachments:
            raise AssertionError("test policy unexpectedly too small")
        return MsgInspection(
            headers={"subject": "MSG quote", "from": "vendor@example.test"},
            attachments=attachments,
        )

    def read_attachment(self, path: Path, token: MsgAttachmentToken) -> bytes:
        self.read_ordinals.append(token.ordinal)
        return self.payloads[token.ordinal]


def test_msg_adapter_boundary_recurses_and_never_reads_web_reference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    embedded = EmailMessage()
    embedded["Subject"] = "Nested from MSG"
    embedded.set_content("body")
    embedded.add_attachment(
        b"evidence",
        maintype="text",
        subtype="plain",
        filename="nested.txt",
    )
    backend = FakeMsgBackend(embedded.as_bytes(policy=email_policy.default))
    monkeypatch.setattr(bootstrap_module, "ExtractMsgBackend", lambda: backend)
    app = bootstrap_module.create_local_application(
        (tmp_path / "workspace").absolute(),
        clock=Clock(),
        id_generator=Sequence(),
    )
    project = _project(app)
    source_path = tmp_path / "supplier.msg"
    source_path.write_bytes(b"fake-msg-source")
    source = _register(app, project, source_path)

    result = _process(app, project)

    assert result.job_status == JobStatus.PARTIAL_SUCCESS
    assert backend.read_ordinals == [0, 1, 2]
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
    by_name = {node.original_name: node for node in nodes}
    assert by_name["supplier.msg"].format == NodeFormat.MSG
    assert by_name["forwarded.msg"].format == NodeFormat.MSG
    assert by_name["attached.eml"].format == NodeFormat.EML
    assert by_name["nested.txt"].status == NodeProcessingStatus.SUCCESS
    assert by_name["remote.url"].status == NodeProcessingStatus.SECURITY_BLOCKED
    assert _details(app, project, by_name["remote.url"].id).artifacts == ()
    metadata = {
        item.key: item.value_text
        for item in _details(app, project, source.root_node_id).metadata
    }
    assert metadata["subject"] == "MSG quote"
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        embedded_relationship = uow.catalog.relationship_for_child(
            by_name["forwarded.msg"].id
        )
    assert embedded_relationship is not None
    assert embedded_relationship.type == RelationshipType.EMBEDDED_MESSAGE


class _EmbeddedData:
    def exportBytes(self) -> bytes:
        return b"embedded-msg"


class _FakeAttachment:
    def __init__(self, name: str, kind: AttachmentType, data: object) -> None:
        self.name = name
        self.type = kind
        self.data = data
        self.mimetype = "application/octet-stream"

    def save(self, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("adapter must not delegate filesystem writes")


class _FakeExtractMsgMessage:
    subject = "Adapter subject"
    sender = "sender@example.test"
    to = "receiver@example.test"
    cc = None
    bcc = None
    date = "2026-09-14"
    messageId = "<adapter@example.test>"

    def __init__(self) -> None:
        self.attachments = (
            _FakeAttachment("ordinary.bin", AttachmentType.DATA, b"ordinary"),
            _FakeAttachment("nested.msg", AttachmentType.MSG, _EmbeddedData()),
            _FakeAttachment("remote", AttachmentType.WEB, object()),
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def test_extract_msg_adapter_returns_data_only_and_never_writes_paths(
    tmp_path: Path,
) -> None:
    opened: list[tuple[bool, bool]] = []

    def opener(path, *, strict: bool, delayAttachments: bool):
        opened.append((strict, delayAttachments))
        return _FakeExtractMsgMessage()

    backend = ExtractMsgBackend(opener=opener)
    inspection = backend.inspect(tmp_path / "unused.msg", max_attachments=3)

    assert [item.kind for item in inspection.attachments] == [
        MsgAttachmentKind.DATA,
        MsgAttachmentKind.EMBEDDED_MESSAGE,
        MsgAttachmentKind.WEB_REFERENCE,
    ]
    assert backend.read_attachment(
        tmp_path / "unused.msg",
        MsgAttachmentToken(ordinal=0, kind=MsgAttachmentKind.DATA),
    ) == b"ordinary"
    assert backend.read_attachment(
        tmp_path / "unused.msg",
        MsgAttachmentToken(ordinal=1, kind=MsgAttachmentKind.EMBEDDED_MESSAGE),
    ) == b"embedded-msg"
    assert opened == [(True, False), (True, False), (True, False)]


def test_invalid_real_msg_is_recorded_as_corrupted_not_an_internal_failure(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_path = tmp_path / "corrupted.msg"
    source_path.write_bytes(b"not-an-ole-compound-file")
    source = _register(app, project, source_path)

    result = _process(app, project)

    detail = _details(app, project, source.root_node_id)
    assert detail.node.status == NodeProcessingStatus.CORRUPTED
    assert result.job_status == JobStatus.FAILED
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        attempt = uow.processing.get_attempt(result.attempt_ids[0])
    assert attempt is not None and attempt.error is not None
    assert attempt.error.code == ErrorCode.CORRUPTED_CONTAINER
