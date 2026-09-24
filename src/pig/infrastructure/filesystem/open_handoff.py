from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import time
from pathlib import Path
from typing import Callable

from pig.application.errors import ApplicationError
from pig.domain.entities import Artifact
from pig.domain.enums import ArtifactScope, NodeFormat


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")
_SUFFIXES = {
    NodeFormat.XLSX: ".xlsx",
    NodeFormat.XLS: ".xls",
    NodeFormat.CSV: ".csv",
    NodeFormat.PDF: ".pdf",
    NodeFormat.DOCX: ".docx",
    NodeFormat.DOC: ".doc",
    NodeFormat.PPTX: ".pptx",
    NodeFormat.PPT: ".ppt",
    NodeFormat.TXT: ".txt",
    NodeFormat.JPG: ".jpg",
    NodeFormat.JPEG: ".jpeg",
    NodeFormat.PNG: ".png",
    NodeFormat.MSG: ".msg",
    NodeFormat.EML: ".eml",
}


class LocalOpenHandoffStore:
    """Create bounded, typed copies without renaming or exposing an Artifact."""

    def __init__(
        self,
        *,
        stale_after_seconds: int = 24 * 60 * 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        self._stale_after_seconds = stale_after_seconds
        self._clock = clock

    def prepare(
        self,
        project_path: Path,
        artifact: Artifact,
        format: NodeFormat,
        verified_path: Path,
    ) -> Path:
        if artifact.scope != ArtifactScope.PROJECT_WORKSPACE:
            raise ApplicationError(
                code="OPEN_HANDOFF_FAILED",
                message="only a Workspace Artifact requires a typed handoff copy",
            )
        if not _SAFE_ID.fullmatch(artifact.id):
            raise ApplicationError(
                code="OPEN_HANDOFF_FAILED",
                message="Artifact identity is not safe for handoff storage",
            )
        suffix = _SUFFIXES.get(format)
        if suffix is None:
            raise ApplicationError(
                code="OPEN_HANDOFF_FAILED",
                message="Node format has no approved handoff extension",
            )
        if artifact.size is None or artifact.sha256 is None:
            raise ApplicationError(
                code="OPEN_HANDOFF_FAILED",
                message="Artifact has no accepted fingerprint for handoff",
            )

        root = self._controlled_root(project_path)
        source = self._controlled_source(root, verified_path)
        cache = root / ".open-handoff"
        self._ensure_directory(cache)
        self._remove_stale(cache, preserve=artifact.id)
        destination_directory = cache / artifact.id
        self._ensure_directory(destination_directory)
        destination = destination_directory / f"document{suffix}"
        temporary = destination_directory / f"document{suffix}.part"

        if destination.exists() or destination.is_symlink():
            if self._matches(destination, artifact.size, artifact.sha256):
                return destination
            self._remove_regular(destination)
        if temporary.exists() or temporary.is_symlink():
            self._remove_regular(temporary)

        digest = hashlib.sha256()
        written = 0
        try:
            with source.open("rb") as input_stream, temporary.open("xb") as output:
                for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                    output.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                output.flush()
                os.fsync(output.fileno())
            if written != artifact.size or digest.hexdigest() != artifact.sha256:
                raise ApplicationError(
                    code="OPEN_HANDOFF_FAILED",
                    message="typed handoff copy did not match the verified Artifact",
                )
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return destination

    def _remove_stale(self, cache: Path, *, preserve: str) -> None:
        threshold = self._clock() - self._stale_after_seconds
        for entry in cache.iterdir():
            if entry.name == preserve:
                continue
            if entry.is_symlink() or not entry.is_dir():
                raise ApplicationError(
                    code="UNSAFE_WORKSPACE",
                    message="open handoff cache contains an unsafe entry",
                )
            if entry.stat().st_mtime < threshold:
                shutil.rmtree(entry)

    @staticmethod
    def _controlled_root(project_path: Path) -> Path:
        root = Path(project_path)
        if not root.is_absolute() or root.is_symlink():
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="Project workspace is unsafe for open handoff",
            )
        try:
            resolved = root.resolve(strict=True)
        except OSError as exc:
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="Project workspace is unavailable for open handoff",
            ) from exc
        if not resolved.is_dir():
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="Project workspace is not a directory",
            )
        return resolved

    @staticmethod
    def _controlled_source(root: Path, verified_path: Path) -> Path:
        source = Path(verified_path)
        if not source.is_absolute() or source.is_symlink():
            raise ApplicationError(
                code="OPEN_HANDOFF_FAILED",
                message="verified Artifact path is unsafe for handoff",
            )
        try:
            resolved = source.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise ApplicationError(
                code="OPEN_HANDOFF_FAILED",
                message="verified Artifact path is outside the Project workspace",
            ) from exc
        if not resolved.is_file():
            raise ApplicationError(
                code="OPEN_HANDOFF_FAILED",
                message="verified Artifact path is not a regular file",
            )
        current = root
        for part in resolved.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise ApplicationError(
                    code="OPEN_HANDOFF_FAILED",
                    message="verified Artifact path traverses a symbolic link",
                )
        return resolved

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        if path.is_symlink():
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="open handoff directory must not be a symbolic link",
            )
        path.mkdir(exist_ok=True)
        if not path.is_dir():
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="open handoff path is not a directory",
            )

    @staticmethod
    def _matches(path: Path, size: int, sha256: str) -> bool:
        try:
            information = path.lstat()
        except OSError:
            return False
        if not stat.S_ISREG(information.st_mode) or information.st_size != size:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == sha256

    @staticmethod
    def _remove_regular(path: Path) -> None:
        information = path.lstat()
        if stat.S_ISLNK(information.st_mode) or not stat.S_ISREG(information.st_mode):
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="refusing to replace an unsafe open handoff entry",
            )
        path.unlink()
