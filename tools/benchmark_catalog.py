from __future__ import annotations

import argparse
import json
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psutil
from sqlalchemy import insert, update

from pig.application import (
    CreateProjectRequest,
    ExportManifestRequest,
    GetProjectTreeRequest,
    SearchNodesRequest,
)
from pig.bootstrap import create_local_application
from pig.domain import enums
from pig.infrastructure.database.engine import create_project_engine
from pig.infrastructure.database.models import (
    LineageRecordModel,
    NodeMetadataModel,
    NodeModel,
    NodeRelationshipModel,
    ProcessingJobModel,
    ProjectModel,
    SourceModel,
    SourceRootModel,
)


def _id(namespace: uuid.UUID, value: str) -> str:
    return str(uuid.uuid5(namespace, value))


def _chunks(items: list[dict[str, object]], size: int = 1_000):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _seed(database_path: Path, project_id: str, node_count: int) -> None:
    """Create a deterministic catalog-only fixture outside product code paths."""
    now = datetime.now(timezone.utc)
    namespace = uuid.UUID(project_id)
    source_id = _id(namespace, "source")
    root_id = _id(namespace, "node:0")
    job_id = _id(namespace, "job")
    engine = create_project_engine(database_path)
    nodes: list[dict[str, object]] = [
        {
            "id": root_id,
            "project_id": project_id,
            "source_id": source_id,
            "kind": enums.NodeKind.CONTAINER,
            "format": enums.NodeFormat.FOLDER,
            "original_name": "benchmark",
            "display_name": "benchmark",
            "logical_path": "/benchmark",
            "depth": 0,
            "media_type": None,
            "declared_size": None,
            "status": enums.NodeProcessingStatus.SUCCESS,
            "detection_method": "benchmark-fixture",
            "detection_confidence": 1.0,
            "detection_details": {},
            "discovery_key": "source-root",
            "created_at": now,
            "updated_at": now,
        }
    ]
    relationships: list[dict[str, object]] = []
    lineage: list[dict[str, object]] = [
        {
            "project_id": project_id,
            "source_id": source_id,
            "ancestor_node_id": root_id,
            "descendant_node_id": root_id,
            "distance": 0,
        }
    ]
    metadata: list[dict[str, object]] = []
    for index in range(1, node_count):
        node_id = _id(namespace, f"node:{index}")
        name = f"target-{index:05d}.txt"
        nodes.append(
            {
                "id": node_id,
                "project_id": project_id,
                "source_id": source_id,
                "kind": enums.NodeKind.FILE,
                "format": enums.NodeFormat.TXT,
                "original_name": name,
                "display_name": name,
                "logical_path": f"/benchmark/{name}",
                "depth": 1,
                "media_type": "text/plain",
                "declared_size": index % 4096,
                "status": enums.NodeProcessingStatus.SUCCESS,
                "detection_method": "benchmark-fixture",
                "detection_confidence": 1.0,
                "detection_details": {},
                "discovery_key": f"entry:{index}",
                "created_at": now,
                "updated_at": now,
            }
        )
        relationships.append(
            {
                "id": _id(namespace, f"relationship:{index}"),
                "project_id": project_id,
                "source_id": source_id,
                "parent_node_id": root_id,
                "child_node_id": node_id,
                "type": enums.RelationshipType.FOLDER_CONTAINS,
                "ordinal": index - 1,
                "discovery_key": f"entry:{index}",
                "created_by_job_id": job_id,
                "created_at": now,
            }
        )
        lineage.extend(
            (
                {
                    "project_id": project_id,
                    "source_id": source_id,
                    "ancestor_node_id": node_id,
                    "descendant_node_id": node_id,
                    "distance": 0,
                },
                {
                    "project_id": project_id,
                    "source_id": source_id,
                    "ancestor_node_id": root_id,
                    "descendant_node_id": node_id,
                    "distance": 1,
                },
            )
        )
        metadata.append(
            {
                "id": _id(namespace, f"metadata:{index}"),
                "project_id": project_id,
                "node_id": node_id,
                "namespace": "benchmark",
                "key": "label",
                "value_type": enums.MetadataValueType.TEXT,
                "value_text": f"catalog fixture {index:05d}",
                "value_integer": None,
                "value_real": None,
                "value_boolean": None,
                "value_datetime": None,
                "value_json": None,
                "provenance": "tools/benchmark_catalog.py",
                "observed_at": now,
                "created_at": now,
            }
        )

    with engine.begin() as connection:
        connection.execute(
            update(ProjectModel)
            .where(ProjectModel.id == project_id)
            .values(status=enums.ProjectStatus.READY, updated_at=now)
        )
        connection.execute(
            insert(SourceModel),
            [{
                "id": source_id,
                "project_id": project_id,
                "kind": enums.SourceKind.FOLDER,
                "display_name": "benchmark",
                "locator": "benchmark://catalog-fixture",
                "path_flavor": enums.PathFlavor.URI,
                "status": enums.SourceStatus.AVAILABLE,
                "registered_at": now,
                "last_verified_at": now,
                "observed_size": None,
                "observed_sha256": None,
                "observed_modified_at": now,
            }],
        )
        connection.execute(
            insert(ProcessingJobModel),
            [{
                "id": job_id,
                "project_id": project_id,
                "type": enums.JobType.PROCESS_PROJECT,
                "status": enums.JobStatus.SUCCESS,
                "requested_by": "benchmark",
                "policy_snapshot": {"fixture": True},
                "created_at": now,
                "started_at": now,
                "finished_at": now,
                "warning_count": 0,
                "error_count": 0,
            }],
        )
        for chunk in _chunks(nodes):
            connection.execute(insert(NodeModel), chunk)
        connection.execute(
            insert(SourceRootModel),
            [{"source_id": source_id, "project_id": project_id, "node_id": root_id}],
        )
        for model, rows in (
            (NodeRelationshipModel, relationships),
            (LineageRecordModel, lineage),
            (NodeMetadataModel, metadata),
        ):
            for chunk in _chunks(rows):
                connection.execute(insert(model), chunk)
    engine.dispose()


