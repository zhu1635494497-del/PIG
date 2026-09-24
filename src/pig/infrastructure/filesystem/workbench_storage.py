from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
from datetime import datetime, timezone
from contextlib import AbstractContextManager
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable

from pig.application.errors import ApplicationError
from pig.application.ports import StoredWorkingContent, WorkingContentObservation
from pig.domain.enums import ErrorCode, WorkingContentStatus
from pig.domain.paths import safe_working_filename
from pig.infrastructure.filesystem.staging_manifest import StagingOperationManifest


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")
_SAFE_SUFFIX = re.compile(r"^\.[a-z0-9]{1,16}$")


class _BoundedHashWriter:
    def __init__(
        self,
        stream: BinaryIO,
        maximum: int,
        error_code: ErrorCode = ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED,
    ) -> None:
        self._stream = stream
        self._maximum = maximum
        self._error_code = error_code
        self.size = 0
        self._digest = hashlib.sha256()

    def write(self, value: bytes) -> int:
        self.size += len(value)
        if self.size > self._maximum:
            raise ApplicationError(
                self._error_code.value,
                "materialized content exceeds the configured resource limit",
                {"maximum": self._maximum},
            )
        written = self._stream.write(value)
        self._digest.update(value[:written])
        return written

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()


class LocalInspectionCache(AbstractContextManager):
    def __init__(self, project_path: Path, operation_id: str) -> None:
        self._project = Path(project_path).resolve(strict=True)
        self._operation_id = self._safe_id(operation_id)
        self._root = self._project / ".inspection" / self._operation_id
        self._total_size = 0

    def __enter__(self) -> "LocalInspectionCache":
        self._ensure_directory(self._root.parent)
        if self._root.exists() or self._root.is_symlink():
            raise ApplicationError(
                "INSPECTION_CACHE_COLLISION", "inspection cache already exists"
            )
        self._root.mkdir()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._root.exists() and not self._root.is_symlink():
            shutil.rmtree(self._root)
        parent = self._root.parent
        if parent.exists() and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()

    def materialize(
        self,
        object_id: str,
        producer: Callable[[BinaryIO], None],
        *,
        maximum: int,
        total_maximum: int,
    ) -> Path:
        target = self._root / "objects" / self._safe_id(object_id) / "content"
        target.parent.mkdir(parents=True)
        try:
            with target.open("xb") as raw:
                remaining = total_maximum - self._total_size
                if remaining < 0:
                    remaining = 0
                writer = _BoundedHashWriter(
                    raw,
                    min(maximum, remaining),
                    (
                        ErrorCode.MAX_TOTAL_EXPANDED_SIZE_EXCEEDED
                        if remaining < maximum
                        else ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED
                    ),
                )
                producer(writer)  # type: ignore[arg-type]
                raw.flush()
                os.fsync(raw.fileno())
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        self._total_size += writer.size
        return target

    def _ensure_directory(self, path: Path) -> None:
        current = self._project
        for segment in path.relative_to(self._project).parts:
            current = current / segment
            if current.is_symlink():
                raise ApplicationError("UNSAFE_WORKSPACE", "cache path traverses a link")
            if current.exists() and not current.is_dir():
                raise ApplicationError("UNSAFE_WORKSPACE", "cache parent is not a directory")
            if not current.exists():
                current.mkdir()

    @staticmethod
    def _safe_id(value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ApplicationError("INVALID_STORAGE_ID", "unsafe generated identity")
        return value


class LocalWorkingArtifactStore:
    def materialize(
        self,
        project_path: Path,
        operation_id: str,
        workspace_item_id: str,
        display_name: str,
        trusted_suffix: str,
        producer: Callable[[BinaryIO], None],
        *,
        project_id: str,
        maximum: int,
    ) -> StoredWorkingContent:
        project = Path(project_path).resolve(strict=True)
        operation = LocalInspectionCache._safe_id(operation_id)
        item = LocalInspectionCache._safe_id(workspace_item_id)
        if not _SAFE_SUFFIX.fullmatch(trusted_suffix):
            raise ApplicationError("INVALID_TRUSTED_SUFFIX", "trusted suffix is invalid")
        friendly_name = safe_working_filename(display_name, trusted_suffix)
        storage_key = str(PurePosixPath("working") / item / friendly_name)
        destination = project.joinpath(*PurePosixPath(storage_key).parts)
        staging = (
            project
            / ".staging"
            / "materializations"
            / operation
            / item
            / friendly_name
        )
        self._ensure_controlled_parent(project, staging.parent)
        if staging.exists() or staging.is_symlink():
            raise ApplicationError("MATERIALIZATION_COLLISION", "staging file exists")
        manifest = StagingOperationManifest(
            project,
            f"{operation}-working",
            "WORKING_MATERIALIZATION",
            project_id,
            target_keys=(storage_key,),
        )
        staging.parent.mkdir(parents=True, exist_ok=True)
        try:
            with staging.open("xb") as raw:
                manifest.update("WRITING")
                writer = _BoundedHashWriter(raw, maximum)
                producer(writer)  # type: ignore[arg-type]
                raw.flush()
                os.fsync(raw.fileno())
            self._ensure_controlled_parent(project, destination.parent)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise ApplicationError(
                    "WORKING_ARTIFACT_COLLISION", "working destination already exists"
                )
            os.replace(staging, destination)
            manifest.update(
                "PUBLISHED", expected_size=writer.size, expected_sha256=writer.sha256
            )
            return StoredWorkingContent(
                storage_key=storage_key,
                path=destination,
                size=writer.size,
                sha256=writer.sha256,
            )
        except BaseException:
            staging.unlink(missing_ok=True)
            if not destination.exists():
                manifest.complete()
            raise
        finally:
            self._remove_empty_parents(staging.parent, project / ".staging")

    def observe(
        self,
        project_path: Path,
        storage_key: str,
        *,
        baseline_size: int,
        baseline_sha256: str,
        maximum: int,
        chunk_size: int,
        stability_retries: int,
    ) -> WorkingContentObservation:
        try:
            project, target = self._controlled_path(project_path, storage_key)
        except ApplicationError as exc:
            return WorkingContentObservation(
                path=Path(project_path).resolve(strict=False),
                status=WorkingContentStatus.UNREADABLE,
                exists=False,
                error_code=ErrorCode.WORKSPACE_INTEGRITY_FAILED,
                error_message=exc.message,
            )
        for attempt in range(stability_retries + 1):
            try:
                before = target.lstat()
            except FileNotFoundError:
                return WorkingContentObservation(
                    path=target,
                    status=WorkingContentStatus.MISSING,
                    exists=False,
                    error_code=ErrorCode.ARTIFACT_MISSING,
                    error_message="Working Artifact is missing",
                )
            except OSError:
                return self._unreadable(target, "Working Artifact cannot be inspected")
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                return self._unreadable(
                    target, "Working Artifact is not a regular non-link file"
                )
            if before.st_size > maximum:
                return self._unreadable(
                    target,
                    "Working Artifact exceeds the configured resource limit",
                    ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED,
                )
            try:
                digest = hashlib.sha256()
                size = 0
                with target.open("rb") as stream:
                    while True:
                        chunk = stream.read(chunk_size)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > maximum:
                            return self._unreadable(
                                target,
                                "Working Artifact exceeds the configured resource limit",
                                ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED,
                            )
                        digest.update(chunk)
                after = target.lstat()
            except FileNotFoundError:
                if attempt < stability_retries:
                    continue
                return WorkingContentObservation(
                    path=target,
                    status=WorkingContentStatus.MISSING,
                    exists=False,
                    error_code=ErrorCode.ARTIFACT_MISSING,
                    error_message="Working Artifact disappeared during inspection",
                )
            except OSError:
                if attempt < stability_retries:
                    continue
                return self._unreadable(target, "Working Artifact cannot be read")
            stable = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            if not stable:
                if attempt < stability_retries:
                    continue
                return self._unreadable(
                    target, "Working Artifact changed during inspection"
                )
            sha256 = digest.hexdigest()
            content_status = (
                WorkingContentStatus.CLEAN
                if size == baseline_size and sha256 == baseline_sha256
                else WorkingContentStatus.MODIFIED
            )
            return WorkingContentObservation(
                path=target,
                status=content_status,
                exists=True,
                size=size,
                sha256=sha256,
                modified_at=datetime.fromtimestamp(
                    after.st_mtime, tz=timezone.utc
                ),
            )
        raise AssertionError("working observation loop did not return")

    def restore(
        self,
        project_path: Path,
        operation_id: str,
        storage_key: str,
        producer: Callable[[BinaryIO], None],
        *,
        project_id: str,
        maximum: int,
        expected_size: int,
        expected_sha256: str,
        allow_replace: bool,
    ) -> StoredWorkingContent:
        project, destination = self._controlled_path(project_path, storage_key)
        operation = LocalInspectionCache._safe_id(operation_id)
        staging = project / ".staging" / "restores" / operation / "content"
        self._ensure_controlled_parent(project, staging.parent)
        if staging.exists() or staging.is_symlink():
            raise ApplicationError("RESTORE_COLLISION", "restore staging file exists")
        manifest = StagingOperationManifest(
            project,
            f"{operation}-working",
            "WORKING_RESTORE",
            project_id,
            source_keys=(storage_key,),
            target_keys=(storage_key,),
        )
        staging.parent.mkdir(parents=True, exist_ok=True)
        try:
            with staging.open("xb") as raw:
                manifest.update("WRITING")
                writer = _BoundedHashWriter(raw, maximum)
                producer(writer)  # type: ignore[arg-type]
                raw.flush()
                os.fsync(raw.fileno())
            if writer.size != expected_size or writer.sha256 != expected_sha256:
                raise ApplicationError(
                    ErrorCode.ARTIFACT_HASH_MISMATCH.value,
                    "restored bytes do not match the immutable baseline",
                )
            self._ensure_controlled_parent(project, destination.parent)
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                existing = destination.lstat()
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
                    raise ApplicationError(
                        ErrorCode.WORKSPACE_INTEGRITY_FAILED.value,
                        "unsafe Working Artifact destination will not be replaced",
                    )
                if not allow_replace:
                    raise ApplicationError(
                        "RESTORE_CONFIRMATION_REQUIRED",
                        "replacing an existing Working Artifact requires confirmation",
                    )
            if existing is None and not allow_replace:
                try:
                    # Same-volume hard-link publication is atomic and cannot
                    # overwrite a file that appears after the lstat above.
                    os.link(staging, destination)
                    staging.unlink()
                except FileExistsError as exc:
                    raise ApplicationError(
                        "RESTORE_CONFIRMATION_REQUIRED",
                        "Working Artifact appeared during restore",
                    ) from exc
            else:
                os.replace(staging, destination)
            manifest.update(
                "PUBLISHED", expected_size=writer.size, expected_sha256=writer.sha256
            )
            return StoredWorkingContent(
                storage_key=storage_key,
                path=destination,
                size=writer.size,
                sha256=writer.sha256,
            )
        except BaseException:
            staging.unlink(missing_ok=True)
            if not destination.exists():
                manifest.complete()
            raise
        finally:
            self._remove_empty_parents(staging.parent, project / ".staging")

    @classmethod
    def _controlled_path(cls, project_path: Path, storage_key: str) -> tuple[Path, Path]:
        project = Path(project_path).resolve(strict=True)
        relative = PurePosixPath(storage_key)
        if (
            relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
            or "\\" in storage_key
            or relative.parts[0] != "working"
        ):
            raise ApplicationError("UNSAFE_WORKSPACE", "invalid working storage key")
        target = project.joinpath(*relative.parts)
        cls._ensure_controlled_parent(project, target.parent)
        return project, target

    @staticmethod
    def _unreadable(
        path: Path,
        message: str,
        code: ErrorCode = ErrorCode.ARTIFACT_UNREADABLE,
    ) -> WorkingContentObservation:
        return WorkingContentObservation(
            path=path,
            status=WorkingContentStatus.UNREADABLE,
            exists=True,
            error_code=code,
            error_message=message,
        )

    @staticmethod
    def _ensure_controlled_parent(project: Path, path: Path) -> None:
        current = project
        for segment in path.relative_to(project).parts:
            current = current / segment
            if current.is_symlink():
                raise ApplicationError("UNSAFE_WORKSPACE", "working path traverses a link")
            if current.exists() and not current.is_dir():
                raise ApplicationError("UNSAFE_WORKSPACE", "working parent is not a directory")

    @staticmethod
    def _remove_empty_parents(path: Path, stop: Path) -> None:
        current = path
        while current != stop.parent and current.exists() and current.is_dir():
            if any(current.iterdir()):
                break
            current.rmdir()
            if current == stop:
                break
            current = current.parent


class LocalInspectionCacheStore:
    def begin(
        self, project_path: Path, operation_id: str
    ) -> LocalInspectionCache:
        return LocalInspectionCache(project_path, operation_id)
