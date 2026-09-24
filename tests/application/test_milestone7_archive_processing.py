from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import py7zr
import pytest

import pig.bootstrap as bootstrap_module
from pig.application import (
    CreateProjectRequest,
    GetNodeRequest,
    GetProjectOverviewRequest,
    ProcessProjectRequest,
    RegisterSourceRequest,
)
from pig.domain.enums import (
    ErrorCategory,
    ErrorCode,
    JobStatus,
    NodeFormat,
    NodeProcessingStatus,
    ProjectStatus,
    RelationshipType,
    SourceKind,
)
from pig.domain.processing_policy import ProcessingPolicy
from pig.handlers.archive import (
    ArchiveBackend,
    ArchiveBackendDependencyError,
    ArchiveHandler,
    ArchiveInspection,
    ArchiveMemberInfo,
    ArchiveMemberToken,
)
from pig.handlers.base import HandlerOutcomeError
from pig.infrastructure.archives.seven_zip_rar_adapter import (
    CommandOutputLimitError,
    CommandResult,
    CommandTimeoutError,
    SevenZipRarBackend,
)
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase


class Sequence:
    def __init__(self) -> None:
        self.number = 0

    def __call__(self) -> str:
        self.number += 1
        return f"m7-id-{self.number}"


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
    return app.create_project(CreateProjectRequest(name="M7", actor="tester"))


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


def _zip_bytes() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("最终报价.xlsx", b"PK\x03\x04workbook")
    return stream.getvalue()


def test_real_7z_recurses_into_zip_and_persists_lineage(app, tmp_path: Path) -> None:
    project = _project(app)
    source_path = tmp_path / "采购资料.7z"
    with py7zr.SevenZipFile(source_path, "w") as archive:
        archive.writestr(_zip_bytes(), "邮件资料/报价附件.zip")
    original = source_path.read_bytes()
    source = _register(app, project, source_path)

    result = _process(app, project)

    assert result.job_status == JobStatus.SUCCESS
    assert result.project_status == ProjectStatus.READY
    assert source_path.read_bytes() == original
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
    by_name = {node.original_name: node for node in nodes}
    archive_child = by_name["邮件资料/报价附件.zip"]
    assert archive_child.format == NodeFormat.ZIP
    assert archive_child.logical_path.endswith(
        "/采购资料.7z!/邮件资料/报价附件.zip"
    )
    final = _details(app, project, by_name["最终报价.xlsx"].id)
    assert [item.distance for item in final.lineage] == [3, 2, 1, 0]
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        relationship = uow.catalog.relationship_for_child(archive_child.id)
    assert relationship is not None
    assert relationship.type == RelationshipType.FOLDER_CONTAINS
    opened = next(
        event
        for event in app.get_project_overview(
            GetProjectOverviewRequest(
                project_id=project.project_id,
                database_path=project.database_path,
            )
        ).events
        if event.node_id == source.root_node_id
        and event.event_type.value == "CONTAINER_OPENED"
    )
    assert opened.details["inspection"]["backend"] == "py7zr"


def test_password_protected_7z_is_blocked_without_children(app, tmp_path: Path) -> None:
    project = _project(app)
    source_path = tmp_path / "secret.7z"
    with py7zr.SevenZipFile(source_path, "w", password="secret") as archive:
        archive.writestr(b"evidence", "secret.txt")
    source = _register(app, project, source_path)

    result = _process(app, project)

    root = _details(app, project, source.root_node_id)
    assert root.node.status == NodeProcessingStatus.PASSWORD_REQUIRED
    assert root.children == ()
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        attempt = uow.processing.get_attempt(result.attempt_ids[0])
    assert attempt is not None and attempt.error is not None
    assert attempt.error.code == ErrorCode.PASSWORD_REQUIRED


def test_corrupted_7z_is_a_durable_format_outcome(app, tmp_path: Path) -> None:
    project = _project(app)
    source_path = tmp_path / "broken.7z"
    source_path.write_bytes(b"not-a-seven-zip-file")
    source = _register(app, project, source_path)

    result = _process(app, project)

    assert result.job_status == JobStatus.FAILED
    assert _details(app, project, source.root_node_id).node.status == NodeProcessingStatus.CORRUPTED


