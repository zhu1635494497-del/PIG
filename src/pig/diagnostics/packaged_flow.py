from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from pig.application import (
    AddWorkspaceInputsRequest,
    CreateProjectRequest,
    ExportWorkspaceItemsRequest,
    GetWorkspaceTreeRequest,
    InspectProjectRecoveryRequest,
    LoadProjectRequest,
    RecoverWorkbenchProjectRequest,
)
from pig.application.contracts import MaterializeWorkspaceItemRequest
from pig.bootstrap import create_local_application
from pig.domain.enums import RecoveryRunStatus, WorkspaceExportKind


def _tree(application, project):
    return application.get_workspace_tree(
        GetWorkspaceTreeRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )


def run_packaged_flow(output_root: Path) -> Path:
    """Exercise the current Workbench closed loop in a packaged runtime."""
    root = Path(output_root)
    if not root.is_absolute() or root.is_symlink():
        raise ValueError("acceptance output root must be absolute and non-symlink")
    root.mkdir(parents=True, exist_ok=True)
    run = root / str(uuid4())
    run.mkdir()

    source = run / "source" / "交付资料"
    nested = source / "报价" / "最终"
    nested.mkdir(parents=True)
    (source / "空文件夹").mkdir()
    original_file = nested / "最终报价.txt"
    original_file.write_bytes(b"original quotation")
    original_hash = hashlib.sha256(original_file.read_bytes()).hexdigest()

    application = create_local_application(run / "projects")
    project = application.create_project(
        CreateProjectRequest(name="Packaged Workbench W8", actor="packaging")
    )
    added = application.add_workspace_inputs(
        AddWorkspaceInputsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            input_paths=(source,),
            actor="packaging",
            expected_workspace_revision=0,
            idempotency_key="packaged-workbench-flow",
        )
    )
    tree = _tree(application, project)
    root_item = next(
        value
        for value in tree.items
        if value.item.display_name == "交付资料"
        and value.placement.parent_workspace_item_id is None
    )
    file_item = next(
        value for value in tree.items if value.item.display_name == "最终报价.txt"
    )
    materialized = application.materialize_workspace_item(
        MaterializeWorkspaceItemRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_id=file_item.item.id,
            actor="packaging",
        )
    )
    materialized.path.write_bytes(b"approved quotation")

    delivery_parent = run / "delivery"
    delivery_parent.mkdir()
    delivery = delivery_parent / "交付资料"
    exported = application.export_workspace_items(
        ExportWorkspaceItemsRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            workspace_item_ids=(root_item.item.id,),
            destination_path=delivery,
            actor="packaging",
        )
    )
    delivered_file = delivery / "报价" / "最终" / "最终报价.txt"
    if exported.export_kind != WorkspaceExportKind.DIRECTORY:
        raise AssertionError("Workbench folder export did not create a directory")
    if delivered_file.read_bytes() != b"approved quotation":
        raise AssertionError("Workbench export did not use current Working bytes")
    if not (delivery / "空文件夹").is_dir():
        raise AssertionError("Workbench export did not preserve empty folders")
    if hashlib.sha256(original_file.read_bytes()).hexdigest() != original_hash:
        raise AssertionError("external source changed during packaged acceptance")

    residue = project.workspace_path / ".inspection" / "interrupted" / "objects"
    residue.mkdir(parents=True)
    (residue / "content").write_bytes(b"reproducible cache")
    inspection = application.inspect_project_recovery(
        InspectProjectRecoveryRequest(
            project_id=project.project_id,
            database_path=project.database_path,
        )
    )
    if not inspection.recovery_required:
        raise AssertionError("Workbench recovery did not detect staged residue")
    recovered = application.recover_workbench_project(
        RecoverWorkbenchProjectRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            actor="packaging",
            inspection_token=inspection.inspection_token,
            confirmed=True,
        )
    )
    if recovered.recovery_run.status != RecoveryRunStatus.SUCCESS:
        raise AssertionError("Workbench recovery did not finish successfully")
    if recovered.remaining_candidate_count != 0 or residue.exists():
        raise AssertionError("Workbench recovery left recoverable residue")
    loaded = application.load_project(
        LoadProjectRequest(database_path=project.database_path)
    )
    if loaded.project.id != project.project_id:
        raise AssertionError("packaged Workbench Project could not be reloaded")

    report = {
        "schema": "pig.workbench-packaged-flow",
        "version": "1.0",
        "status": "PASS",
        "scope": (
            "packaged Workbench runtime on the current Windows host; "
            "not clean-VM or manual GUI evidence"
        ),
        "run_directory": str(run),
        "project_id": project.project_id,
        "project_database": str(project.database_path),
        "workspace_revision": added.workspace_revision,
        "workspace_item_count": len(tree.items),
        "materialized_path": str(materialized.path),
        "delivery_path": str(delivery),
        "delivery_sha256": hashlib.sha256(delivered_file.read_bytes()).hexdigest(),
        "external_source_sha256": original_hash,
        "recovery_run_id": recovered.recovery_run.id,
        "recovery_item_count": len(recovered.recovery_items),
    }
    path = run / "workbench-acceptance-report.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