def _measure(action):
    process = psutil.Process()
    before = process.memory_info().rss
    started = time.perf_counter()
    value = action()
    elapsed = time.perf_counter() - started
    after = process.memory_info().rss
    return value, round(elapsed, 4), max(0, after - before)


def run(workspace_root: Path, node_count: int) -> dict[str, object]:
    application = create_local_application(workspace_root)
    created = application.create_project(
        CreateProjectRequest(name="10k catalog benchmark", actor="benchmark")
    )
    _seed(created.database_path, created.project_id, node_count)
    tree, tree_seconds, tree_memory = _measure(
        lambda: application.get_project_tree(
            GetProjectTreeRequest(
                project_id=created.project_id,
                database_path=created.database_path,
            )
        )
    )
    search, search_seconds, search_memory = _measure(
        lambda: application.search_nodes(
            SearchNodesRequest(
                project_id=created.project_id,
                database_path=created.database_path,
                query=f"target-{node_count - 1:05d}",
                limit=20,
            )
        )
    )
    manifest, manifest_seconds, manifest_memory = _measure(
        lambda: application.export_manifest(
            ExportManifestRequest(
                project_id=created.project_id,
                database_path=created.database_path,
                actor="benchmark",
            )
        )
    )
    return {
        "schema": "pig.catalog-performance-baseline",
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": {"logical_cpu_count": psutil.cpu_count(), "python": __import__("sys").version},
        "fixture": {"nodes": node_count, "metadata_records": node_count - 1},
        "results": {
            "load_tree": {
                "seconds": tree_seconds,
                "items": len(tree.items),
                "rss_delta_bytes": tree_memory,
            },
            "search_exact_name": {
                "seconds": search_seconds,
                "matches": search.total,
                "rss_delta_bytes": search_memory,
            },
            "export_manifest": {
                "seconds": manifest_seconds,
                "bytes": manifest.size,
                "rss_delta_bytes": manifest_memory,
            },
        },
        "interpretation": "Measured baseline, not a universal service-level guarantee.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark PIG V1 catalog operations")
    parser.add_argument("--nodes", type=int, default=10_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.nodes < 2:
        parser.error("--nodes must be at least 2")
    with tempfile.TemporaryDirectory(prefix="pig-benchmark-") as directory:
        result = run(Path(directory), args.nodes)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
