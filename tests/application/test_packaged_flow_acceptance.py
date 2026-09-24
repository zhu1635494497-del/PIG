from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pig.diagnostics.packaged_flow import run_packaged_flow


def test_packaged_flow_diagnostic_preserves_source_and_reports_closed_loop(
    tmp_path: Path,
) -> None:
    report_path = run_packaged_flow((tmp_path / "acceptance").absolute())
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["status"] == "PASS"
    assert report["tree_node_count"] >= 4
    assert report["search_matches"] == 1
    assert report["lineage_distance_count"] >= 4
    assert Path(report["project_database"]).is_file()
    assert Path(report["manifest_path"]).is_file()
    assert (
        hashlib.sha256(Path(report["original_source"]).read_bytes()).hexdigest()
        == report["original_sha256"]
    )
