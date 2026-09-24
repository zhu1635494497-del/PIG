from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path, PurePosixPath
from typing import Sequence

from pig.application.errors import ApplicationError
from pig.domain.enums import ErrorCode
from pig.infrastructure.filesystem.workbench_storage import LocalInspectionCache
from pig.infrastructure.filesystem.staging_manifest import StagingOperationManifest


class LocalImportUndoSession:
    """Stage one top-level import's Project-owned bytes before DB commit."""

    def __init__(
        self,
        project_path: Path,
        operation_id: str,
        snapshot_id: str,
        project_id: str,
        working_storage_keys: Sequence[str],
        revision_storage_keys: Sequence[str],
    ) -> None:
        self._project = Path(project_path).resolve(strict=True)
        self._operation = LocalInspectionCache._safe_id(operation_id)
        self._snapshot = LocalInspectionCache._safe_id(snapshot_id)
        self._project_id = LocalInspectionCache._safe_id(project_id)
        self._staging = (
            self._project / ".staging" / "import-undo" / self._operation
        )
        self._targets = self._target_directories(
            working_storage_keys, revision_storage_keys
        )
        self._moved: list[tuple[Path, Path]] = []
        self._removed_size = 0
        self._staged = False
        self._completed = False
        self._manifest: StagingOperationManifest | None = None

    @property
    def removed_size(self) -> int:
        return self._removed_size

    def __enter__(self) -> "LocalImportUndoSession":
        entries = tuple(
            {
                "source_key": source.relative_to(self._project).as_posix(),
                "staging_key": (self._staging / f"item-{index}")
                .relative_to(self._project)
                .as_posix(),
            }
            for index, source in enumerate(self._targets)
        )
        self._manifest = StagingOperationManifest(
            self._project,
            self._operation,
            "IMPORT_UNDO",
            self._project_id,
            source_keys=tuple(value["source_key"] for value in entries),
            entries=entries,
        )
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self._completed:
            self._restore()

    def stage(self) -> None:
        if self._staged:
            raise ApplicationError("INVALID_UNDO_STATE", "import undo was staged twice")
        if self._staging.exists() or self._staging.is_symlink():
            raise ApplicationError(
                ErrorCode.IMPORT_ITEM_UNDO_FAILED.value,
                "import undo staging path already exists",
            )
        self._ensure_parents(self._staging.parent)
        self._staging.mkdir(parents=True)
        assert self._manifest is not None
        self._manifest.update("STAGING")
        try:
            for index, source in enumerate(self._targets):
                if not source.exists() and not source.is_symlink():
                    continue
                self._removed_size += self._tree_size(source)
                destination = self._staging / f"item-{index}"
                os.replace(source, destination)
                self._moved.append((source, destination))
            self._staged = True
            self._manifest.update("STAGED")
        except BaseException:
            self._restore()
            raise

    def complete(self) -> None:
        if not self._staged:
            raise ApplicationError("INVALID_UNDO_STATE", "import undo is not staged")
        self._completed = True
        assert self._manifest is not None
        self._manifest.update("DATABASE_COMMITTED")
        try:
            shutil.rmtree(self._staging)
            self._remove_empty_parents()
        except OSError:
            # Bytes are already outside every authoritative storage path. W8
            # recovery may clean an orphaned committed staging directory.
            pass
        self._manifest.complete()

    def _target_directories(
        self,
        working_storage_keys: Sequence[str],
        revision_storage_keys: Sequence[str],
    ) -> tuple[Path, ...]:
        targets = [self._project / "originals" / self._snapshot]
        for storage_key, prefix in (
            *((value, "working") for value in working_storage_keys),
            *((value, "working-versions") for value in revision_storage_keys),
        ):
            relative = PurePosixPath(storage_key)
            if (
                relative.is_absolute()
                or len(relative.parts) < 2
                or relative.parts[0] != prefix
                or ".." in relative.parts
                or "\\" in storage_key
            ):
                raise ApplicationError(
                    ErrorCode.IMPORT_ITEM_UNDO_FAILED.value,
                    "invalid storage key in import undo plan",
                )
            targets.append(self._project.joinpath(*relative.parts[:2]))
        unique: list[Path] = []
        seen: set[Path] = set()
        for target in targets:
            if target in seen:
                continue
            self._ensure_controlled(target)
            seen.add(target)
            unique.append(target)
        return tuple(unique)

    def _tree_size(self, path: Path) -> int:
        value = path.lstat()
        if stat.S_ISLNK(value.st_mode):
            raise ApplicationError(
                ErrorCode.IMPORT_ITEM_UNDO_FAILED.value,
                "import undo refuses a symbolic-link target",
            )
        if stat.S_ISREG(value.st_mode):
            return value.st_size
        if not stat.S_ISDIR(value.st_mode):
            raise ApplicationError(
                ErrorCode.IMPORT_ITEM_UNDO_FAILED.value,
                "import undo target is not a regular file or directory",
            )
        total = 0
        for child in path.iterdir():
            total += self._tree_size(child)
        return total

    def _restore(self) -> None:
        for source, staged in reversed(self._moved):
            if staged.exists() and not source.exists() and not source.is_symlink():
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, source)
        self._moved.clear()
        if self._staging.exists() and not self._staging.is_symlink():
            shutil.rmtree(self._staging)
        self._remove_empty_parents()
        if self._manifest is not None:
            self._manifest.complete()

    def _ensure_controlled(self, target: Path) -> None:
        try:
            relative = target.relative_to(self._project)
        except ValueError as exc:
            raise ApplicationError(
                ErrorCode.IMPORT_ITEM_UNDO_FAILED.value,
                "import undo target escaped the Project",
            ) from exc
        current = self._project
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ApplicationError(
                    ErrorCode.IMPORT_ITEM_UNDO_FAILED.value,
                    "import undo path traverses a symbolic link",
                )

    def _ensure_parents(self, target: Path) -> None:
        self._ensure_controlled(target)
        current = self._project
        for part in target.relative_to(self._project).parts:
            current = current / part
            if current.exists() and not current.is_dir():
                raise ApplicationError(
                    ErrorCode.IMPORT_ITEM_UNDO_FAILED.value,
                    "import undo staging parent is not a directory",
                )

    def _remove_empty_parents(self) -> None:
        current = self._staging.parent
        stop = self._project / ".staging"
        while current != stop.parent and current.exists() and current.is_dir():
            if any(current.iterdir()):
                break
            current.rmdir()
            if current == stop:
                break
            current = current.parent


class LocalImportUndoStore:
    def begin(
        self,
        project_path: Path,
        operation_id: str,
        snapshot_id: str,
        *,
        project_id: str,
        working_storage_keys: Sequence[str],
        revision_storage_keys: Sequence[str],
    ) -> LocalImportUndoSession:
        return LocalImportUndoSession(
            project_path,
            operation_id,
            snapshot_id,
            project_id,
            working_storage_keys,
            revision_storage_keys,
        )
