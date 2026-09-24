from __future__ import annotations

import hashlib
import os
import re
from contextlib import AbstractContextManager
from pathlib import Path, PurePosixPath
from typing import Optional

from pig.application.errors import ApplicationError
from pig.application.ports import StoredManifest


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")


class LocalManifestWriteSession(AbstractContextManager):
    def __init__(self, project_path: Path, operation_id: str) -> None:
        self._project_path = project_path.resolve(strict=True)
        self._operation_id = self._validate_id(operation_id)
        self._manifest_root = self._project_path / "manifests"
        self._staging_root = self._manifest_root / ".staging"
        self._stage_path: Optional[Path] = None
        self._final_path: Optional[Path] = None
        self._published = False
        self._completed = False

    def __enter__(self) -> "LocalManifestWriteSession":
        self._require_controlled_directory(self._project_path, "project workspace")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self._completed:
            self._rollback()

    def write(
        self,
        manifest_id: str,
        payload: bytes,
        *,
        max_size: int,
    ) -> StoredManifest:
        if self._stage_path is not None:
            raise ApplicationError(
                code="MANIFEST_ALREADY_STAGED",
                message="manifest session already contains an output",
            )
        identifier = self._validate_id(manifest_id)
        if len(payload) > max_size:
            raise ApplicationError(
                code="MANIFEST_SIZE_EXCEEDED",
                message="manifest exceeds the configured output limit",
                details={"maximum": max_size, "actual": len(payload)},
            )
        self._ensure_output_directories()
        stage_path = self._staging_root / f"{self._operation_id}.part"
        final_path = self._manifest_root / f"{identifier}.json"
        if final_path.exists() or final_path.is_symlink():
            raise ApplicationError(
                code="MANIFEST_COLLISION",
                message="manifest output already exists",
                details={"manifest_id": identifier},
            )
        stage_created = False
        try:
            with stage_path.open("xb") as output:
                stage_created = True
                written = output.write(payload)
                if written != len(payload):
                    raise OSError("manifest staging write was incomplete")
                output.flush()
                os.fsync(output.fileno())
        except OSError as exc:
            if stage_created:
                stage_path.unlink(missing_ok=True)
            raise ApplicationError(
                code="MANIFEST_WRITE_FAILED",
                message="manifest could not be staged",
            ) from exc
        self._stage_path = stage_path
        self._final_path = final_path
        return StoredManifest(
            storage_key=PurePosixPath("manifests", f"{identifier}.json").as_posix(),
            path=final_path,
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def publish(self) -> None:
        if self._stage_path is None or self._final_path is None:
            raise ApplicationError(
                code="MANIFEST_NOT_STAGED",
                message="manifest must be staged before publication",
            )
        if self._published:
            raise ApplicationError(
                code="MANIFEST_ALREADY_PUBLISHED",
                message="manifest was published more than once",
            )
        link_created = False
        try:
            os.link(
                self._stage_path,
                self._final_path,
                follow_symlinks=False,
            )
            link_created = True
            self._stage_path.unlink()
        except OSError as exc:
            if link_created:
                self._final_path.unlink(missing_ok=True)
            raise ApplicationError(
                code="MANIFEST_PUBLISH_FAILED",
                message="manifest could not be published atomically",
            ) from exc
        self._published = True

    def complete(self) -> None:
        if not self._published:
            raise ApplicationError(
                code="MANIFEST_NOT_PUBLISHED",
                message="manifest must be published before completion",
            )
        self._completed = True
        self._remove_empty_staging()

    def _ensure_output_directories(self) -> None:
        self._create_or_validate_directory(self._manifest_root, "manifest directory")
        self._create_or_validate_directory(self._staging_root, "manifest staging")

    @staticmethod
    def _create_or_validate_directory(path: Path, label: str) -> None:
        try:
            path.mkdir()
        except FileExistsError:
            pass
        except OSError as exc:
            raise ApplicationError(
                code="MANIFEST_WRITE_FAILED",
                message=f"{label} could not be created",
            ) from exc
        LocalManifestWriteSession._require_controlled_directory(path, label)

    @staticmethod
    def _require_controlled_directory(path: Path, label: str) -> None:
        if path.is_symlink() or not path.is_dir():
            raise ApplicationError(
                code="UNSAFE_MANIFEST_PATH",
                message=f"{label} must be a non-symbolic-link directory",
            )

    @staticmethod
    def _validate_id(value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ApplicationError(
                code="INVALID_MANIFEST_ID",
                message="manifest identifier is not a safe path segment",
            )
        return value

    def _rollback(self) -> None:
        if self._stage_path is not None:
            self._stage_path.unlink(missing_ok=True)
        if self._published and self._final_path is not None:
            self._final_path.unlink(missing_ok=True)
        self._remove_empty_staging()
        try:
            self._manifest_root.rmdir()
        except OSError:
            pass

    def _remove_empty_staging(self) -> None:
        try:
            self._staging_root.rmdir()
        except OSError:
            pass


class LocalManifestStore:
    def begin(
        self, project_path: Path, operation_id: str
    ) -> LocalManifestWriteSession:
        return LocalManifestWriteSession(project_path, operation_id)
