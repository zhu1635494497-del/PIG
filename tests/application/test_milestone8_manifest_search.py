from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import pytest

from pig.application import (
    CreateProjectRequest,
    ExportManifestRequest,
    ProcessProjectRequest,
    RegisterSourceRequest,
    SearchNodesRequest,
)
from pig.application.errors import ApplicationError
from pig.bootstrap import create_local_application
from pig.domain.catalog_policy import CatalogPolicy
from pig.domain.enums import (
    EventType,
    NodeFormat,
    NodeKind,
    NodeProcessingStatus,
    RelationshipType,
    SourceKind,
)
from pig.infrastructure.database.provider import SqlAlchemyProjectDatabase


class Sequence:
    def __init__(self) -> None:
        self.number = 0

    def __call__(self) -> str:
        self.number += 1
        return f"m8-id-{self.number}"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 14, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(microseconds=1)
        return current


@pytest.fixture
def app(tmp_path: Path):
    return create_local_application(
        (tmp_path / "workspace").absolute(),
        clock=Clock(),
        id_generator=Sequence(),
    )


def _project(app):
    return app.create_project(CreateProjectRequest(name="M8", actor="tester"))


def _register_and_process(app, project, source_path: Path, kind: SourceKind):
    registered = app.register_source(
        RegisterSourceRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            source_path=source_path.absolute(),
            source_kind=kind,
            actor="tester",
        )
    )
    app.process_project(
        ProcessProjectRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            actor="tester",
        )
    )
    return registered


def test_search_nodes_supports_literal_text_filters_parent_and_pagination(
    app, tmp_path: Path
) -> None:
    source_path = tmp_path / "采购资料"
    source_path.mkdir()
    (source_path / "100%报价.xlsx").write_bytes(b"xlsx")
    (source_path / "100X报价.xlsx").write_bytes(b"xlsx")
    (source_path / "FINAL.txt").write_text("notes", encoding="utf-8")
    (source_path / "report.pdf").write_bytes(b"%PDF")
    project = _project(app)
    registered = _register_and_process(
        app, project, source_path, SourceKind.FOLDER
    )

    literal = app.search_nodes(
        SearchNodesRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            query="%",
        )
    )
    assert [hit.node.original_name for hit in literal.items] == ["100%报价.xlsx"]
    assert literal.items[0].parent_node_id == registered.root_node_id
    assert literal.items[0].relationship_type == RelationshipType.FOLDER_CONTAINS

    filtered = app.search_nodes(
        SearchNodesRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            query="报价",
            source_id=registered.source_id,
            kinds=(NodeKind.FILE,),
            formats=(NodeFormat.XLSX,),
            statuses=(NodeProcessingStatus.SUCCESS,),
        )
    )
    assert filtered.total == 2
    assert all(hit.node.format == NodeFormat.XLSX for hit in filtered.items)

    first_page = app.search_nodes(
        SearchNodesRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            limit=2,
        )
    )
    second_page = app.search_nodes(
        SearchNodesRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            limit=2,
            offset=2,
        )
    )
    assert first_page.total == 5
    assert first_page.has_more is True
    assert {hit.node.id for hit in first_page.items}.isdisjoint(
        hit.node.id for hit in second_page.items
    )
    assert [hit.node.logical_path for hit in first_page.items] == sorted(
        hit.node.logical_path for hit in first_page.items
    )

    case_insensitive = app.search_nodes(
        SearchNodesRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            query="final",
        )
    )
    assert [hit.node.original_name for hit in case_insensitive.items] == ["FINAL.txt"]


def test_search_is_read_only_and_validates_bounds(app, tmp_path: Path) -> None:
    source_path = tmp_path / "one.txt"
    source_path.write_text("one", encoding="utf-8")
    project = _project(app)
    _register_and_process(app, project, source_path, SourceKind.FILE)
    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        before = len(uow.processing.events_for_project(project.project_id))

    result = app.search_nodes(
        SearchNodesRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            query="one",
        )
    )

    assert result.total == 1
    with database.unit_of_work(project.database_path) as uow:
        after = len(uow.processing.events_for_project(project.project_id))
    assert after == before
    with pytest.raises(ApplicationError) as too_many:
        app.search_nodes(
            SearchNodesRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                limit=201,
            )
        )
    assert too_many.value.code == "INVALID_REQUEST"
    with pytest.raises(ApplicationError):
        app.search_nodes(
            SearchNodesRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                query="x" * 257,
            )
        )


