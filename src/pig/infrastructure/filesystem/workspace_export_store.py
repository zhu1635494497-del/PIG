from __future__ import annotations

import hashlib
import os
import shutil
import stat
import zipfile
from pathlib import Path

from pig.application.errors import ApplicationError
from pig.application.ports import (
    StoredWorkspaceExport,
    WorkspaceExportDirectory,
    WorkspaceExportEntry,
)
from pig.domain.enums import ErrorCode, WorkspaceExportKind
from pig.infrastructure.filesystem.workbench_storage import LocalInspectionCache


class LocalWorkspaceExportStore:
    """Atomically publish user-selected Workspace bytes outside the Project."""

    def write(
        self,
        destination: Path,
        operation_id: str,
        entries: tuple[WorkspaceExportEntry, ...],
        directories: tuple[WorkspaceExportDirectory, ...] = (),
        *,
        export_kind: WorkspaceExportKind,
        allow_replace: bool,
        maximum_total_size: int,
        chunk_size: int,
    ) -> StoredWorkspaceExport:
        if (
            export_kind == WorkspaceExportKind.FILE
            and (len(entries) != 1 or directories)
        ) or (
            export_kind == WorkspaceExportKind.ZIP and not entries
        ):
            raise ApplicationError("INVALID_REQUEST", "invalid export entry selection")
        LocalInspectionCache._safe_id(operation_id)
        target = Path(destination).expanduser().resolve(strict=False)
        parent = target.parent.resolve(strict=True)
        if parent.is_symlink() or not parent.is_dir():
            raise ApplicationError(
                ErrorCode.EXPORT_DESTINATION_INVALID.value,
                "export destination parent must be a regular directory",
            )
        try:
            existing = target.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
                raise ApplicationError(
                    ErrorCode.EXPORT_DESTINATION_INVALID.value,
                    "unsafe export destination will not be replaced",
                )
            if export_kind == WorkspaceExportKind.DIRECTORY:
                raise ApplicationError(
                    ErrorCode.EXPORT_DESTINATION_INVALID.value,
                    "an existing directory export destination is never merged or replaced",
                )
            if not allow_replace:
                raise ApplicationError(
                    "EXPORT_CONFIRMATION_REQUIRED",
                    "replacing an existing export requires confirmation",
                )
        staging = parent / f".{target.name}.{operation_id}.pig-export.tmp"
        if staging.exists() or staging.is_symlink():
            raise ApplicationError("EXPORT_STAGING_COLLISION", "export staging exists")
        try:
            if export_kind == WorkspaceExportKind.ZIP:
                total = self._write_zip(
                    staging, entries, directories, maximum_total_size, chunk_size
                )
                sha256, size = self._hash_file(staging, chunk_size)
                if size != total:
                    raise ApplicationError(
                        ErrorCode.EXPORT_FAILED.value,
                        "export size changed before publication",
                    )
            elif export_kind == WorkspaceExportKind.DIRECTORY:
                size, sha256 = self._write_directory(
                    staging, entries, directories, maximum_total_size, chunk_size
                )
            else:
                total = self._copy_file(
                    entries[0], staging, maximum_total_size, chunk_size
                )
                sha256, size = self._hash_file(staging, chunk_size)
                if size != total:
                    raise ApplicationError(
                        ErrorCode.EXPORT_FAILED.value,
                        "export size changed before publication",
                    )
            if existing is None and not allow_replace:
                if export_kind == WorkspaceExportKind.DIRECTORY:
                    try:
                        os.replace(staging, target)
                    except FileExistsError as exc:
                        raise ApplicationError(
                            "EXPORT_CONFIRMATION_REQUIRED",
                            "export destination appeared during publication",
                        ) from exc
                else:
                    try:
                        os.link(staging, target)
                        staging.unlink()
                    except FileExistsError as exc:
                        raise ApplicationError(
                            "EXPORT_CONFIRMATION_REQUIRED",
                            "export destination appeared during publication",
                        ) from exc
            else:
                os.replace(staging, target)
            return StoredWorkspaceExport(
                path=target,
                size=size,
                sha256=sha256,
                entry_count=len(entries),
            )
        except BaseException:
            if staging.exists() and staging.is_dir() and not staging.is_symlink():
                shutil.rmtree(staging)
            else:
                staging.unlink(missing_ok=True)
            raise

    def _write_zip(
        self,
        staging: Path,
        entries: tuple[WorkspaceExportEntry, ...],
        directories: tuple[WorkspaceExportDirectory, ...],
        maximum_total_size: int,
        chunk_size: int,
    ) -> int:
        total_input = 0
        with zipfile.ZipFile(
            staging, mode="x", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            for directory in directories:
                relative = self._safe_relative(directory.relative_path)
                archive.writestr(relative.rstrip("/") + "/", b"")
            for entry in entries:
                total_input += entry.size
                if total_input > maximum_total_size:
                    raise ApplicationError(
                        ErrorCode.MAX_TOTAL_EXPANDED_SIZE_EXCEEDED.value,
                        "export selection exceeds the configured resource limit",
                )
                self._verify_source(entry, chunk_size)
                archive.write(entry.source_path, arcname=entry.relative_path)
                self._verify_source(entry, chunk_size)
        return staging.stat().st_size

    def _write_directory(
        self,
        staging: Path,
        entries: tuple[WorkspaceExportEntry, ...],
        directories: tuple[WorkspaceExportDirectory, ...],
        maximum_total_size: int,
        chunk_size: int,
    ) -> tuple[int, str]:
        staging.mkdir()
        for directory in sorted(
            directories, key=lambda value: (value.relative_path.count("/"), value.relative_path)
        ):
            relative = self._safe_relative(directory.relative_path)
            staging.joinpath(*relative.split("/")).mkdir(parents=True, exist_ok=True)
        total = 0
        digest = hashlib.sha256()
        for entry in sorted(entries, key=lambda value: value.relative_path):
            relative = self._safe_relative(entry.relative_path)
            total += entry.size
            if total > maximum_total_size:
                raise ApplicationError(
                    ErrorCode.MAX_TOTAL_EXPANDED_SIZE_EXCEEDED.value,
                    "export selection exceeds the configured resource limit",
                )
            output = staging.joinpath(*relative.split("/"))
            output.parent.mkdir(parents=True, exist_ok=True)
            self._copy_file(entry, output, maximum_total_size, chunk_size)
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(entry.sha256.encode("ascii"))
            digest.update(b"\0")
        for directory in sorted(value.relative_path for value in directories):
            digest.update(self._safe_relative(directory).encode("utf-8"))
            digest.update(b"/\0")
        return total, digest.hexdigest()

    def _copy_file(
        self,
        entry: WorkspaceExportEntry,
        staging: Path,
        maximum_total_size: int,
        chunk_size: int,
    ) -> int:
        if entry.size > maximum_total_size:
            raise ApplicationError(
                ErrorCode.MAX_TOTAL_EXPANDED_SIZE_EXCEEDED.value,
                "export selection exceeds the configured resource limit",
            )
        before = self._regular_stat(entry.source_path)
        digest = hashlib.sha256()
        size = 0
        with entry.source_path.open("rb") as source, staging.open("xb") as output:
            while True:
                block = source.read(chunk_size)
                if not block:
                    break
                size += len(block)
                output.write(block)
                digest.update(block)
            output.flush()
            os.fsync(output.fileno())
        after = self._regular_stat(entry.source_path)
        if self._fact(before) != self._fact(after):
            raise ApplicationError(
                ErrorCode.EXPORT_FAILED.value,
                "source Working File changed during export",
            )
        if size != entry.size or digest.hexdigest() != entry.sha256:
            raise ApplicationError(
                ErrorCode.EXPORT_FAILED.value,
                "source Working File does not match its refreshed fingerprint",
            )
        return size

    def _verify_source(self, entry: WorkspaceExportEntry, chunk_size: int) -> None:
        before = self._regular_stat(entry.source_path)
        sha256, size = self._hash_file(entry.source_path, chunk_size)
        after = self._regular_stat(entry.source_path)
        if (
            self._fact(before) != self._fact(after)
            or size != entry.size
            or sha256 != entry.sha256
        ):
            raise ApplicationError(
                ErrorCode.EXPORT_FAILED.value,
                "source Working File does not match its refreshed fingerprint",
            )

    @staticmethod
    def _safe_relative(value: str) -> str:
        normalized = value.replace("\\", "/")
        parts = normalized.split("/")
        if (
            not normalized
            or normalized.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or ":" in parts[0]
        ):
            raise ApplicationError(
                ErrorCode.EXPORT_DESTINATION_INVALID.value,
                "invalid Workspace-relative export path",
            )
        return "/".join(parts)

    @staticmethod
    def _regular_stat(path: Path):
        try:
            value = path.lstat()
        except OSError as exc:
            raise ApplicationError(
                ErrorCode.EXPORT_FAILED.value, "export source is unavailable"
            ) from exc
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
            raise ApplicationError(
                ErrorCode.EXPORT_FAILED.value,
                "export source is not a regular non-link file",
            )
        return value

    @staticmethod
    def _fact(value) -> tuple[int, int, int, int]:
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns

    @staticmethod
    def _hash_file(path: Path, chunk_size: int) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while True:
                block = source.read(chunk_size)
                if not block:
                    break
                size += len(block)
                digest.update(block)
        return digest.hexdigest(), size