class FakeArchiveBackend(ArchiveBackend):
    name = "fake"
    version = "1.0"

    def __init__(self, members: tuple[ArchiveMemberInfo, ...]) -> None:
        self.members = members

    def inspect(self, path: Path, *, policy: ProcessingPolicy) -> ArchiveInspection:
        return ArchiveInspection(members=self.members)

    def write_member(
        self,
        path: Path,
        token: ArchiveMemberToken,
        output,
        *,
        policy: ProcessingPolicy,
    ) -> None:
        raise AssertionError("blocked members must not be materialized")


def _member(
    ordinal: int,
    name: str,
    *,
    symlink: bool = False,
    encrypted: bool = False,
) -> ArchiveMemberInfo:
    return ArchiveMemberInfo(
        ordinal=ordinal,
        name=name,
        is_directory=False,
        is_symbolic_link=symlink,
        size=4,
        compressed_size=4,
        encrypted=encrypted,
        token=ArchiveMemberToken(ordinal=ordinal, name=name),
    )


def test_archive_handler_catalogs_unsafe_links_encryption_and_duplicate_identity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.7z"
    source.write_bytes(b"archive")
    backend = FakeArchiveBackend(
        (
            _member(0, "../../outside.txt"),
            _member(1, "link.txt", symlink=True),
            _member(2, "secret.txt", encrypted=True),
            _member(3, "duplicate.txt"),
            _member(4, "duplicate.txt"),
        )
    )

    inspection = ArchiveHandler(NodeFormat.SEVEN_Z, backend).inspect(
        source, ProcessingPolicy()
    )

    assert [child.blocked_status for child in inspection.children] == [
        NodeProcessingStatus.SECURITY_BLOCKED,
        NodeProcessingStatus.SECURITY_BLOCKED,
        NodeProcessingStatus.PASSWORD_REQUIRED,
        NodeProcessingStatus.UNSUPPORTED,
        NodeProcessingStatus.UNSUPPORTED,
    ]
    assert inspection.children[0].error_code == ErrorCode.PATH_TRAVERSAL_BLOCKED
    assert inspection.children[1].error_code == ErrorCode.SYMLINK_BLOCKED


def test_archive_handler_applies_declared_compression_ratio_limit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ratio.7z"
    source.write_bytes(b"archive")
    member = ArchiveMemberInfo(
        ordinal=0,
        name="large.bin",
        is_directory=False,
        is_symbolic_link=False,
        size=100,
        compressed_size=1,
        encrypted=False,
        token=ArchiveMemberToken(ordinal=0, name="large.bin"),
    )

    inspection = ArchiveHandler(
        NodeFormat.SEVEN_Z, FakeArchiveBackend((member,))
    ).inspect(source, ProcessingPolicy(max_compression_ratio=2.0))

    assert (
        inspection.children[0].blocked_status
        == NodeProcessingStatus.LIMIT_EXCEEDED
    )
    assert (
        inspection.children[0].error_code
        == ErrorCode.MAX_COMPRESSION_RATIO_EXCEEDED
    )


def test_archive_handler_rejects_excessive_entry_count(tmp_path: Path) -> None:
    source = tmp_path / "entries.7z"
    source.write_bytes(b"archive")
    backend = FakeArchiveBackend((_member(0, "a.txt"), _member(1, "b.txt")))

    with pytest.raises(HandlerOutcomeError) as raised:
        ArchiveHandler(NodeFormat.SEVEN_Z, backend).inspect(
            source, ProcessingPolicy(max_archive_entries=1)
        )

    assert raised.value.status == NodeProcessingStatus.LIMIT_EXCEEDED
    assert raised.value.code == ErrorCode.MAX_ARCHIVE_ENTRIES_EXCEEDED


