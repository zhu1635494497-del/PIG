from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from pig.domain.entities import (
    Artifact,
    LineageRecord,
    Node,
    NodeMetadata,
    NodeRelationship,
    ProcessingAttempt,
    ProcessingEvent,
    ProcessingJob,
    Project,
    Source,
)
from pig.domain.enums import MetadataValueType


MANIFEST_SCHEMA_NAME = "pig.project-manifest"
MANIFEST_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestDocument:
    payload: bytes
    included_event_count: int
    last_included_event_id: str | None


def build_manifest_document(
    *,
    manifest_id: str,
    generated_at: datetime,
    project: Project,
    sources: Sequence[Source],
    nodes: Sequence[Node],
    artifacts: Sequence[Artifact],
    relationships: Sequence[NodeRelationship],
    lineage: Sequence[LineageRecord],
    metadata: Sequence[NodeMetadata],
    jobs: Sequence[ProcessingJob],
    attempts: Sequence[ProcessingAttempt],
    events: Sequence[ProcessingEvent],
) -> ManifestDocument:
    event_count = len(events)
    last_event_id = events[-1].id if events else None
    document = {
        "schema_name": MANIFEST_SCHEMA_NAME,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_id": manifest_id,
        "generated_at": _time(generated_at),
        "event_snapshot": {
            "included_event_count": event_count,
            "last_included_event_id": last_event_id,
        },
        "counts": {
            "sources": len(sources),
            "nodes": len(nodes),
            "artifacts": len(artifacts),
            "relationships": len(relationships),
            "lineage_records": len(lineage),
            "metadata_records": len(metadata),
            "processing_jobs": len(jobs),
            "processing_attempts": len(attempts),
            "processing_events": event_count,
        },
        "project": _project(project),
        "sources": [_source(item) for item in sources],
        "nodes": [_node(item) for item in nodes],
        "artifacts": [_artifact(item) for item in artifacts],
        "relationships": [_relationship(item) for item in relationships],
        "lineage": [_lineage(item) for item in lineage],
        "metadata": [_metadata(item) for item in metadata],
        "processing": {
            "jobs": [_job(item) for item in jobs],
            "attempts": [_attempt(item) for item in attempts],
            "events": [_event(item) for item in events],
        },
    }
    payload = (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    return ManifestDocument(
        payload=payload,
        included_event_count=event_count,
        last_included_event_id=last_event_id,
    )


def _time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("manifest timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _time(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _project(value: Project) -> dict[str, Any]:
    return {
        "id": value.id,
        "name": value.name,
        "description": value.description,
        "status": value.status.value,
        "workspace_locator": value.workspace_locator,
        "model_version": value.model_version,
        "created_at": _time(value.created_at),
        "updated_at": _time(value.updated_at),
    }


def _source(value: Source) -> dict[str, Any]:
    return {
        "id": value.id,
        "project_id": value.project_id,
        "kind": value.kind.value,
        "display_name": value.display_name,
        "locator": value.locator,
        "path_flavor": value.path_flavor.value,
        "status": value.status.value,
        "root_node_id": value.root_node_id,
        "registered_at": _time(value.registered_at),
        "last_verified_at": _time(value.last_verified_at),
        "observed_size": value.observed_size,
        "observed_sha256": value.observed_sha256,
        "observed_modified_at": _time(value.observed_modified_at),
    }


def _node(value: Node) -> dict[str, Any]:
    return {
        "id": value.id,
        "project_id": value.project_id,
        "source_id": value.source_id,
        "kind": value.kind.value,
        "format": value.format.value,
        "original_name": value.original_name,
        "display_name": value.display_name,
        "logical_path": value.logical_path,
        "depth": value.depth,
        "media_type": value.media_type,
        "declared_size": value.declared_size,
        "status": value.status.value,
        "detection_method": value.detection_method,
        "detection_confidence": value.detection_confidence,
        "detection_details": _json_value(value.detection_details),
        "discovery_key": value.discovery_key,
        "created_at": _time(value.created_at),
        "updated_at": _time(value.updated_at),
    }


def _artifact(value: Artifact) -> dict[str, Any]:
    return {
        "id": value.id,
        "project_id": value.project_id,
        "node_id": value.node_id,
        "role": value.role.value,
        "scope": value.scope.value,
        "locator": value.locator,
        "size": value.size,
        "sha256": value.sha256,
        "integrity_status": value.integrity_status.value,
        "observed_at": _time(value.observed_at),
        "created_at": _time(value.created_at),
    }


def _relationship(value: NodeRelationship) -> dict[str, Any]:
    return {
        "id": value.id,
        "project_id": value.project_id,
        "parent_node_id": value.parent_node_id,
        "child_node_id": value.child_node_id,
        "type": value.type.value,
        "ordinal": value.ordinal,
        "discovery_key": value.discovery_key,
        "created_by_job_id": value.created_by_job_id,
        "created_at": _time(value.created_at),
    }


def _lineage(value: LineageRecord) -> dict[str, Any]:
    return {
        "project_id": value.project_id,
        "ancestor_node_id": value.ancestor_node_id,
        "descendant_node_id": value.descendant_node_id,
        "distance": value.distance,
    }


def _metadata(value: NodeMetadata) -> dict[str, Any]:
    typed_values = {
        MetadataValueType.TEXT: value.value_text,
        MetadataValueType.INTEGER: value.value_integer,
        MetadataValueType.REAL: value.value_real,
        MetadataValueType.BOOLEAN: value.value_boolean,
        MetadataValueType.DATETIME: value.value_datetime,
        MetadataValueType.JSON: value.value_json,
    }
    return {
        "id": value.id,
        "project_id": value.project_id,
        "node_id": value.node_id,
        "namespace": value.namespace,
        "key": value.key,
        "value_type": value.value_type.value,
        "value": _json_value(typed_values[value.value_type]),
        "provenance": value.provenance,
        "observed_at": _time(value.observed_at),
        "created_at": _time(value.created_at),
    }


def _job(value: ProcessingJob) -> dict[str, Any]:
    return {
        "id": value.id,
        "project_id": value.project_id,
        "type": value.type.value,
        "status": value.status.value,
        "requested_by": value.requested_by,
        "policy_snapshot": _json_value(value.policy_snapshot),
        "created_at": _time(value.created_at),
        "started_at": _time(value.started_at),
        "finished_at": _time(value.finished_at),
        "warning_count": value.warning_count,
        "error_count": value.error_count,
    }


def _attempt(value: ProcessingAttempt) -> dict[str, Any]:
    error = value.error
    return {
        "id": value.id,
        "project_id": value.project_id,
        "job_id": value.job_id,
        "node_id": value.node_id,
        "attempt_number": value.attempt_number,
        "status": value.status.value,
        "stage": value.stage.value,
        "handler_name": value.handler_name,
        "handler_version": value.handler_version,
        "backend_name": value.backend_name,
        "backend_version": value.backend_version,
        "backend_sha256": value.backend_sha256,
        "queued_at": _time(value.queued_at),
        "started_at": _time(value.started_at),
        "finished_at": _time(value.finished_at),
        "error": None
        if error is None
        else {
            "code": error.code.value,
            "category": error.category.value,
            "stage": error.stage.value,
            "message": error.message,
            "retryable": error.retryable,
            "technical_reference": error.technical_reference,
        },
    }


def _event(value: ProcessingEvent) -> dict[str, Any]:
    return {
        "id": value.id,
        "event_type": value.event_type.value,
        "project_id": value.project_id,
        "source_id": value.source_id,
        "node_id": value.node_id,
        "job_id": value.job_id,
        "attempt_id": value.attempt_id,
        "actor": value.actor,
        "occurred_at": _time(value.occurred_at),
        "severity": value.severity.value,
        "previous_status": value.previous_status,
        "new_status": value.new_status,
        "error_code": None if value.error_code is None else value.error_code.value,
        "details": _json_value(value.details),
        "correlation_id": value.correlation_id,
    }
