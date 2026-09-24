from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pig.application.errors import ApplicationError
from pig.domain.entities import Artifact
from pig.domain.enums import (
    ArtifactIntegrityStatus,
    ArtifactRole,
    ArtifactScope,
    NodeFormat,
)
from pig.infrastructure.filesystem.open_handoff import LocalOpenHandoffStore


def _artifact(payload: bytes) -> Artifact:
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    return Artifact(
        id="artifact-1",
        project_id="project-1",
        node_id="node-1",
        role=ArtifactRole.EXTRACTED_ARTIFACT,
        scope=ArtifactScope.PROJECT_WORKSPACE,
        locator="artifacts/ar/artifact-1/content",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        integrity_status=ArtifactIntegrityStatus.VERIFIED,
        observed_at=now,
        created_at=now,
    )


def test_handoff_copy_uses_controlled_extension_and_preserves_artifact(
    tmp_path: Path,
) -> None:
    project = tmp_path.absolute()
    payload = b"%PDF-1.7 evidence"
    source = project / "artifacts" / "ar" / "artifact-1" / "content"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)

    result = LocalOpenHandoffStore().prepare(
        project, _artifact(payload), NodeFormat.PDF, source
    )

    assert result == project / ".open-handoff" / "artifact-1" / "document.pdf"
    assert result.read_bytes() == payload
    assert source.read_bytes() == payload


def test_handoff_replaces_only_a_tampered_cache_copy(tmp_path: Path) -> None:
    project = tmp_path.absolute()
    payload = b"PK\x03\x04workbook"
    source = project / "artifacts" / "ar" / "artifact-1" / "content"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    store = LocalOpenHandoffStore()
    result = store.prepare(project, _artifact(payload), NodeFormat.XLSX, source)
    result.write_bytes(b"changed cache")

    repaired = store.prepare(project, _artifact(payload), NodeFormat.XLSX, source)

    assert repaired == result
    assert repaired.read_bytes() == payload
    assert source.read_bytes() == payload


def test_handoff_removes_only_stale_controlled_cache_directories(
    tmp_path: Path,
) -> None:
    project = tmp_path.absolute()
    payload = b"text"
    source = project / "artifacts" / "ar" / "artifact-1" / "content"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    stale = project / ".open-handoff" / "old-artifact"
    stale.mkdir(parents=True)
    (stale / "document.txt").write_bytes(b"old")
    os.utime(stale, (1.0, 1.0))

    LocalOpenHandoffStore(
        stale_after_seconds=10, clock=lambda: 100.0
    ).prepare(project, _artifact(payload), NodeFormat.TXT, source)

    assert not stale.exists()
    assert source.read_bytes() == payload


def test_handoff_rejects_unapproved_format(tmp_path: Path) -> None:
    project = tmp_path.absolute()
    payload = b"archive"
    source = project / "artifacts" / "ar" / "artifact-1" / "content"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)

    with pytest.raises(ApplicationError) as failure:
        LocalOpenHandoffStore().prepare(
            project, _artifact(payload), NodeFormat.ZIP, source
        )

    assert failure.value.code == "OPEN_HANDOFF_FAILED"
