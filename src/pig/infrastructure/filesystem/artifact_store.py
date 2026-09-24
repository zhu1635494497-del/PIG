from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable, Optional

from pig.application.errors import ApplicationError
from pig.domain.entities import Artifact
from pig.domain.enums import (
    ArtifactScope,
    ErrorCategory,
    ErrorCode,
    NodeProcessingStatus,
)
from pig.handlers.base import ArtifactObservation, HandlerOutcomeError, StoredArtifact


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")


class _LimitedArtifactWriter:
    def __init__(
        self,
        output: BinaryIO,
        *,
        prior_total: int,
        max_single_file_size: int,
        max_total_expanded_size: int,
    ) -> None:
        self._output = output
        self._prior_total = prior_total
        self._max_single_file_size = max_single_file_size
        self._max_total_expanded_size = max_total_expanded_size
        self._digest = hashlib.sha256()
        self._signature = bytearray()
        self.written = 0

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    @property
    def signature(self) -> bytes:
        return bytes(self._signature)

    def write(self, data: bytes | bytearray) -> int:
        payload = bytes(data)
        proposed = self.written + len(payload)
        if proposed > self._max_single_file_size:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.LIMIT_EXCEEDED,
                code=ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED,
                category=ErrorCategory.RESOURCE_LIMIT,
                message="actual extracted file exceeds the configured limit",
            )
        if self._prior_total + proposed > self._max_total_expanded_size:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.LIMIT_EXCEEDED,
                code=ErrorCode.MAX_TOTAL_EXPANDED_SIZE_EXCEEDED,
                category=ErrorCategory.RESOURCE_LIMIT,
                message="actual expanded bytes exceed the configured limit",
            )
        if len(self._signature) < 8:
            self._signature.extend(payload[: 8 - len(self._signature)])
        count = self._output.write(payload)
        if count != len(payload):
            raise OSError("artifact staging write was incomplete")
        self._digest.update(payload)
        self.written = proposed
        return count

    def flush(self) -> None:
        self._output.flush()


class LocalArtifactWriteSession(AbstractContextManager):
    def __init__(self, project_path: Path, operation_id: str) -> None:
        self._project_path = project_path.resolve(strict=True)
        self._operation_id = self._validate_id(operation_id)
        self._staging_root = self._project_path / ".staging" / self._operation_id
        self._staged: dict[str, Path] = {}
        self._published: list[Path] = []
        self._total_written = 0
        self._publish_called = False
        self._completed = False

    def __enter__(self) -> "LocalArtifactWriteSession":
        self._assert_controlled_directory(self._project_path)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self._completed:
            self._rollback()

    def write_stream(
        self,
        artifact_id: str,
        stream: BinaryIO,
        *,
        max_single_file_size: int,
        max_total_expanded_size: int,
        chunk_size: int,
    ) -> StoredArtifact:
        def produce(output: BinaryIO) -> None:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    return
                output.write(chunk)

        return self.write_generated(
            artifact_id,
            produce,
            max_single_file_size=max_single_file_size,
            max_total_expanded_size=max_total_expanded_size,
        )

    def write_generated(
        self,
        artifact_id: str,
        producer: Callable[[BinaryIO], None],
        *,
        max_single_file_size: int,
        max_total_expanded_size: int,
    ) -> StoredArtifact:
        artifact_id = self._validate_id(artifact_id)
        if artifact_id in self._staged:
            raise ApplicationError(
                code="ARTIFACT_COLLISION",
                message="artifact was staged more than once",
                details={"artifact_id": artifact_id},
            )
        self._ensure_staging()
        stage_path = self._staging_root / f"{artifact_id}.part"
        writer: Optional[_LimitedArtifactWriter] = None
        try:
            with stage_path.open("xb") as output:
                writer = _LimitedArtifactWriter(
                    output,
                    prior_total=self._total_written,
                    max_single_file_size=max_single_file_size,
                    max_total_expanded_size=max_total_expanded_size,
                )
                producer(writer)  # type: ignore[arg-type]
                writer.flush()
                os.fsync(output.fileno())
        except BaseException:
            stage_path.unlink(missing_ok=True)
            raise
        if writer is None:
            raise ApplicationError(
                code="ARTIFACT_WRITE_FAILED",
                message="artifact writer was not initialized",
            )
        self._total_written += writer.written
        self._staged[artifact_id] = stage_path
        return StoredArtifact(
            storage_key=self.storage_key(artifact_id),
            size=writer.written,
            sha256=writer.sha256,
            signature=writer.signature,
        )

    def publish(self) -> None:
        if self._publish_called:
            raise ApplicationError(
                code="INVALID_ARTIFACT_STATE",
                message="artifact session was published more than once",
            )
        for artifact_id, stage_path in self._staged.items():
            destination_directory = self._destination_directory(artifact_id)
            if destination_directory.exists() or destination_directory.is_symlink():
                raise ApplicationError(
                    code="ARTIFACT_COLLISION",
                    message="artifact destination already exists",
                    details={"artifact_id": artifact_id},
                )
            self._ensure_parent_chain(destination_directory.parent)
            destination_directory.mkdir()
            destination = destination_directory / "content"
            try:
                os.replace(stage_path, destination)
            except BaseException:
                if destination_directory.exists() and not any(destination_directory.iterdir()):
                    destination_directory.rmdir()
                raise
            self._published.append(destination_directory)
        self._remove_staging()
        self._publish_called = True

    def complete(self) -> None:
        if self._staged and not self._publish_called:
            raise ApplicationError(
                code="INVALID_ARTIFACT_STATE",
                message="staged artifacts must be published before completion",
            )
        self._completed = True

    @staticmethod
    def storage_key(artifact_id: str) -> str:
        safe_id = LocalArtifactWriteSession._validate_id(artifact_id)
        return str(
            PurePosixPath("artifacts") / safe_id[:2] / safe_id / "content"
        )

    def _destination_directory(self, artifact_id: str) -> Path:
        return self._project_path / "artifacts" / artifact_id[:2] / artifact_id

    def _ensure_staging(self) -> None:
        staging_parent = self._project_path / ".staging"
        self._ensure_parent_chain(staging_parent)
        if not staging_parent.exists():
            staging_parent.mkdir()
        if staging_parent.is_symlink():
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="artifact staging directory is a symbolic link",
            )
        if not self._staging_root.exists():
            self._staging_root.mkdir()

    def _ensure_parent_chain(self, parent: Path) -> None:
        parent.relative_to(self._project_path)
        current = self._project_path
        for segment in parent.relative_to(self._project_path).parts:
            current = current / segment
            if current.is_symlink():
                raise ApplicationError(
                    code="UNSAFE_WORKSPACE",
                    message="artifact path traverses a workspace symbolic link",
                    details={"component": str(current)},
                )
            if not current.exists():
                current.mkdir()
            elif not current.is_dir():
                raise ApplicationError(
                    code="UNSAFE_WORKSPACE",
                    message="artifact path component is not a directory",
                    details={"component": str(current)},
                )

    def _remove_staging(self) -> None:
        if self._staging_root.is_symlink():
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="refusing to remove symlinked staging directory",
            )
        if self._staging_root.exists():
            shutil.rmtree(self._staging_root)
        parent = self._staging_root.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()

    def _rollback(self) -> None:
        self._remove_staging()
        for directory in reversed(self._published):
            self._require_artifact_directory(directory)
            if directory.exists() and not directory.is_symlink():
                shutil.rmtree(directory)
            prefix = directory.parent
            if prefix.exists() and not any(prefix.iterdir()):
                prefix.rmdir()
        artifacts = self._project_path / "artifacts"
        if artifacts.exists() and not any(artifacts.iterdir()):
            artifacts.rmdir()

    def _require_artifact_directory(self, directory: Path) -> None:
        relative = directory.relative_to(self._project_path)
        if len(relative.parts) != 3 or relative.parts[0] != "artifacts":
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="refusing to remove an unexpected artifact path",
            )

    @staticmethod
    def _validate_id(value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ApplicationError(
                code="INVALID_ARTIFACT_ID",
                message="operation or artifact id is not a safe storage key",
            )
        return value

    @staticmethod
    def _assert_controlled_directory(path: Path) -> None:
        if path.is_symlink() or not path.is_dir():
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="project workspace must be a non-symlink directory",
                details={"path": str(path)},
            )


