from __future__ import annotations

import json

from pig.diagnostics.packaged_flow import run_packaged_flow


def test_workbench_packaged_flow_reports_current_closed_loop(tmp_path) -> None:
    report_path = run_packaged_flow((tmp_path / "acceptance").absolute())

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema"] == "pig.workbench-packaged-flow"
    assert report["status"] == "PASS"
    assert report["workspace_item_count"] >= 5
    assert report["recovery_item_count"] >= 1
