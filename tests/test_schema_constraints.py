from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, StatementError

from pig.domain import entities, enums
from pig.domain.exceptions import InvariantViolationError
from tests.support import NOW, identifier, seed_complete_catalog


def test_project_database_accepts_only_one_project(uow_factory) -> None:
    with uow_factory() as uow:
        seeded = seed_complete_catalog(uow)
        uow.commit()

    second = replace(
        seeded["project"],
        id=identifier(),
        name="另一个项目",
        workspace_locator="projects/another-project",
    )
    with pytest.raises(IntegrityError):
        with uow_factory() as uow:
            uow.projects.add(second)


def test_source_accepted_fingerprint_cannot_be_rewritten(engine, uow_factory) -> None:
    with uow_factory() as uow:
        seeded = seed_complete_catalog(uow)
        uow.commit()

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE sources SET observed_sha256 = :hash WHERE id = :id"),
                {"hash": "f" * 64, "id": seeded["ids"]["source"]},
            )


def test_sha256_must_be_canonical_lowercase_hex(uow_factory) -> None:
    with uow_factory() as uow:
        seeded = seed_complete_catalog(uow)
        uow.commit()

    invalid_source = replace(
        seeded["source"],
        id=identifier(),
        display_name="invalid-hash.zip",
        locator="file:///external/invalid-hash.zip",
        observed_sha256="z" * 64,
    )
    with pytest.raises(IntegrityError):
        with uow_factory() as uow:
            uow.catalog.add_source(invalid_source)


@pytest.mark.parametrize("statement", ["UPDATE", "DELETE"])
def test_processing_events_are_append_only(
    statement: str, engine, uow_factory
) -> None:
    with uow_factory() as uow:
        seeded = seed_complete_catalog(uow)
        uow.commit()

    sql = (
        "UPDATE processing_events SET actor = 'changed' WHERE id = :id"
        if statement == "UPDATE"
        else "DELETE FROM processing_events WHERE id = :id"
    )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text(sql), {"id": seeded["ids"]["event"]})


def test_relationship_cannot_cross_sources(uow_factory) -> None:
    with uow_factory() as uow:
        seeded = seed_complete_catalog(uow)
        uow.commit()

    second_source = replace(
        seeded["source"],
        id=identifier(),
        display_name="第二来源",
        locator="file:///external/second.zip",
        observed_sha256="c" * 64,
    )
    other_root = replace(
        seeded["root"],
        id=identifier(),
        source_id=second_source.id,
        logical_path="/second.zip",
        discovery_key="source-root:second",
    )
    other_child = replace(
        seeded["child"],
        id=identifier(),
        source_id=second_source.id,
        logical_path="/second.zip!/报价.pdf",
        discovery_key="entry:0:other.pdf",
    )
    invalid_relationship = replace(
        seeded["relationship"],
        id=identifier(),
        child_node_id=other_child.id,
        discovery_key=other_child.discovery_key,
    )

    with pytest.raises(InvariantViolationError, match="cross sources"):
        with uow_factory() as uow:
            uow.catalog.add_source(second_source)
            uow.catalog.register_root(other_root)
            uow.catalog.register_child(other_child, invalid_relationship)


def test_node_has_at_most_one_active_attempt(uow_factory) -> None:
    with uow_factory() as uow:
        seeded = seed_complete_catalog(uow)
        uow.commit()

    second_attempt = replace(
        seeded["attempt"],
        id=identifier(),
        attempt_number=2,
        status=enums.AttemptStatus.QUEUED,
        started_at=None,
        finished_at=None,
    )
    with uow_factory() as uow:
        uow.processing.add_attempt(second_attempt)
        uow.commit()

    third_attempt = replace(second_attempt, id=identifier(), attempt_number=3)
    with pytest.raises(IntegrityError):
        with uow_factory() as uow:
            uow.processing.add_attempt(third_attempt)


def test_project_has_at_most_one_active_job(uow_factory) -> None:
    with uow_factory() as uow:
        seeded = seed_complete_catalog(uow)
        uow.commit()

    second_job = replace(
        seeded["job"],
        id=identifier(),
        status=enums.JobStatus.QUEUED,
        started_at=None,
        finished_at=None,
    )
    with pytest.raises(IntegrityError):
        with uow_factory() as uow:
            uow.processing.add_job(second_job)


def test_metadata_requires_exactly_one_value_column(uow_factory) -> None:
    with uow_factory() as uow:
        seeded = seed_complete_catalog(uow)
        uow.commit()

    invalid = entities.NodeMetadata(
        id=identifier(),
        project_id=seeded["ids"]["project"],
        node_id=seeded["ids"]["child"],
        namespace="invalid",
        key="wrong_type",
        value_type=enums.MetadataValueType.TEXT,
        value_integer=42,
        provenance="test",
        created_at=NOW,
    )
    with pytest.raises(IntegrityError):
        with uow_factory() as uow:
            uow.catalog.add_metadata(invalid)


def test_lineage_distance_zero_requires_same_node(engine, uow_factory) -> None:
    with uow_factory() as uow:
        seeded = seed_complete_catalog(uow)
        uow.commit()

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO node_lineage "
                    "(project_id, source_id, ancestor_node_id, descendant_node_id, distance) "
                    "VALUES (:project, :source, :ancestor, :descendant, 0)"
                ),
                {
                    "project": seeded["ids"]["project"],
                    "source": seeded["ids"]["source"],
                    "ancestor": seeded["ids"]["child"],
                    "descendant": seeded["ids"]["root"],
                },
            )


def test_naive_datetime_is_rejected_at_persistence_boundary(uow_factory) -> None:
    project = entities.Project(
        id=identifier(),
        name="无时区时间测试",
        status=enums.ProjectStatus.CREATED,
        workspace_locator="projects/naive-time",
        model_version="0.1",
        created_at=datetime(2026, 9, 13, 12, 0),
        updated_at=NOW,
    )

    with pytest.raises(StatementError, match="timezone-aware"):
        with uow_factory() as uow:
            uow.projects.add(project)