class LocalArtifactStore:
    def begin(
        self, project_path: Path, operation_id: str
    ) -> LocalArtifactWriteSession:
        return LocalArtifactWriteSession(project_path, operation_id)

    def inspect(
        self, project_path: Path, artifact: Artifact, *, chunk_size: int
    ) -> ArtifactObservation:
        if artifact.scope != ArtifactScope.PROJECT_WORKSPACE:
            raise ApplicationError(
                code="INVALID_ARTIFACT_SCOPE",
                message="workspace Artifact resolver received an external Artifact",
            )
        expected_key = LocalArtifactWriteSession.storage_key(artifact.id)
        if artifact.locator != expected_key:
            raise ApplicationError(
                code=ErrorCode.ARTIFACT_HASH_MISMATCH.value,
                message="Artifact storage key does not match its immutable identity",
                details={"artifact_id": artifact.id},
            )
        root = Path(project_path)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="Project workspace is not a controlled directory",
            )
        path = root.joinpath(*PurePosixPath(artifact.locator).parts)
        current = root
        for part in path.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise ApplicationError(
                    code=ErrorCode.SYMLINK_BLOCKED.value,
                    message="Artifact path traverses a symbolic link",
                    details={"artifact_id": artifact.id},
                )
        try:
            before = path.stat()
        except FileNotFoundError as exc:
            raise ApplicationError(
                code=ErrorCode.ARTIFACT_MISSING.value,
                message="workspace Artifact is missing",
                details={"artifact_id": artifact.id},
            ) from exc
        if not stat.S_ISREG(before.st_mode):
            raise ApplicationError(
                code=ErrorCode.ARTIFACT_MISSING.value,
                message="workspace Artifact is not a regular file",
                details={"artifact_id": artifact.id},
            )
        digest = hashlib.sha256()
        signature = bytearray()
        try:
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if (
                    opened.st_dev != before.st_dev
                    or opened.st_ino != before.st_ino
                ):
                    raise ApplicationError(
                        code=ErrorCode.ARTIFACT_HASH_MISMATCH.value,
                        message="workspace Artifact changed before verification",
                    )
                for chunk in iter(lambda: stream.read(chunk_size), b""):
                    if len(signature) < 8:
                        signature.extend(chunk[: 8 - len(signature)])
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
        except ApplicationError:
            raise
        except OSError as exc:
            raise ApplicationError(
                code=ErrorCode.ARTIFACT_MISSING.value,
                message="workspace Artifact could not be read",
                details={"artifact_id": artifact.id},
            ) from exc
        sha256 = digest.hexdigest()
        if (
            after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
            or artifact.size != after.st_size
            or artifact.sha256 != sha256
        ):
            raise ApplicationError(
                code=ErrorCode.ARTIFACT_HASH_MISMATCH.value,
                message="workspace Artifact no longer matches its accepted fingerprint",
                details={"artifact_id": artifact.id},
            )
        return ArtifactObservation(
            path=path,
            size=after.st_size,
            sha256=sha256,
            signature=bytes(signature),
            observed_at=datetime.now(timezone.utc),
        )
