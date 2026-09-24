from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from pig.application import (
    CreateProjectRequest,
    GetNodeRequest,
    GetProjectOverviewRequest,
    LoadProjectRequest,
    RegisterSourceRequest,
)
from pig.application.errors import ApplicationError
from pig.application.service import PigApplication
from pig.bootstrap import create_local_application
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase
from pig.infrastructure.filesystem import LocalSourceInspector, LocalWorkspaceManager
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    ArtifactRole,
    ArtifactScope,
    EventType,
    NodeFormat,
    NodeKind,
    NodeProcessingStatus,
    ProjectStatus,
    SourceKind,
    SourceStatus,
)


class Sequence:
    def __init__(self) -> None:
        self._number = 0

    def id(self) -> str:
        self._number += 1
        return f"id-{self._number}"


class Clock:
    def __init__(self) -> None:
        self._value = datetime(2026, 9, 13, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        value = self._value
        self._value += timedelta(microseconds=1)
        return value


@pytest.fixture
def local_app(tmp_path: Path):
    ids = Sequence()
    return create_local_application(
        (tmp_path / "pig-workspace").absolute(),
        clock=Clock(),
        id_generator=ids.id,
    )


def _create_project(local_app):
    return local_app.create_project(
        CreateProjectRequest(name="采购尽调", description="M3", actor="tester")
    )


def test_create_project_initializes_isolated_database_and_event(local_app) -> None:
    created = _create_project(local_app)

    assert created.status == ProjectStatus.CREATED
    assert created.database_path == created.workspace_path / "project.sqlite"
    assert created.database_path.is_file()
    assert not (created.workspace_path / "extracted").exists()
    assert not (created.workspace_path / "manifests").exists()

    overview = local_app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=created.project_id,
            database_path=created.database_path,
        )
    )
    assert overview.project.name == "采购尽调"
    assert overview.project.workspace_locator == created.workspace_path.as_uri()
    assert overview.sources == ()
    assert [event.event_type for event in overview.events] == [
        EventType.PROJECT_CREATED
    ]


def test_create_project_uses_caller_selected_workspace_root(
    local_app, tmp_path: Path
) -> None:
    selected_root = (tmp_path / "user-selected-project-storage").absolute()

    created = local_app.create_project(
        CreateProjectRequest(
            name="指定位置项目",
            actor="tester",
            workspace_root=selected_root,
        )
    )

    assert created.workspace_path.parent == selected_root / "projects"
    assert created.workspace_path.name == created.project_id
    assert created.database_path == created.workspace_path / "project.sqlite"
    assert created.database_path.is_file()
    overview = local_app.load_project(
        LoadProjectRequest(database_path=created.database_path)
    )
    assert overview.project.workspace_locator == created.workspace_path.as_uri()


def test_create_project_rejects_relative_workspace_root(local_app) -> None:
    with pytest.raises(ApplicationError) as raised:
        local_app.create_project(
            CreateProjectRequest(
                name="非法位置项目",
                actor="tester",
                workspace_root=Path("relative-storage"),
            )
        )

    assert raised.value.code == "INVALID_REQUEST"


def test_register_file_source_builds_root_artifact_lineage_and_history(
    local_app, tmp_path: Path
) -> None:
    created = _create_project(local_app)
    source_path = (tmp_path / "最终报价.xlsx").absolute()
    payload = b"not-an-xlsx-yet-milestone-4-detects-format"
    source_path.write_bytes(payload)
    before = source_path.stat()

    registered = local_app.register_source(
        RegisterSourceRequest(
            project_id=created.project_id,
            database_path=created.database_path,
            source_path=source_path,
            source_kind=SourceKind.FILE,
            actor="tester",
        )
    )

    after = source_path.stat()
    assert source_path.read_bytes() == payload
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns
    assert registered.source_status == SourceStatus.AVAILABLE
    assert registered.artifact_id is not None

    overview = local_app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=created.project_id,
            database_path=created.database_path,
        )
    )
    assert overview.project.status == ProjectStatus.IMPORTING
    assert len(overview.sources) == 1
    source_view = overview.sources[0]
    assert source_view.source.locator == source_path.as_uri()
    assert source_view.source.observed_sha256 == hashlib.sha256(payload).hexdigest()
    assert source_view.root_node.id == registered.root_node_id
    assert source_view.root_node.kind == NodeKind.FILE
    assert source_view.root_node.format == NodeFormat.UNKNOWN
    assert source_view.root_node.status == NodeProcessingStatus.DISCOVERED
    assert source_view.root_node.logical_path == "/最终报价.xlsx"
    assert len(source_view.artifacts) == 1
    artifact = source_view.artifacts[0]
    assert artifact.role == ArtifactRole.ORIGINAL_REFERENCE
    assert artifact.scope == ArtifactScope.EXTERNAL_SOURCE
    assert artifact.integrity_status == ArtifactIntegrityStatus.VERIFIED
    assert artifact.sha256 == hashlib.sha256(payload).hexdigest()

    node = local_app.get_node(
        GetNodeRequest(
            project_id=created.project_id,
            database_path=created.database_path,
            node_id=registered.root_node_id,
        )
    )
    assert node.source.id == registered.source_id
    assert [(item.ancestor_node_id, item.descendant_node_id, item.distance) for item in node.lineage] == [
        (registered.root_node_id, registered.root_node_id, 0)
    ]
    event_types = [event.event_type for event in overview.events]
    assert event_types == [
        EventType.PROJECT_CREATED,
        EventType.PROJECT_STATUS_CHANGED,
        EventType.SOURCE_REGISTERED,
        EventType.SOURCE_VERIFICATION_STARTED,
        EventType.SOURCE_VERIFIED,
        EventType.NODE_DISCOVERED,
        EventType.ARTIFACT_REGISTERED,
    ]


