from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pig.application.errors import ApplicationError
from pig.infrastructure.filesystem.manifest_store import LocalManifestStore


def test_manifest_store_publishes_immutable_id_based_output(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    payload = '{"project":"PIG"}\n'.encode()

    with LocalManifestStore().begin(project, "operation-1") as session:
        stored = session.write("manifest-1", payload, max_size=1024)
        session.publish()
        session.complete()

    assert stored.storage_key == "manifests/manifest-1.json"
    assert stored.path == project / "manifests" / "manifest-1.json"
    assert stored.path.read_bytes() == payload
    assert stored.size == len(payload)
    assert stored.sha256 == hashlib.sha256(payload).hexdigest()
    assert not (project / "manifests" / ".staging").exists()


def test_manifest_store_rolls_back_published_output_until_completed(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(RuntimeError):
        with LocalManifestStore().begin(project, "operation-2") as session:
            stored = session.write("manifest-2", b"payload", max_size=1024)
            session.publish()
            raise RuntimeError("database commit failed")

    assert not stored.path.exists()
    assert not (project / "manifests").exists()


def test_manifest_store_rejects_limit_without_leaving_output(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ApplicationError) as raised:
        with LocalManifestStore().begin(project, "operation-3") as session:
            session.write("manifest-3", b"too-large", max_size=2)

    assert raised.value.code == "MANIFEST_SIZE_EXCEEDED"
    assert not (project / "manifests").exists()


def test_manifest_collision_never_removes_existing_snapshot(tmp_path: Path) -> None:
    project = tmp_path / "project"
    manifest_root = project / "manifests"
    manifest_root.mkdir(parents=True)
    existing = manifest_root / "manifest-4.json"
    existing.write_bytes(b"accepted-snapshot")

    with pytest.raises(ApplicationError) as raised:
        with LocalManifestStore().begin(project, "operation-4") as session:
            session.write("manifest-4", b"replacement", max_size=1024)

    assert raised.value.code == "MANIFEST_COLLISION"
    assert existing.read_bytes() == b"accepted-snapshot"


def test_manifest_staging_collision_never_removes_existing_bytes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    staging = project / "manifests" / ".staging"
    staging.mkdir(parents=True)
    existing = staging / "operation-5.part"
    existing.write_bytes(b"other-operation")

    with pytest.raises(ApplicationError) as raised:
        with LocalManifestStore().begin(project, "operation-5") as session:
            session.write("manifest-5", b"replacement", max_size=1024)

    assert raised.value.code == "MANIFEST_WRITE_FAILED"
    assert existing.read_bytes() == b"other-operation"


def test_manifest_store_rejects_symlinked_output_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (project / "manifests").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic-link creation is not permitted on this test host")

    with pytest.raises(ApplicationError) as raised:
        with LocalManifestStore().begin(project, "operation-6") as session:
            session.write("manifest-6", b"payload", max_size=1024)

    assert raised.value.code == "UNSAFE_MANIFEST_PATH"
    assert list(outside.iterdir()) == []
