from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pig.application.errors import ApplicationError
from pig.infrastructure.filesystem.recovery import LocalWorkspaceRecovery


def test_recovery_quarantines_only_uncommitted_outputs(tmp_path: Path) -> None:
    project = tmp_path.absolute()
    known_id = "known-artifact"
    orphan_id = "orphan-artifact"
    known_artifact = project / "artifacts" / "kn" / known_id / "content"
    known_artifact.parent.mkdir(parents=True)
    known_artifact.write_bytes(b"accepted")
    orphan_artifact = project / "artifacts" / "or" / orphan_id / "content"
    orphan_artifact.parent.mkdir(parents=True)
    orphan_artifact.write_bytes(b"orphan")
    staging = project / ".staging" / "crashed-operation"
    staging.mkdir(parents=True)
    (staging / "partial.part").write_bytes(b"partial")
    manifests = project / "manifests"
    manifests.mkdir()
    known_manifest = manifests / "known-manifest.json"
    known_manifest.write_text("{}", encoding="utf-8")
    orphan_manifest = manifests / "orphan-manifest.json"
    orphan_manifest.write_text('{"orphan":true}', encoding="utf-8")
    manifest_staging = manifests / ".staging"
    manifest_staging.mkdir()
    (manifest_staging / "partial.part").write_bytes(b"partial")
    handoff = project / ".open-handoff" / "artifact-id"
    handoff.mkdir(parents=True)
    (handoff / "document.pdf").write_bytes(b"derived open copy")

    report = LocalWorkspaceRecovery().reconcile(
        project,
        "recovery-1",
        known_artifact_keys=frozenset(
            {f"artifacts/kn/{known_id}/content"}
        ),
        known_manifest_keys=frozenset({"manifests/known-manifest.json"}),
    )

    assert known_artifact.read_bytes() == b"accepted"
    assert known_manifest.read_text(encoding="utf-8") == "{}"
    assert not orphan_artifact.exists()
    assert not (project / ".staging").exists()
    assert not manifest_staging.exists()
    assert {item.kind for item in report.records} == {
        "ARTIFACT_STAGING",
        "ARTIFACT_ORPHAN",
        "MANIFEST_STAGING",
        "MANIFEST_ORPHAN",
        "OPEN_HANDOFF_CACHE",
    }
    manifest_record = next(
        item for item in report.records if item.kind == "MANIFEST_ORPHAN"
    )
    assert manifest_record.sha256 == hashlib.sha256(
        b'{"orphan":true}'
    ).hexdigest()
    recovery_report = json.loads(
        (project / "recovery" / "quarantine" / "recovery-1" / "report.json")
        .read_text(encoding="utf-8")
    )
    assert recovery_report["complete"] is True
    assert len(recovery_report["records"]) == 5
    for item in report.records:
        assert project.joinpath(*item.quarantine_storage_key.split("/")).exists()


def test_recovery_is_noop_without_orphans(tmp_path: Path) -> None:
    report = LocalWorkspaceRecovery().reconcile(
        tmp_path.absolute(),
        "recovery-2",
        known_artifact_keys=frozenset(),
        known_manifest_keys=frozenset(),
    )

    assert report.records == ()
    assert not (tmp_path / "recovery").exists()


def test_recovery_rejects_invalid_database_storage_keys(tmp_path: Path) -> None:
    with pytest.raises(ApplicationError) as failure:
        LocalWorkspaceRecovery().reconcile(
            tmp_path.absolute(),
            "recovery-3",
            known_artifact_keys=frozenset({"artifacts/aa/wrong-prefix/content"}),
            known_manifest_keys=frozenset(),
        )

    assert failure.value.code == "WORKSPACE_INTEGRITY_FAILED"
