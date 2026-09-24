from __future__ import annotations

from dataclasses import replace
from datetime import timezone

from pig.domain import enums
from tests.support import NOW, identifier, seed_complete_catalog


def test_repository_round_trip_preserves_catalog_and_lineage(uow_factory) -> None:
    with uow_factory() as uow:
        seeded = seed_complete_catalog(uow)
        uow.commit()

    ids = seeded["ids"]
    with uow_factory() as uow:
        project = uow.projects.get(ids["project"])
        source = uow.catalog.get_source(ids["source"])
        root = uow.catalog.get_node(ids["root"])
        children = uow.catalog.children_of(ids["root"])
        relationship = uow.catalog.relationship_for_child(ids["child"])
        artifacts = uow.catalog.artifacts_for_node(ids["child"])
        lineage = uow.catalog.lineage_for(ids["child"])
        metadata = uow.catalog.metadata_for_node(ids["child"])
        job = uow.processing.get_job(ids["job"])
        attempt = uow.processing.get_attempt(ids["attempt"])
        events = uow.processing.events_for_project(ids["project"])

    assert project == seeded["project"]
    assert source is not None and source.root_node_id == ids["root"]
    assert source.observed_sha256 == "a" * 64
    assert source.registered_at.tzinfo == timezone.utc
    assert root == seeded["root"]
    assert children == [seeded["child"]]
    assert relationship == seeded["relationship"]
    assert artifacts == [seeded["child_artifact"]]
    assert [(item.ancestor_node_id, item.distance) for item in lineage] == [
        (ids["root"], 1),
        (ids["child"], 0),
    ]
    assert metadata == [seeded["metadata"]]
    assert job == seeded["job"]
    assert attempt == seeded["attempt"]
    assert events == [seeded["event"]]


def test_unit_of_work_rolls_back_without_explicit_commit(uow_factory) -> None:
    with uow_factory() as uow:
        seeded = seed_complete_catalog(uow)

    with uow_factory() as uow:
        assert uow.projects.get(seeded["ids"]["project"]) is None


def test_register_child_builds_complete_ancestor_closure(uow_factory) -> None:
    with uow_factory() as uow:
        seeded = seed_complete_catalog(uow)
        uow.commit()

    grandchild = replace(
        seeded["child"],
        id=identifier(),
        format=enums.NodeFormat.XLSX,
        original_name="最终报价.xlsx",
        display_name="最终报价.xlsx",
        logical_path="/采购资料.zip!/供应商报价.eml!/最终报价.xlsx",
        depth=2,
        discovery_key="attachment:0:最终报价.xlsx",
    )
    relationship = replace(
        seeded["relationship"],
        id=identifier(),
        parent_node_id=seeded["ids"]["child"],
        child_node_id=grandchild.id,
        type=enums.RelationshipType.EMAIL_ATTACHMENT,
        discovery_key=grandchild.discovery_key,
    )

    with uow_factory() as uow:
        uow.catalog.register_child(grandchild, relationship)
        uow.commit()

    with uow_factory() as uow:
        lineage = uow.catalog.lineage_for(grandchild.id)

    assert [(item.ancestor_node_id, item.distance) for item in lineage] == [
        (seeded["ids"]["root"], 2),
        (seeded["ids"]["child"], 1),
        (grandchild.id, 0),
    ]