def test_rar_without_configured_system_7zip_is_structured_unsupported(
    app, tmp_path: Path
) -> None:
    project = _project(app)
    source_path = tmp_path / "evidence.rar"
    source_path.write_bytes(b"rar-source")
    source = _register(app, project, source_path)

    result = _process(app, project)

    root = _details(app, project, source.root_node_id)
    assert root.node.status == NodeProcessingStatus.UNSUPPORTED
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        attempt = uow.processing.get_attempt(result.attempt_ids[0])
    assert attempt is not None and attempt.error is not None
    assert attempt.error.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    assert attempt.error.category == ErrorCategory.PROCESSING


class FakeCommandRunner:
    def __init__(self, member_payload: bytes, version: str = "26.03") -> None:
        self.member_payload = member_payload
        self.version = version
        self.captured: list[tuple[str, ...]] = []
        self.streamed: list[tuple[str, ...]] = []

    def capture(
        self,
        arguments,
        *,
        timeout_seconds: float,
        max_stdout_size: int,
        max_stderr_size: int,
    ) -> CommandResult:
        command = tuple(arguments)
        self.captured.append(command)
        if command[1] == "i":
            return CommandResult(
                return_code=0,
                stdout=f"7-Zip (z) {self.version} (x64)".encode(),
            )
        listing = (
            "Path = nested.zip\n"
            f"Size = {len(self.member_payload)}\n"
            f"Packed Size = {len(self.member_payload)}\n"
            "Attributes = A\n"
            "Encrypted = -\n\n"
        )
        return CommandResult(return_code=0, stdout=listing.encode())

    def stream_stdout(
        self,
        arguments,
        output,
        *,
        timeout_seconds: float,
        max_stderr_size: int,
    ) -> CommandResult:
        self.streamed.append(tuple(arguments))
        output.write(self.member_payload)
        return CommandResult(return_code=0)


class FailingListingRunner(FakeCommandRunner):
    def __init__(self, failure: Exception) -> None:
        super().__init__(b"")
        self.failure = failure

    def capture(
        self,
        arguments,
        *,
        timeout_seconds: float,
        max_stdout_size: int,
        max_stderr_size: int,
    ) -> CommandResult:
        command = tuple(arguments)
        self.captured.append(command)
        if command[1] == "i":
            return CommandResult(return_code=0, stdout=b"7-Zip (z) 26.03 (x64)")
        raise self.failure


def test_controlled_rar_adapter_streams_to_artifact_and_recurses_zip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = (tmp_path / "7zz.exe").absolute()
    executable.write_bytes(b"trusted-test-double")
    runner = FakeCommandRunner(_zip_bytes())
    backend = SevenZipRarBackend(executable, runner=runner)
    monkeypatch.setattr(
        bootstrap_module, "SevenZipRarBackend", lambda configured: backend
    )
    app = bootstrap_module.create_local_application(
        (tmp_path / "workspace").absolute(),
        seven_zip_executable=executable,
        clock=Clock(),
        id_generator=Sequence(),
    )
    project = _project(app)
    source_path = tmp_path / "supplier.rar"
    source_path.write_bytes(b"rar-source")
    source = _register(app, project, source_path)

    result = _process(app, project)

    assert result.job_status == JobStatus.SUCCESS
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        nodes = tuple(uow.catalog.nodes_for_project(project.project_id))
    by_name = {node.original_name: node for node in nodes}
    assert by_name["nested.zip"].format == NodeFormat.ZIP
    assert by_name["最终报价.xlsx"].status == NodeProcessingStatus.SUCCESS
    assert [item.distance for item in _details(
        app, project, by_name["最终报价.xlsx"].id
    ).lineage] == [2, 1, 0]
    assert len(runner.captured) == 3
    assert len(runner.streamed) == 1
    list_command = runner.captured[1]
    extract_command = runner.streamed[0]
    assert list_command[0] == str(executable)
    assert "--" in list_command
    assert "-p" not in list_command
    assert "-so" in extract_command
    assert "-spd" in extract_command
    assert extract_command[-1] == "nested.zip"
    opened = next(
        event
        for event in app.get_project_overview(
            GetProjectOverviewRequest(
                project_id=project.project_id,
                database_path=project.database_path,
            )
        ).events
        if event.node_id == source.root_node_id
        and event.event_type.value == "CONTAINER_OPENED"
    )
    assert opened.details["inspection"]["backend_version"] == "26.03"
    assert len(opened.details["inspection"]["executable_sha256"]) == 64