def _email_source(path: Path) -> bytes:
    message = EmailMessage()
    message["Subject"] = "供应商最终报价"
    message["From"] = "buyer@example.com"
    message["To"] = "audit@example.com"
    message.set_content("body is not indexed")
    message.add_attachment(
        b"PK\x03\x04workbook",
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="最终报价.xlsx",
    )
    payload = message.as_bytes()
    path.write_bytes(payload)
    return payload


def test_manifest_exports_complete_snapshot_and_preserves_history(
    app, tmp_path: Path
) -> None:
    source_path = tmp_path / "报价邮件.eml"
    original = _email_source(source_path)
    project = _project(app)
    _register_and_process(app, project, source_path, SourceKind.FILE)

    metadata_search = app.search_nodes(
        SearchNodesRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            query="供应商",
        )
    )
    assert metadata_search.total == 1
    assert metadata_search.items[0].node.format == NodeFormat.EML

    first = app.export_manifest(
        ExportManifestRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            actor="auditor",
        )
    )

    assert source_path.read_bytes() == original
    assert first.storage_key == f"manifests/{first.manifest_id}.json"
    assert first.manifest_path.read_bytes()
    assert hashlib.sha256(first.manifest_path.read_bytes()).hexdigest() == first.sha256
    assert first.manifest_path.stat().st_size == first.size
    assert not (project.workspace_path / "manifests" / ".staging").exists()
    document = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert document["schema_name"] == "pig.project-manifest"
    assert document["schema_version"] == "1.0"
    assert document["manifest_id"] == first.manifest_id
    assert document["project"]["id"] == project.project_id
    assert document["counts"]["sources"] == 1
    assert document["counts"]["nodes"] == 2
    assert document["counts"]["artifacts"] == 2
    assert document["counts"]["relationships"] == 1
    assert document["counts"]["lineage_records"] == 3
    assert any(item["key"] == "subject" for item in document["metadata"])
    assert document["relationships"][0]["type"] == "EMAIL_ATTACHMENT"
    assert any(item["distance"] == 1 for item in document["lineage"])
    assert document["processing"]["jobs"]
    assert document["processing"]["attempts"]
    included_events = document["processing"]["events"]
    assert any(
        item["event_type"] == "MANIFEST_EXPORT_REQUESTED"
        for item in included_events
    )
    assert all(
        item["event_type"] != "MANIFEST_EXPORTED" for item in included_events
    )
    assert first.included_event_count == len(included_events)
    assert first.last_included_event_id == included_events[-1]["id"]

    database = SqlAlchemyProjectDatabase()
    with database.unit_of_work(project.database_path) as uow:
        events = tuple(uow.processing.events_for_project(project.project_id))
    manifest_events = tuple(
        event
        for event in events
        if event.details.get("manifest_id") == first.manifest_id
    )
    assert [event.event_type for event in manifest_events] == [
        EventType.MANIFEST_EXPORT_REQUESTED,
        EventType.MANIFEST_EXPORTED,
    ]
    assert manifest_events[-1].details["sha256"] == first.sha256

    second = app.export_manifest(
        ExportManifestRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            actor="auditor",
        )
    )
    assert second.manifest_path != first.manifest_path
    assert first.manifest_path.exists()
    assert second.manifest_path.exists()


def test_manifest_limit_records_failure_and_leaves_no_output(tmp_path: Path) -> None:
    app = create_local_application(
        (tmp_path / "workspace").absolute(),
        clock=Clock(),
        id_generator=Sequence(),
        catalog_policy=CatalogPolicy(max_manifest_size=10),
    )
    project = _project(app)

    with pytest.raises(ApplicationError) as raised:
        app.export_manifest(
            ExportManifestRequest(
                project_id=project.project_id,
                database_path=project.database_path,
                actor="auditor",
            )
        )

    assert raised.value.code == "MANIFEST_SIZE_EXCEEDED"
    assert not (project.workspace_path / "manifests").exists()
    with SqlAlchemyProjectDatabase().unit_of_work(project.database_path) as uow:
        events = tuple(uow.processing.events_for_project(project.project_id))
    manifest_events = tuple(
        event for event in events if "manifest_id" in event.details
    )
    assert [event.event_type for event in manifest_events] == [
        EventType.MANIFEST_EXPORT_REQUESTED,
        EventType.MANIFEST_EXPORT_FAILED,
    ]
    assert manifest_events[-1].details["failure_code"] == "MANIFEST_SIZE_EXCEEDED"
    assert manifest_events[-1].error_code.value == "MANIFEST_SIZE_EXCEEDED"
