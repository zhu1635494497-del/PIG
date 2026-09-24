from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
from typing import Iterable, Mapping

from pig.application.errors import ApplicationError
from pig.application.ports import (
    RecoveryCandidate,
    RecoveryDisposition,
    RecoveryInspection,
)
from pig.domain.enums import RecoveryAction, RecoveryItemKind
from pig.infrastructure.filesystem.staging_manifest import (
    STAGING_MANIFEST_SCHEMA_VERSION,
)


class LocalWorkbenchRecoveryStore:
    """Read-only Workbench residue inspection and confirmed reconciliation."""

    def inspect(
        self,
        project_path: Path,
        project_id: str,
        *,
        known_original_keys: frozenset[str],
        known_working_keys: frozenset[str],
        known_version_keys: frozenset[str],
        purged_snapshot_ids: frozenset[str],
    ) -> RecoveryInspection:
        project = self._project(project_path)
        candidates: list[RecoveryCandidate] = []
        covered: set[str] = set()

        for manifest_path, payload in self._manifests(project):
            storage_key = self._key(project, manifest_path)
            operation_id = str(payload.get("operation_id") or manifest_path.stem)
            operation_type = str(payload.get("operation_type") or "UNKNOWN")
            manifest_project = str(payload.get("project_id") or "")
            if (
                payload.get("schema_version") != STAGING_MANIFEST_SCHEMA_VERSION
                or manifest_project != project_id
            ):
                candidates.append(
                    RecoveryCandidate(
                        kind=RecoveryItemKind.UNKNOWN_STAGING,
                        action=RecoveryAction.QUARANTINE,
                        storage_key=storage_key,
                        operation_id=operation_id,
                        reason="invalid or foreign staging operation manifest",
                    )
                )
                covered.add(storage_key)
                continue

            candidate = self._candidate_from_manifest(
                project,
                manifest_path,
                payload,
                known_original_keys=known_original_keys,
                known_working_keys=known_working_keys,
                known_version_keys=known_version_keys,
                purged_snapshot_ids=purged_snapshot_ids,
            )
            candidates.append(candidate)
            covered.add(candidate.storage_key)
            covered.add(storage_key)

        candidates.extend(self._unmanifested_staging(project, covered))
        candidates.extend(
            self._unregistered_roots(
                project,
                "originals",
                known_original_keys,
                RecoveryItemKind.UNREGISTERED_ORIGINAL,
            )
        )
        candidates.extend(
            self._unregistered_roots(
                project,
                "working",
                known_working_keys,
                RecoveryItemKind.UNREGISTERED_WORKING,
            )
        )
        candidates.extend(
            self._unregistered_roots(
                project,
                "working-versions",
                known_version_keys,
                RecoveryItemKind.UNREGISTERED_VERSION,
            )
        )

        unique = {
            (candidate.storage_key, candidate.action.value): candidate
            for candidate in candidates
        }
        ordered = tuple(
            sorted(
                unique.values(),
                key=lambda value: (
                    value.storage_key.casefold(),
                    value.action.value,
                ),
            )
        )
        token_payload = [
            {
                "kind": value.kind.value,
                "action": value.action.value,
                "storage_key": value.storage_key,
                "operation_id": value.operation_id,
                "reason": value.reason,
                "details": value.details or {},
            }
            for value in ordered
        ]
        token = hashlib.sha256(
            json.dumps(
                token_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return RecoveryInspection(token=token, candidates=ordered)

    def execute(
        self,
        project_path: Path,
        recovery_run_id: str,
        recovery_item_id: str,
        candidate: RecoveryCandidate,
    ) -> RecoveryDisposition:
        project = self._project(project_path)
        target = self._controlled(project, candidate.storage_key)
        size, sha256 = self._fingerprint(target)
        if candidate.action == RecoveryAction.RESTORE:
            self._restore_import_undo(project, candidate)
            return RecoveryDisposition(status="RESTORED", size=size, sha256=sha256)
        if candidate.action == RecoveryAction.REMOVE_REPRODUCIBLE:
            self._require_reproducible_scope(candidate.storage_key)
            self._remove(target)
            self._remove_empty_parents(target.parent, project)
            self._remove_manifest(project, candidate.operation_id)
            return RecoveryDisposition(
                status="REMOVED_REPRODUCIBLE", size=size, sha256=sha256
            )
        if candidate.action == RecoveryAction.REMOVE_MANIFEST:
            self._require_manifest_key(candidate.storage_key)
            self._remove(target)
            self._remove_empty_parents(target.parent, project)
            return RecoveryDisposition(
                status="REMOVED_REPRODUCIBLE", size=size, sha256=sha256
            )
        if candidate.action == RecoveryAction.QUARANTINE:
            if not target.exists() and not target.is_symlink():
                return RecoveryDisposition(status="UNCHANGED")
            destination = (
                project
                / "recovery"
                / "quarantine"
                / self._safe_id(recovery_run_id)
                / self._safe_id(recovery_item_id)
                / "payload"
            )
            destination.parent.mkdir(parents=True, exist_ok=False)
            os.replace(target, destination)
            self._remove_empty_parents(target.parent, project)
            self._remove_manifest(project, candidate.operation_id)
            return RecoveryDisposition(
                status="QUARANTINED",
                size=size,
                sha256=sha256,
                recovery_storage_key=self._key(project, destination),
            )
        return RecoveryDisposition(status="UNCHANGED", size=size, sha256=sha256)

    @staticmethod
    def _fingerprint(path: Path) -> tuple[int | None, str | None]:
        """Measure candidate bytes immediately before a confirmed action.

        Directory hashes are deterministic trees of relative path, kind, size,
        and regular-file content hash. Links are never followed.
        """
        if not path.exists() and not path.is_symlink():
            return None, None
        root_stat = path.lstat()
        if path.is_symlink():
            return int(root_stat.st_size), None
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            return int(root_stat.st_size), digest.hexdigest()
        if not path.is_dir():
            return int(root_stat.st_size), None

        total = 0
        tree_digest = hashlib.sha256()
        pending = [path]
        while pending:
            directory = pending.pop()
            entries = sorted(
                os.scandir(directory), key=lambda value: value.name.casefold()
            )
            for entry in entries:
                entry_path = Path(entry.path)
                relative = entry_path.relative_to(path).as_posix()
                entry_stat = entry.stat(follow_symlinks=False)
                if entry.is_symlink():
                    tree_digest.update(f"L\0{relative}\0{entry_stat.st_size}\n".encode("utf-8"))
                    continue
                if entry.is_dir(follow_symlinks=False):
                    tree_digest.update(f"D\0{relative}\n".encode("utf-8"))
                    pending.append(entry_path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    tree_digest.update(f"O\0{relative}\0{entry_stat.st_size}\n".encode("utf-8"))
                    continue
                content = hashlib.sha256()
                with entry_path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        content.update(block)
                size = int(entry_stat.st_size)
                total += size
                tree_digest.update(
                    f"F\0{relative}\0{size}\0{content.hexdigest()}\n".encode("utf-8")
                )
        return total, tree_digest.hexdigest()

    def _candidate_from_manifest(
        self,
        project: Path,
        manifest_path: Path,
        payload: Mapping[str, object],
        *,
        known_original_keys: frozenset[str],
        known_working_keys: frozenset[str],
        known_version_keys: frozenset[str],
        purged_snapshot_ids: frozenset[str],
    ) -> RecoveryCandidate:
        operation_id = str(payload["operation_id"])
        operation_type = str(payload["operation_type"])
        manifest_key = self._key(project, manifest_path)
        source_keys = tuple(str(value) for value in payload.get("source_keys", ()))
        target_keys = tuple(str(value) for value in payload.get("target_keys", ()))

        if operation_type == "IMPORT_UNDO":
            snapshot_ids = {
                PurePosixPath(value).parts[1]
                for value in source_keys
                if len(PurePosixPath(value).parts) == 2
                and PurePosixPath(value).parts[0] == "originals"
            }
            staging_key = f".staging/import-undo/{operation_id}"
            if snapshot_ids and snapshot_ids <= purged_snapshot_ids:
                if self._controlled(project, staging_key).exists():
                    return RecoveryCandidate(
                        kind=RecoveryItemKind.IMPORT_UNDO_STAGING,
                        action=RecoveryAction.REMOVE_REPRODUCIBLE,
                        storage_key=staging_key,
                        operation_id=operation_id,
                        reason="committed import undo staging is no longer authoritative",
                    )
                return RecoveryCandidate(
                    kind=RecoveryItemKind.OPERATION_MANIFEST,
                    action=RecoveryAction.REMOVE_MANIFEST,
                    storage_key=manifest_key,
                    operation_id=operation_id,
                    reason="committed import undo manifest remained after cleanup",
                )
            return RecoveryCandidate(
                kind=RecoveryItemKind.IMPORT_UNDO_STAGING,
                action=RecoveryAction.RESTORE,
                storage_key=staging_key,
                operation_id=operation_id,
                reason="uncommitted import undo must restore Project-owned bytes",
                details={"entries": list(payload.get("entries", ()))},
            )

        if operation_type == "SNAPSHOT_IMPORT":
            snapshot_id = operation_id
            staging_matches = sorted(
                (project / ".staging" / "imports").glob(f"*/{snapshot_id}")
            ) if (project / ".staging" / "imports").exists() else []
            if staging_matches:
                return RecoveryCandidate(
                    kind=RecoveryItemKind.SNAPSHOT_STAGING,
                    action=RecoveryAction.QUARANTINE,
                    storage_key=self._key(project, staging_matches[0]),
                    operation_id=operation_id,
                    reason="incomplete immutable snapshot bytes require reversible quarantine",
                )
            if any(
                any(known == value or known.startswith(value + "/") for known in known_original_keys)
                for value in target_keys
            ):
                return RecoveryCandidate(
                    kind=RecoveryItemKind.OPERATION_MANIFEST,
                    action=RecoveryAction.REMOVE_MANIFEST,
                    storage_key=manifest_key,
                    operation_id=operation_id,
                    reason="snapshot commit succeeded but operation manifest remained",
                )
            return RecoveryCandidate(
                kind=RecoveryItemKind.OPERATION_MANIFEST,
                action=RecoveryAction.QUARANTINE,
                storage_key=manifest_key,
                operation_id=operation_id,
                reason="snapshot manifest has no registered destination",
            )

        kind = (
            RecoveryItemKind.VERSION_STAGING
            if operation_type.startswith("WORKING_VERSION")
            else RecoveryItemKind.MATERIALIZATION_STAGING
        )
        registered = known_working_keys | known_version_keys
        if target_keys and all(value in registered for value in target_keys):
            return RecoveryCandidate(
                kind=RecoveryItemKind.OPERATION_MANIFEST,
                action=RecoveryAction.REMOVE_MANIFEST,
                storage_key=manifest_key,
                operation_id=operation_id,
                reason="filesystem publication and SQLite registration both succeeded",
            )
        staging_root = self._operation_staging_root(project, operation_type, operation_id)
        if staging_root is not None and staging_root.exists():
            return RecoveryCandidate(
                kind=kind,
                action=RecoveryAction.REMOVE_REPRODUCIBLE,
                storage_key=self._key(project, staging_root),
                operation_id=operation_id,
                reason="staged bytes are reproducible from registered Project data",
            )
        return RecoveryCandidate(
            kind=RecoveryItemKind.OPERATION_MANIFEST,
            action=RecoveryAction.REMOVE_MANIFEST,
            storage_key=manifest_key,
            operation_id=operation_id,
            reason="operation manifest remained without staged payload",
        )

    def _unmanifested_staging(
        self, project: Path, covered: set[str]
    ) -> list[RecoveryCandidate]:
        candidates: list[RecoveryCandidate] = []
        inspection = project / ".inspection"
        if inspection.exists() and inspection.is_dir() and not inspection.is_symlink():
            for child in self._children(inspection):
                key = self._key(project, child)
                candidates.append(
                    RecoveryCandidate(
                        kind=RecoveryItemKind.INSPECTION_CACHE,
                        action=RecoveryAction.REMOVE_REPRODUCIBLE,
                        storage_key=key,
                        operation_id=child.name,
                        reason="inspection cache is derived and reproducible",
                    )
                )

        staging = project / ".staging"
        if not staging.exists() or staging.is_symlink() or not staging.is_dir():
            return candidates
        policies = {
            "materializations": (
                RecoveryItemKind.MATERIALIZATION_STAGING,
                RecoveryAction.REMOVE_REPRODUCIBLE,
            ),
            "restores": (
                RecoveryItemKind.MATERIALIZATION_STAGING,
                RecoveryAction.REMOVE_REPRODUCIBLE,
            ),
            "versions": (
                RecoveryItemKind.VERSION_STAGING,
                RecoveryAction.REMOVE_REPRODUCIBLE,
            ),
            "import-undo": (
                RecoveryItemKind.IMPORT_UNDO_STAGING,
                RecoveryAction.QUARANTINE,
            ),
            "imports": (
                RecoveryItemKind.SNAPSHOT_STAGING,
                RecoveryAction.QUARANTINE,
            ),
        }
        for family in self._children(staging):
            if family.name == "operations":
                for child in self._children(family):
                    key = self._key(project, child)
                    if key not in covered:
                        candidates.append(
                            RecoveryCandidate(
                                kind=RecoveryItemKind.UNKNOWN_STAGING,
                                action=RecoveryAction.QUARANTINE,
                                storage_key=key,
                                reason="unrecognized staging manifest residue",
                            )
                        )
                continue
            kind, action = policies.get(
                family.name,
                (RecoveryItemKind.UNKNOWN_STAGING, RecoveryAction.QUARANTINE),
            )
            for child in self._children(family):
                key = self._key(project, child)
                if any(
                    key == value
                    or key.startswith(value + "/")
                    or value.startswith(key + "/")
                    for value in covered
                ):
                    continue
                candidates.append(
                    RecoveryCandidate(
                        kind=kind,
                        action=action,
                        storage_key=key,
                        operation_id=child.name,
                        reason="staging payload has no active operation manifest",
                    )
                )
        return candidates

    def _unregistered_roots(
        self,
        project: Path,
        root_name: str,
        known_keys: frozenset[str],
        kind: RecoveryItemKind,
    ) -> list[RecoveryCandidate]:
        root = project / root_name
        if not root.exists() or root.is_symlink() or not root.is_dir():
            return []
        candidates: list[RecoveryCandidate] = []
        for child in self._children(root):
            key = self._key(project, child)
            if any(value == key or value.startswith(key + "/") for value in known_keys):
                continue
            candidates.append(
                RecoveryCandidate(
                    kind=kind,
                    action=RecoveryAction.QUARANTINE,
                    storage_key=key,
                    reason=f"{root_name} object is not registered in Project SQLite",
                )
            )
        return candidates

    def _restore_import_undo(
        self, project: Path, candidate: RecoveryCandidate
    ) -> None:
        entries = (candidate.details or {}).get("entries", [])
        if not isinstance(entries, list):
            raise ApplicationError(
                "RECOVERY_PLAN_INVALID", "import undo manifest entries are invalid"
            )
        for raw in entries:
            if not isinstance(raw, dict):
                raise ApplicationError(
                    "RECOVERY_PLAN_INVALID", "import undo entry is invalid"
                )
            source = self._controlled(project, str(raw.get("source_key", "")))
            staged = self._controlled(project, str(raw.get("staging_key", "")))
            if not staged.exists() and not staged.is_symlink():
                continue
            if source.exists() or source.is_symlink():
                raise ApplicationError(
                    "RECOVERY_DESTINATION_COLLISION",
                    "recovery will not overwrite an existing Project object",
                    {"storage_key": self._key(project, source)},
                )
            source.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, source)
        staging = self._controlled(project, candidate.storage_key)
        if staging.exists() and staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging)
        self._remove_manifest(project, candidate.operation_id)
        self._remove_empty_parents(staging.parent, project)

    def _remove_manifest(self, project: Path, operation_id: str | None) -> None:
        if not operation_id:
            return
        path = project / ".staging" / "operations" / f"{self._safe_id(operation_id)}.json"
        path.unlink(missing_ok=True)
        self._remove_empty_parents(path.parent, project)

    @staticmethod
    def _operation_staging_root(
        project: Path, operation_type: str, operation_id: str
    ) -> Path | None:
        base_operation = operation_id.removesuffix("-working").removesuffix("-version")
        if operation_type == "WORKING_MATERIALIZATION":
            return project / ".staging" / "materializations" / base_operation
        if operation_type == "WORKING_RESTORE":
            return project / ".staging" / "restores" / base_operation
        if operation_type.startswith("WORKING_VERSION"):
            return project / ".staging" / "versions" / base_operation
        return None

    @staticmethod
    def _manifests(project: Path) -> Iterable[tuple[Path, Mapping[str, object]]]:
        root = project / ".staging" / "operations"
        if not root.exists() or root.is_symlink() or not root.is_dir():
            return ()
        result: list[tuple[Path, Mapping[str, object]]] = []
        for path in sorted(root.iterdir(), key=lambda value: value.name.casefold()):
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                result.append((path, {}))
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                payload = {}
            result.append((path, payload if isinstance(payload, dict) else {}))
        return tuple(result)

    @staticmethod
    def _children(path: Path) -> tuple[Path, ...]:
        return tuple(sorted(path.iterdir(), key=lambda value: value.name.casefold()))

    @staticmethod
    def _project(path: Path) -> Path:
        project = Path(path).resolve(strict=True)
        value = project.lstat()
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode):
            raise ApplicationError("UNSAFE_WORKSPACE", "Project path is not controlled")
        return project

    @staticmethod
    def _controlled(project: Path, storage_key: str) -> Path:
        relative = PurePosixPath(storage_key)
        if (
            not storage_key
            or relative.is_absolute()
            or ".." in relative.parts
            or "\\" in storage_key
            or any(part in {"", "."} for part in relative.parts)
        ):
            raise ApplicationError(
                "RECOVERY_PATH_REJECTED", "recovery storage key is unsafe"
            )
        target = project.joinpath(*relative.parts)
        current = project
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise ApplicationError(
                    "RECOVERY_PATH_REJECTED", "recovery path traverses a link"
                )
        return target

    @staticmethod
    def _key(project: Path, path: Path) -> str:
        return path.relative_to(project).as_posix()

    @staticmethod
    def _remove(path: Path) -> None:
        try:
            value = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISDIR(value.st_mode) and not stat.S_ISLNK(value.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink()

    @staticmethod
    def _remove_empty_parents(path: Path, project: Path) -> None:
        current = path
        while current != project:
            if not current.exists() or current.is_symlink() or not current.is_dir():
                break
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    @staticmethod
    def _require_reproducible_scope(storage_key: str) -> None:
        if not (
            storage_key == ".inspection"
            or storage_key.startswith(".inspection/")
            or storage_key == ".staging"
            or storage_key.startswith(".staging/")
        ):
            raise ApplicationError(
                "RECOVERY_ACTION_DENIED",
                "only cache and staging data may be removed as reproducible",
            )

    @staticmethod
    def _require_manifest_key(storage_key: str) -> None:
        if not (
            storage_key.startswith(".staging/operations/")
            and storage_key.endswith(".json")
        ):
            raise ApplicationError(
                "RECOVERY_ACTION_DENIED", "only operation manifests may be removed"
            )

    @staticmethod
    def _safe_id(value: str) -> str:
        if not value or len(value) > 128 or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in value
        ):
            raise ApplicationError("RECOVERY_PATH_REJECTED", "recovery id is unsafe")
        return value
