from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
import platform

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from pig.domain.processing_policy import ProcessingPolicy
from pig.infrastructure.archives import SevenZipRarBackend


PROJECT_NAME = "pig-project-ingestion-gateway"


def runtime_distributions() -> list[metadata.Distribution]:
    installed = {
        canonicalize_name(distribution.metadata["Name"]): distribution
        for distribution in metadata.distributions()
        if distribution.metadata.get("Name")
    }
    pending = [canonicalize_name(PROJECT_NAME)]
    accepted: dict[str, metadata.Distribution] = {}
    environment = default_environment()
    while pending:
        name = pending.pop()
        if name in accepted:
            continue
        distribution = installed.get(name)
        if distribution is None:
            raise RuntimeError(f"runtime distribution is not installed: {name}")
        accepted[name] = distribution
        for requirement_text in distribution.requires or ():
            requirement = Requirement(requirement_text)
            if requirement.marker is not None and not requirement.marker.evaluate(
                environment
            ):
                continue
            pending.append(canonicalize_name(requirement.name))
    return sorted(
        accepted.values(),
        key=lambda item: canonicalize_name(item.metadata["Name"]),
    )


def license_value(distribution: metadata.Distribution) -> str:
    package_metadata = distribution.metadata
    expression = package_metadata.get("License-Expression")
    if expression:
        return expression.strip()
    license_text = package_metadata.get("License")
    if license_text and len(license_text.strip()) <= 160:
        return license_text.strip()
    classifiers = package_metadata.get_all("Classifier") or ()
    licenses = [
        item.removeprefix("License :: ")
        for item in classifiers
        if item.startswith("License :: ")
    ]
    return "; ".join(licenses) or "UNKNOWN - manual review required"


def project_url(distribution: metadata.Distribution) -> str | None:
    for value in distribution.metadata.get_all("Project-URL") or ():
        _, separator, url = value.partition(",")
        if separator and url.strip():
            return url.strip()
    return distribution.metadata.get("Home-page")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("release"))
    parser.add_argument("--distribution-dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir.absolute()
    output.mkdir(parents=True, exist_ok=True)
    distributions = runtime_distributions()
    packages = [
        {
            "name": item.metadata["Name"],
            "version": item.version,
            "license": license_value(item),
            "project_url": project_url(item),
        }
        for item in distributions
        if canonicalize_name(item.metadata["Name"])
        != canonicalize_name(PROJECT_NAME)
    ]
    notice = {
        "schema": "pig.third-party-notices",
        "version": "1.0",
        "release_status": "REQUIRES_HUMAN_LICENSE_REVIEW",
        "packages": packages,
        "external_runtime_dependencies": [
            _seven_zip_evidence()
        ],
    }
    (output / "THIRD_PARTY_NOTICES.json").write_text(
        json.dumps(notice, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# PIG 第三方组件声明 / Third-Party Notices",
        "",
        "> 发布门：以下元数据由当前环境生成；外部分发前必须完成人工许可证与合规复核。",
        "> Release gate: metadata below is generated from the current environment and requires human license/compliance review before external distribution.",
        "",
        "| Package | Version | Declared license | Project |",
        "|---|---:|---|---|",
    ]
    for item in packages:
        url = item["project_url"] or ""
        lines.append(
            f"| {item['name']} | {item['version']} | "
            f"{str(item['license']).replace('|', '/')} | {url} |"
        )
    lines.extend(
        (
            "",
            "## 外部依赖（不捆绑）/ External, not bundled",
            "",
            "7-Zip 由用户或管理员安装，仅用于 RAR；PIG 安装包不包含其二进制。",
            "7-Zip is operator-provided, used only for RAR, and is not bundled. "
            "See <https://www.7-zip.org/license.txt>.",
            "",
        )
    )
    (output / "THIRD_PARTY_NOTICES.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    runtime_requirements = "\n".join(
        f"{item.metadata['Name']}=={item.version}"
        for item in distributions
        if canonicalize_name(item.metadata["Name"])
        != canonicalize_name(PROJECT_NAME)
    )
    (output / "requirements-runtime.txt").write_text(
        runtime_requirements + "\n", encoding="utf-8"
    )
    if args.distribution_dir is not None:
        _write_distribution_inventory(args.distribution_dir, output)
    return 0


def _seven_zip_evidence() -> dict[str, object]:
    path = SevenZipRarBackend.discover_standard_windows_installation()
    evidence: dict[str, object] = {
        "name": "7-Zip",
        "bundled": False,
        "purpose": "RAR processing only",
        "license": "https://www.7-zip.org/license.txt",
        "discovery": "standard Windows installation locations",
        "status": "NOT_FOUND",
    }
    if path is None:
        return evidence
    try:
        identity = SevenZipRarBackend(path).validated_identity(ProcessingPolicy())
    except Exception as exc:
        evidence.update(
            {
                "status": "FOUND_BUT_REJECTED",
                "path": str(path),
                "error_type": type(exc).__name__,
            }
        )
        return evidence
    evidence.update(
        {
            "status": "VALIDATED",
            "path": str(identity.path),
            "version": identity.version,
            "sha256": identity.sha256,
        }
    )
    return evidence


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_distribution_inventory(distribution_dir: Path, output: Path) -> None:
    root = distribution_dir.absolute().resolve(strict=True)
    files = []
    aggregate = hashlib.sha256()
    for path in sorted(
        (value for value in root.rglob("*") if value.is_file()),
        key=lambda value: value.relative_to(root).as_posix().casefold(),
    ):
        relative = path.relative_to(root).as_posix()
        sha256 = _sha256(path)
        size = path.stat().st_size
        files.append({"path": relative, "size": size, "sha256": sha256})
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(sha256.encode("ascii"))
        aggregate.update(b"\n")
    executable = root / "PIG.exe"
    inventory = {
        "schema": "pig.windows-distribution-inventory",
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "distribution_root": str(root),
        "mode": "onedir",
        "upx": False,
        "file_count": len(files),
        "total_bytes": sum(value["size"] for value in files),
        "build_sha256": aggregate.hexdigest(),
        "executable_sha256": _sha256(executable) if executable.exists() else None,
        "bundled_7zip_binary_count": sum(
            1 for value in files if Path(value["path"]).name.lower() == "7z.exe"
        ),
        "files": files,
    }
    (output / "windows-file-inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
