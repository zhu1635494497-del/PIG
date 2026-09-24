from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pig.domain import entities, enums


NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def identifier() -> str:
    return str(uuid4())


def seed_complete_catalog(uow: Any) -> dict[str, Any]:
    ids = {
        name: identifier()
        for name in (
            "project",
            "source",
            "job",
            "root",
            "child",
            "root_artifact",
            "child_artifact",
            "relationship",
            "metadata",
            "attempt",
            "event",
            "correlation",
        )
    }

    project = entities.Project(
        id=ids["project"],
        name="采购项目",
        description="Milestone 2 repository test",
        status=enums.ProjectStatus.PROCESSING,
        workspace_locator="projects/test-project",
        model_version="0.1",
        created_at=NOW,
        updated_at=NOW,
    )
    source = entities.Source(
        id=ids["source"],
        project_id=project.id,
        kind=enums.SourceKind.FILE,
        display_name="采购资料.zip",
        locator="file:///external/采购资料.zip",
        path_flavor=enums.PathFlavor.URI,
        status=enums.SourceStatus.AVAILABLE,
        registered_at=NOW,
        last_verified_at=NOW,
        observed_size=4096,
        observed_sha256="a" * 64,
        observed_modified_at=NOW,
    )
    job = entities.ProcessingJob(
        id=ids["job"],
        project_id=project.id,
        type=enums.JobType.PROCESS_PROJECT,
        status=enums.JobStatus.RUNNING,
        requested_by="test-user",
        policy_snapshot={"max_depth": 10, "allow_symlinks": False},
        created_at=NOW,
        started_at=NOW,
    )
    root = entities.Node(
        id=ids["root"],
        project_id=project.id,
        source_id=source.id,
        kind=enums.NodeKind.CONTAINER,
        format=enums.NodeFormat.ZIP,
        original_name="采购资料.zip",
        display_name="采购资料.zip",
        logical_path="/采购资料.zip",
        depth=0,
        status=enums.NodeProcessingStatus.PROCESSING,
        discovery_key="source-root",
        created_at=NOW,
        updated_at=NOW,
        media_type="application/zip",
        declared_size=4096,
        detection_method="fixture",
        detection_confidence=1.0,
        detection_details={"signature": "zip"},
    )
    child = entities.Node(
        id=ids["child"],
        project_id=project.id,
        source_id=source.id,
        kind=enums.NodeKind.CONTAINER,
        format=enums.NodeFormat.EML,
        original_name="供应商报价.eml",
        display_name="供应商报价.eml",
        logical_path="/采购资料.zip!/供应商报价.eml",
        depth=1,
        status=enums.NodeProcessingStatus.SUCCESS,
        discovery_key="entry:0:供应商报价.eml",
        created_at=NOW,
        updated_at=NOW,
        media_type="message/rfc822",
        declared_size=1024,
        detection_method="fixture",
        detection_confidence=1.0,
    )
    root_artifact = entities.Artifact(
        id=ids["root_artifact"],
        project_id=project.id,
        node_id=root.id,
        role=enums.ArtifactRole.ORIGINAL_REFERENCE,
        scope=enums.ArtifactScope.EXTERNAL_SOURCE,
        locator=source.locator,
        size=4096,
        sha256="a" * 64,
        integrity_status=enums.ArtifactIntegrityStatus.VERIFIED,
        observed_at=NOW,
        created_at=NOW,
    )
    child_artifact = entities.Artifact(
        id=ids["child_artifact"],
        project_id=project.id,
        node_id=child.id,
        role=enums.ArtifactRole.EXTRACTED_ARTIFACT,
        scope=enums.ArtifactScope.PROJECT_WORKSPACE,
        locator=f"extracted/{child.id}/payload.bin",
        size=1024,
        sha256="b" * 64,
        integrity_status=enums.ArtifactIntegrityStatus.VERIFIED,
        observed_at=NOW,
        created_at=NOW,
    )
    relationship = entities.NodeRelationship(
        id=ids["relationship"],
        project_id=project.id,
        parent_node_id=root.id,
        child_node_id=child.id,
        type=enums.RelationshipType.ARCHIVE_ENTRY,
        ordinal=0,
        discovery_key=child.discovery_key,
        created_by_job_id=job.id,
        created_at=NOW,
    )
    metadata = entities.NodeMetadata(
        id=ids["metadata"],
        project_id=project.id,
        node_id=child.id,
        namespace="archive",
        key="entry_name",
        value_type=enums.MetadataValueType.TEXT,
        value_text="供应商报价.eml",
        provenance="zip-index",
        observed_at=NOW,
        created_at=NOW,
    )
    attempt = entities.ProcessingAttempt(
        id=ids["attempt"],
        project_id=project.id,
        job_id=job.id,
        node_id=root.id,
        attempt_number=1,
        status=enums.AttemptStatus.COMPLETED,
        stage=enums.ProcessingStage.INSPECT_CONTAINER,
        handler_name="zip",
        handler_version="1",
        queued_at=NOW,
        started_at=NOW,
        finished_at=NOW,
    )
    event = entities.ProcessingEvent(
        id=ids["event"],
        event_type=enums.EventType.CHILD_DISCOVERED,
        project_id=project.id,
        source_id=source.id,
        node_id=child.id,
        job_id=job.id,
        attempt_id=attempt.id,
        actor="system",
        occurred_at=NOW,
        severity=enums.EventSeverity.INFO,
        previous_status=None,
        new_status=enums.NodeProcessingStatus.DISCOVERED.value,
        details={"ordinal": 0},
        correlation_id=ids["correlation"],
    )

    uow.projects.add(project)
    uow.catalog.add_source(source)
    uow.processing.add_job(job)
    uow.catalog.register_root(root)
    uow.catalog.register_child(child, relationship)
    uow.catalog.add_artifact(root_artifact)
    uow.catalog.add_artifact(child_artifact)
    uow.catalog.add_metadata(metadata)
    uow.processing.add_attempt(attempt)
    uow.processing.append_event(event)

    return {
        "ids": ids,
        "project": project,
        "source": source,
        "job": job,
        "root": root,
        "child": child,
        "root_artifact": root_artifact,
        "child_artifact": child_artifact,
        "relationship": relationship,
        "metadata": metadata,
        "attempt": attempt,
        "event": event,
    }
