from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory", type=Path, default=Path("release/windows-file-inventory.json")
    )
    parser.add_argument(
        "--acceptance-report", type=Path, required=True
    )
    parser.add_argument(
        "--output", type=Path, default=Path("release/windows-build-report.json")
    )
    parser.add_argument("--runtime-smoke-exit-code", type=int, required=True)
    parser.add_argument("--packaged-flow-exit-code", type=int, required=True)
    args = parser.parse_args()

    inventory = _json(args.inventory)
    acceptance = _json(args.acceptance_report)
    report = {
        "schema": "pig.workbench-windows-build-report",
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "PASS_INTERNAL_ACCEPTANCE"
            if args.runtime_smoke_exit_code == 0
            and args.packaged_flow_exit_code == 0
            and acceptance.get("status") == "PASS"
            and inventory.get("bundled_7zip_binary_count") == 0
            else "FAIL"
        ),
        "scope": (
            "当前 Windows 主机的 W9 未签名内部候选构建；不代表人工许可证、代码签名、"
            "干净主机或桌面验收完成。 / W9 unsigned internal candidate build on the current "
            "Windows host; it does not claim completion of human license, code-signing, "
            "clean-host, or manual desktop gates."
        ),
        "platform": platform.platform(),
        "build": {
            "mode": inventory["mode"],
            "console": False,
            "upx": inventory["upx"],
            "migration_head": "0008_workbench_recovery",
            "distribution_root": inventory["distribution_root"],
            "file_count": inventory["file_count"],
            "total_bytes": inventory["total_bytes"],
            "build_sha256": inventory["build_sha256"],
            "executable_sha256": inventory["executable_sha256"],
            "bundled_7zip_binary_count": inventory["bundled_7zip_binary_count"],
        },
        "machine_acceptance": {
            "runtime_smoke_exit_code": args.runtime_smoke_exit_code,
            "packaged_flow_exit_code": args.packaged_flow_exit_code,
            "packaged_flow_status": acceptance["status"],
            "packaged_flow_report": str(args.acceptance_report.resolve()),
            "recovery_item_count": acceptance["recovery_item_count"],
        },
        "open_human_gates": [
            "THIRD_PARTY_LICENSE_REVIEW",
            "CODE_SIGNING_POLICY",
            "CLEAN_WINDOWS_HOST",
            "MANUAL_DESKTOP_ACCEPTANCE",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if report["status"] == "PASS_INTERNAL_ACCEPTANCE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
