from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from pig.domain.enums import ErrorCode
from pig.handlers.base import HandlerOutcomeError
from pig.infrastructure.filesystem.artifact_store import LocalArtifactStore


def test_artifact_store_publishes_id_based_content(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = LocalArtifactStore()

    with store.begin(project, "operation-1") as session:
        artifact = session.write_stream(
            "artifact-1",
            BytesIO(b"evidence"),
            max_single_file_size=100,
            max_total_expanded_size=100,
            chunk_size=3,
        )
        session.publish()
        session.complete()

    assert artifact.storage_key == "artifacts/ar/artifact-1/content"
    assert (project / "artifacts" / "ar" / "artifact-1" / "content").read_bytes() == b"evidence"
    assert not (project / ".staging").exists()


def test_artifact_store_rolls_back_published_content_if_outer_commit_fails(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = LocalArtifactStore()

    with pytest.raises(RuntimeError, match="database commit failed"):
        with store.begin(project, "operation-2") as session:
            session.write_stream(
                "artifact-2",
                BytesIO(b"evidence"),
                max_single_file_size=100,
                max_total_expanded_size=100,
                chunk_size=4,
            )
            session.publish()
            raise RuntimeError("database commit failed")

    assert not (project / "artifacts").exists()
    assert not (project / ".staging").exists()


def test_artifact_store_stops_and_removes_partial_bytes_at_actual_limit(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = LocalArtifactStore()

    with pytest.raises(HandlerOutcomeError) as raised:
        with store.begin(project, "operation-3") as session:
            session.write_stream(
                "artifact-3",
                BytesIO(b"12345"),
                max_single_file_size=4,
                max_total_expanded_size=100,
                chunk_size=2,
            )

    assert raised.value.code == ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED
    assert not (project / "artifacts").exists()
    assert not (project / ".staging").exists()


def test_artifact_store_enforces_actual_total_across_multiple_members(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = LocalArtifactStore()

    with pytest.raises(HandlerOutcomeError) as raised:
        with store.begin(project, "operation-4") as session:
            session.write_stream(
                "artifact-4",
                BytesIO(b"123"),
                max_single_file_size=100,
                max_total_expanded_size=5,
                chunk_size=2,
            )
            session.write_stream(
                "artifact-5",
                BytesIO(b"456"),
                max_single_file_size=100,
                max_total_expanded_size=5,
                chunk_size=2,
            )

    assert raised.value.code == ErrorCode.MAX_TOTAL_EXPANDED_SIZE_EXCEEDED
    assert not (project / "artifacts").exists()
    assert not (project / ".staging").exists()


def test_artifact_store_bounds_callback_generated_output(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = LocalArtifactStore()

    def produce(output) -> None:
        output.write(b"123")
        output.write(b"45")

    with pytest.raises(HandlerOutcomeError) as raised:
        with store.begin(project, "operation-5") as session:
            session.write_generated(
                "artifact-6",
                produce,
                max_single_file_size=4,
                max_total_expanded_size=100,
            )

    assert raised.value.code == ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED
    assert not (project / "artifacts").exists()
    assert not (project / ".staging").exists()


def test_artifact_store_publishes_callback_generated_output(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = LocalArtifactStore()

    with store.begin(project, "operation-6") as session:
        artifact = session.write_generated(
            "artifact-7",
            lambda output: output.write(b"generated"),
            max_single_file_size=100,
            max_total_expanded_size=100,
        )
        session.publish()
        session.complete()

    assert artifact.size == len(b"generated")
    assert (project / "artifacts" / "ar" / "artifact-7" / "content").read_bytes() == b"generated"