@pytest.mark.parametrize(
    ("failure", "expected_code", "retryable"),
    (
        (
            CommandOutputLimitError("too much output"),
            ErrorCode.EXTERNAL_PROCESS_OUTPUT_EXCEEDED,
            False,
        ),
        (
            CommandTimeoutError("too slow"),
            ErrorCode.EXTERNAL_PROCESS_TIMEOUT,
            True,
        ),
    ),
)
def test_rar_process_limits_are_persisted_as_precise_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: Exception,
    expected_code: ErrorCode,
    retryable: bool,
) -> None:
    executable = (tmp_path / "7zz.exe").absolute()
    executable.write_bytes(b"trusted-test-double")
    backend = SevenZipRarBackend(
        executable, runner=FailingListingRunner(failure)
    )
    monkeypatch.setattr(
        bootstrap_module, "SevenZipRarBackend", lambda configured: backend
    )
    app = bootstrap_module.create_local_application(
        (tmp_path / "workspace").absolute(),
        seven_zip_executable=executable,
        clock=Clock(),
        id_generator=Sequence(),
    )
    project = _project(app)
    source_path = tmp_path / "limited.rar"
    source_path.write_bytes(b"rar-source")
    source = _register(app, project, source_path)

    result = _process(app, project)

    assert (
        _details(app, project, source.root_node_id).node.status
        == NodeProcessingStatus.LIMIT_EXCEEDED
    )
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        attempt = uow.processing.get_attempt(result.attempt_ids[0])
    assert attempt is not None and attempt.error is not None
    assert attempt.error.code == expected_code
    assert attempt.error.retryable is retryable


def test_rar_adapter_rejects_unapproved_system_7zip_version(tmp_path: Path) -> None:
    executable = (tmp_path / "7zz.exe").absolute()
    executable.write_bytes(b"old-test-double")
    backend = SevenZipRarBackend(
        executable, runner=FakeCommandRunner(b"data", version="24.09")
    )
    archive = tmp_path / "input.rar"
    archive.write_bytes(b"rar")

    handler = ArchiveHandler(NodeFormat.RAR, backend)
    with pytest.raises(HandlerOutcomeError) as raised:
        handler.inspect(archive, ProcessingPolicy())

    assert raised.value.status == NodeProcessingStatus.UNSUPPORTED
    assert raised.value.code == ErrorCode.DEPENDENCY_VERSION_UNSUPPORTED


def test_rar_adapter_rejects_executable_changed_after_validation(
    tmp_path: Path,
) -> None:
    executable = (tmp_path / "7zz.exe").absolute()
    executable.write_bytes(b"accepted-binary")
    runner = FakeCommandRunner(b"data")
    backend = SevenZipRarBackend(executable, runner=runner)
    archive = tmp_path / "input.rar"
    archive.write_bytes(b"rar")
    inspection = backend.inspect(archive, policy=ProcessingPolicy())
    executable.write_bytes(b"replaced-binary")

    with pytest.raises(ArchiveBackendDependencyError):
        backend.write_member(
            archive,
            inspection.members[0].token,
            io.BytesIO(),
            policy=ProcessingPolicy(),
        )


def test_rar_listing_marks_link_and_encrypted_members() -> None:
    members = SevenZipRarBackend._parse_listing(
        (
            "Path = link\nSize = 6\nPacked Size = 6\n"
            "Attributes = A l---------\nSymbolic Link = target\nEncrypted = -\n\n"
            "Path = secret.txt\nSize = 4\nPacked Size = 4\n"
            "Attributes = A\nEncrypted = +\n\n"
        ).encode()
    )

    assert members[0].is_symbolic_link is True
    assert members[1].encrypted is True