def test_register_folder_creates_only_a_folder_root(local_app, tmp_path: Path) -> None:
    created = _create_project(local_app)
    source_path = (tmp_path / "采购资料").absolute()
    source_path.mkdir()
    (source_path / "not-discovered-in-m3.pdf").write_bytes(b"pdf")

    registered = local_app.register_source(
        RegisterSourceRequest(
            project_id=created.project_id,
            database_path=created.database_path,
            source_path=source_path,
            source_kind=SourceKind.FOLDER,
            actor="tester",
        )
    )

    assert registered.artifact_id is None
    overview = local_app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=created.project_id,
            database_path=created.database_path,
        )
    )
    source_view = overview.sources[0]
    assert source_view.source.observed_sha256 is None
    assert source_view.source.observed_size is None
    assert source_view.root_node.kind == NodeKind.CONTAINER
    assert source_view.root_node.format == NodeFormat.FOLDER
    assert source_view.artifacts == ()
    node = local_app.get_node(
        GetNodeRequest(
            project_id=created.project_id,
            database_path=created.database_path,
            node_id=registered.root_node_id,
        )
    )
    assert len(node.lineage) == 1


@pytest.mark.parametrize(
    ("source_name", "expected_kind", "expected_code"),
    [
        ("missing.zip", SourceKind.FILE, "SOURCE_NOT_FOUND"),
        ("existing-folder", SourceKind.FILE, "SOURCE_KIND_MISMATCH"),
    ],
)
def test_rejected_source_leaves_catalog_and_project_state_unchanged(
    local_app,
    tmp_path: Path,
    source_name: str,
    expected_kind: SourceKind,
    expected_code: str,
) -> None:
    created = _create_project(local_app)
    source_path = (tmp_path / source_name).absolute()
    if source_name == "existing-folder":
        source_path.mkdir()

    with pytest.raises(ApplicationError) as raised:
        local_app.register_source(
            RegisterSourceRequest(
                project_id=created.project_id,
                database_path=created.database_path,
                source_path=source_path,
                source_kind=expected_kind,
                actor="tester",
            )
        )

    assert raised.value.code == expected_code
    overview = local_app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=created.project_id,
            database_path=created.database_path,
        )
    )
    assert overview.project.status == ProjectStatus.CREATED
    assert overview.sources == ()
    assert [event.event_type for event in overview.events] == [
        EventType.PROJECT_CREATED
    ]


def test_relative_source_path_is_rejected_before_registration(local_app) -> None:
    created = _create_project(local_app)
    with pytest.raises(ApplicationError) as raised:
        local_app.register_source(
            RegisterSourceRequest(
                project_id=created.project_id,
                database_path=created.database_path,
                source_path=Path("relative.zip"),
                source_kind=SourceKind.FILE,
                actor="tester",
            )
        )
    assert raised.value.code == "INVALID_REQUEST"


def test_source_path_through_symlink_is_blocked(local_app, tmp_path: Path) -> None:
    created = _create_project(local_app)
    target = tmp_path / "target"
    target.mkdir()
    (target / "evidence.pdf").write_bytes(b"evidence")
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic-link creation is not permitted on this test host")

    with pytest.raises(ApplicationError) as raised:
        local_app.register_source(
            RegisterSourceRequest(
                project_id=created.project_id,
                database_path=created.database_path,
                source_path=(link / "evidence.pdf").absolute(),
                source_kind=SourceKind.FILE,
                actor="tester",
            )
        )

    assert raised.value.code == "SYMLINK_BLOCKED"


def test_registration_failure_rolls_back_state_catalog_lineage_and_events(
    tmp_path: Path,
) -> None:
    class DuplicateEventIdSequence(Sequence):
        def id(self) -> str:
            self._number += 1
            if self._number == 9:
                return "id-8"
            return f"id-{self._number}"

    ids = DuplicateEventIdSequence()
    app = create_local_application(
        (tmp_path / "workspace").absolute(),
        clock=Clock(),
        id_generator=ids.id,
    )
    created = _create_project(app)
    source_path = (tmp_path / "source.pdf").absolute()
    source_path.write_bytes(b"evidence")

    with pytest.raises(IntegrityError):
        app.register_source(
            RegisterSourceRequest(
                project_id=created.project_id,
                database_path=created.database_path,
                source_path=source_path,
                source_kind=SourceKind.FILE,
                actor="tester",
            )
        )

    overview = app.get_project_overview(
        GetProjectOverviewRequest(
            project_id=created.project_id,
            database_path=created.database_path,
        )
    )
    assert overview.project.status == ProjectStatus.CREATED
    assert overview.sources == ()
    assert [event.event_type for event in overview.events] == [
        EventType.PROJECT_CREATED
    ]


def test_failed_project_initialization_removes_only_staging_workspace(
    tmp_path: Path,
) -> None:
    class FailingDatabase(SqlAlchemyProjectDatabase):
        def migrate(self, database_path: Path) -> None:
            raise RuntimeError("migration failed")

    workspace_root = (tmp_path / "workspace").absolute()
    ids = Sequence()
    app = PigApplication(
        workspace=LocalWorkspaceManager(workspace_root),
        database=FailingDatabase(),
        source_inspector=LocalSourceInspector(clock=Clock()),
        clock=Clock(),
        id_generator=ids.id,
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        _create_project(app)

    assert list((workspace_root / "projects").iterdir()) == []
