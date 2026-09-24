from __future__ import annotations

import hashlib
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from pig.application.errors import ApplicationError
from pig.application.ports import StoredWorkingVersion, WorkingVersionPair
from pig.domain.enums import ErrorCode
from pig.infrastructure.filesystem.workbench_storage import LocalInspectionCache
from pig.infrastructure.filesystem.staging_manifest import StagingOperationManifest


class LocalWorkingVersionStore:
    """Maintain one current checkpoint and one previous Working version."""

    def initialize(
        self,
        project_path: Path,
        operation_id: str,
        working_artifact_id: str,
        working_storage_key: str,
        *,
        project_id: str,
        expected_size: int,
        expected_sha256: str,
        maximum: int,
        chunk_size: int,
        stability_retries: int,
    ) -> StoredWorkingVersion:
        project = Path(project_path).resolve(strict=True)
        artifact_id = LocalInspectionCache._safe_id(working_artifact_id)
        operation = LocalInspectionCache._safe_id(operation_id)
        source = self._path(project, working_storage_key, "working")
        current_key = self._version_key(artifact_id, "current")
        destination = self._path(project, current_key, "working-versions")
        staging_root = project / ".staging" / "versions" / operation / artifact_id
        staging = staging_root / "current"
        self._prepare_staging(project, staging_root)
        manifest = StagingOperationManifest(
            project,
            f"{operation}-version",
            "WORKING_VERSION_INITIALIZE",
            project_id,
            source_keys=(working_storage_key,),
            target_keys=(current_key,),
        )
        published = False
        try:
            manifest.update("WRITING")
            stored = self._copy_verified(
                source,
                staging,
                storage_key=current_key,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                maximum=maximum,
                chunk_size=chunk_size,
                stability_retries=stability_retries,
            )
            self._publish_new(project, staging, destination)
            published = True
            manifest.update(
                "PUBLISHED", expected_size=stored.size, expected_sha256=stored.sha256
            )
            return StoredWorkingVersion(
                storage_key=current_key,
                path=destination,
                size=stored.size,
                sha256=stored.sha256,
                file_modified_at=stored.file_modified_at,
            )
        except BaseException:
            if not published:
                manifest.complete()
            raise
        finally:
            self._cleanup(staging_root, project / ".staging")

    def capture(
        self,
        project_path: Path,
        operation_id: str,
        working_artifact_id: str,
        working_storage_key: str,
        current_checkpoint_key: str,
        *,
        project_id: str,
        expected_old_size: int,
        expected_old_sha256: str,
        expected_new_size: int,
        expected_new_sha256: str,
        maximum: int,
        chunk_size: int,
        stability_retries: int,
    ) -> WorkingVersionPair:
        project = Path(project_path).resolve(strict=True)
        artifact_id = LocalInspectionCache._safe_id(working_artifact_id)
        operation = LocalInspectionCache._safe_id(operation_id)
        expected_current_key = self._version_key(artifact_id, "current")
        if current_checkpoint_key != expected_current_key:
            raise ApplicationError(
                ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                "current version checkpoint key does not match its artifact",
            )
        working = self._path(project, working_storage_key, "working")
        checkpoint = self._path(
            project, current_checkpoint_key, "working-versions"
        )
        previous_key = self._version_key(artifact_id, "previous")
        previous_path = self._path(project, previous_key, "working-versions")
        current_path = self._path(project, expected_current_key, "working-versions")
        staging_root = project / ".staging" / "versions" / operation / artifact_id
        self._prepare_staging(project, staging_root)
        manifest = StagingOperationManifest(
            project,
            f"{operation}-version",
            "WORKING_VERSION_CAPTURE",
            project_id,
            source_keys=(working_storage_key, current_checkpoint_key),
            target_keys=(previous_key, expected_current_key),
        )
        published = False
        try:
            manifest.update("WRITING")
            previous = self._copy_verified(
                checkpoint,
                staging_root / "previous",
                storage_key=previous_key,
                expected_size=expected_old_size,
                expected_sha256=expected_old_sha256,
                maximum=maximum,
                chunk_size=chunk_size,
                stability_retries=stability_retries,
            )
            current = self._copy_verified(
                working,
                staging_root / "current",
                storage_key=expected_current_key,
                expected_size=expected_new_size,
                expected_sha256=expected_new_sha256,
                maximum=maximum,
                chunk_size=chunk_size,
                stability_retries=stability_retries,
            )
            self._publish_replace(project, staging_root / "previous", previous_path)
            self._publish_replace(project, staging_root / "current", current_path)
            published = True
            manifest.update("PUBLISHED")
            return WorkingVersionPair(
                current=self._at_path(current, current_path),
                previous=self._at_path(previous, previous_path),
            )
        except BaseException:
            if not published:
                manifest.complete()
            raise
        finally:
            self._cleanup(staging_root, project / ".staging")

    def rollback(
        self,
        project_path: Path,
        operation_id: str,
        working_artifact_id: str,
        working_storage_key: str,
        current_checkpoint_key: str,
        previous_storage_key: str,
        *,
        project_id: str,
        expected_current_size: int,
        expected_current_sha256: str,
        expected_previous_size: int,
        expected_previous_sha256: str,
        maximum: int,
        chunk_size: int,
        stability_retries: int,
    ) -> WorkingVersionPair:
        project = Path(project_path).resolve(strict=True)
        artifact_id = LocalInspectionCache._safe_id(working_artifact_id)
        operation = LocalInspectionCache._safe_id(operation_id)
        current_key = self._version_key(artifact_id, "current")
        previous_key = self._version_key(artifact_id, "previous")
        if current_checkpoint_key != current_key or previous_storage_key != previous_key:
            raise ApplicationError(
                ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                "working version key does not match its artifact",
            )
        working = self._path(project, working_storage_key, "working")
        current_path = self._path(project, current_key, "working-versions")
        previous_path = self._path(project, previous_key, "working-versions")
        staging_root = project / ".staging" / "versions" / operation / artifact_id
        self._prepare_staging(project, staging_root)
        manifest = StagingOperationManifest(
            project,
            f"{operation}-version",
            "WORKING_VERSION_ROLLBACK",
            project_id,
            source_keys=(working_storage_key, current_checkpoint_key, previous_storage_key),
            target_keys=(working_storage_key, current_key, previous_key),
        )
        published = False
        try:
            manifest.update("WRITING")
            old_current = self._copy_verified(
                current_path,
                staging_root / "previous",
                storage_key=previous_key,
                expected_size=expected_current_size,
                expected_sha256=expected_current_sha256,
                maximum=maximum,
                chunk_size=chunk_size,
                stability_retries=stability_retries,
            )
            new_current = self._copy_verified(
                previous_path,
                staging_root / "current",
                storage_key=current_key,
                expected_size=expected_previous_size,
                expected_sha256=expected_previous_sha256,
                maximum=maximum,
                chunk_size=chunk_size,
                stability_retries=stability_retries,
            )
            working_copy = self._copy_verified(
                previous_path,
                staging_root / "working",
                storage_key=working_storage_key,
                expected_size=expected_previous_size,
                expected_sha256=expected_previous_sha256,
                maximum=maximum,
                chunk_size=chunk_size,
                stability_retries=stability_retries,
            )
            self._publish_replace(project, staging_root / "working", working)
            self._publish_replace(project, staging_root / "previous", previous_path)
            self._publish_replace(project, staging_root / "current", current_path)
            published = True
            manifest.update("PUBLISHED")
            return WorkingVersionPair(
                current=self._at_path(new_current, current_path),
                previous=self._at_path(old_current, previous_path),
            )
        except BaseException:
            if not published:
                manifest.complete()
            raise
        finally:
            self._cleanup(staging_root, project / ".staging")

    def _copy_verified(
        self,
        source: Path,
        destination: Path,
        *,
        storage_key: str,
        expected_size: int,
        expected_sha256: str,
        maximum: int,
        chunk_size: int,
        stability_retries: int,
    ) -> StoredWorkingVersion:
        for attempt in range(stability_retries + 1):
            destination.unlink(missing_ok=True)
            try:
                before = source.lstat()
                if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                    raise ApplicationError(
                        ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                        "working version source is not a regular non-link file",
                    )
                if before.st_size > maximum:
                    raise ApplicationError(
                        ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED.value,
                        "working version exceeds the configured resource limit",
                    )
                digest = hashlib.sha256()
                size = 0
                with source.open("rb") as reader, destination.open("xb") as writer:
                    while True:
                        block = reader.read(chunk_size)
                        if not block:
                            break
                        size += len(block)
                        if size > maximum:
                            raise ApplicationError(
                                ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED.value,
                                "working version exceeds the configured resource limit",
                            )
                        writer.write(block)
                        digest.update(block)
                    writer.flush()
                    os.fsync(writer.fileno())
                after = source.lstat()
            except FileNotFoundError as exc:
                if attempt < stability_retries:
                    continue
                raise ApplicationError(
                    ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                    "working version source is missing",
                ) from exc
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
            sha256 = digest.hexdigest()
            if not stable:
                if attempt < stability_retries:
                    continue
                raise ApplicationError(
                    ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                    "working version changed while it was being captured",
                )
            if size != expected_size or sha256 != expected_sha256:
                raise ApplicationError(
                    ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                    "working version fingerprint does not match the expected state",
                )
            return StoredWorkingVersion(
                storage_key=storage_key,
                path=destination,
                size=size,
                sha256=sha256,
                file_modified_at=datetime.fromtimestamp(
                    before.st_mtime, tz=timezone.utc
                ),
            )
        raise AssertionError("version copy loop did not return")

    @staticmethod
    def _version_key(artifact_id: str, name: str) -> str:
        return str(PurePosixPath("working-versions") / artifact_id / name)

    @classmethod
    def _path(cls, project: Path, storage_key: str, prefix: str) -> Path:
        relative = PurePosixPath(storage_key)
        if (
            relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
            or "\\" in storage_key
            or relative.parts[0] != prefix
        ):
            raise ApplicationError(
                ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                "invalid Working version storage key",
            )
        target = project.joinpath(*relative.parts)
        cls._ensure_controlled_parent(project, target.parent)
        return target

    @classmethod
    def _prepare_staging(cls, project: Path, root: Path) -> None:
        cls._ensure_controlled_parent(project, root.parent)
        if root.exists() or root.is_symlink():
            raise ApplicationError("WORKING_VERSION_COLLISION", "version staging exists")
        root.mkdir(parents=True)

    @classmethod
    def _publish_new(cls, project: Path, staging: Path, destination: Path) -> None:
        cls._ensure_controlled_parent(project, destination.parent)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            raise ApplicationError(
                "WORKING_VERSION_COLLISION", "version destination already exists"
            )
        os.replace(staging, destination)

    @classmethod
    def _publish_replace(cls, project: Path, staging: Path, destination: Path) -> None:
        cls._ensure_controlled_parent(project, destination.parent)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = destination.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode)
        ):
            raise ApplicationError(
                ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                "unsafe version destination will not be replaced",
            )
        os.replace(staging, destination)

    @staticmethod
    def _at_path(value: StoredWorkingVersion, path: Path) -> StoredWorkingVersion:
        return StoredWorkingVersion(
            storage_key=value.storage_key,
            path=path,
            size=value.size,
            sha256=value.sha256,
            file_modified_at=value.file_modified_at,
        )

    @staticmethod
    def _ensure_controlled_parent(project: Path, path: Path) -> None:
        current = project
        for segment in path.relative_to(project).parts:
            current = current / segment
            if current.is_symlink():
                raise ApplicationError(
                    ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                    "working version path traverses a link",
                )
            if current.exists() and not current.is_dir():
                raise ApplicationError(
                    ErrorCode.WORKING_VERSION_INTEGRITY_FAILED.value,
                    "working version parent is not a directory",
                )

    @staticmethod
    def _cleanup(path: Path, stop: Path) -> None:
        if path.exists() and not path.is_symlink():
            shutil.rmtree(path)
        current = path.parent
        while current != stop.parent and current.exists() and current.is_dir():
            if any(current.iterdir()):
                break
            current.rmdir()
            if current == stop:
                break
            current = current.parent
