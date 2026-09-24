from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Iterable

from pig.application.errors import ApplicationError
from pig.application.ports import QuarantineRecord, WorkspaceRecoveryReport


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")


class LocalWorkspaceRecovery:
    """Move uncommitted workspace outputs to a reversible quarantine."""

    def reconcile(
        self,
        project_path: Path,
        recovery_id: str,
        *,
        known_artifact_keys: frozenset[str],
        known_manifest_keys: frozenset[str],
    ) -> WorkspaceRecoveryReport:
        root = self._controlled_root(project_path)
        identifier = self._safe_id(recovery_id)
        artifact_keys = self._validate_known_keys(
            known_artifact_keys, "artifacts", "content"
        )
        manifest_keys = self._validate_manifest_keys(known_manifest_keys)
        candidates = self._find_candidates(root, artifact_keys, manifest_keys)
        if not candidates:
            return WorkspaceRecoveryReport(records=())

        quarantine = self._create_quarantine(root, identifier)
        records: list[QuarantineRecord] = []
        complete = False
        try:
            for index, (kind, source) in enumerate(candidates, start=1):
                self._require_member(root, source)
                entry_type, size, sha256 = self._describe(source)
                destination_parent = quarantine / f"{index:06d}"
                destination_parent.mkdir()
                destination = destination_parent / "payload"
                original_key = source.relative_to(root).as_posix()
                os.replace(source, destination)
                records.append(
                    QuarantineRecord(
                        kind=kind,
                        original_storage_key=original_key,
                        quarantine_storage_key=destination.relative_to(root).as_posix(),
                        entry_type=entry_type,
                        size=size,
                        sha256=sha256,
                    )
                )
            complete = True
            return WorkspaceRecoveryReport(records=tuple(records))
        except Exception as exc:
            if isinstance(exc, ApplicationError):
                raise
            raise ApplicationError(
                code="WORKSPACE_INTEGRITY_FAILED",
                message="workspace orphan could not be quarantined safely",
            ) from exc
        finally:
            self._write_report(quarantine, records, complete=complete)
            self._remove_known_empty_directories(root)

    def _find_candidates(
        self,
        root: Path,
        artifact_keys: frozenset[str],
        manifest_keys: frozenset[str],
    ) -> list[tuple[str, Path]]:
        candidates: list[tuple[str, Path]] = []
        artifact_staging = root / ".staging"
        if artifact_staging.exists() or artifact_staging.is_symlink():
            candidates.append(("ARTIFACT_STAGING", artifact_staging))

        open_handoff = root / ".open-handoff"
        if open_handoff.exists() or open_handoff.is_symlink():
            candidates.append(("OPEN_HANDOFF_CACHE", open_handoff))

        artifacts = root / "artifacts"
        if artifacts.exists() or artifacts.is_symlink():
            if artifacts.is_symlink() or not artifacts.is_dir():
                raise self._integrity_error("artifacts")
            candidates.extend(
                self._artifact_candidates(root, artifacts, artifact_keys)
            )

        manifests = root / "manifests"
        if manifests.exists() or manifests.is_symlink():
            if manifests.is_symlink() or not manifests.is_dir():
                raise self._integrity_error("manifests")
            for entry in sorted(manifests.iterdir(), key=lambda value: value.name):
                key = entry.relative_to(root).as_posix()
                if entry.name == ".staging":
                    candidates.append(("MANIFEST_STAGING", entry))
                elif key in manifest_keys:
                    if entry.is_symlink() or not entry.is_file():
                        raise self._integrity_error(key)
                else:
                    candidates.append(("MANIFEST_ORPHAN", entry))
        return self._without_nested_candidates(candidates)

    def _artifact_candidates(
        self,
        root: Path,
        artifacts: Path,
        known_keys: frozenset[str],
    ) -> Iterable[tuple[str, Path]]:
        known_directories = {
            str(PurePosixPath(key).parent) for key in known_keys
        }
        known_prefixes = {
            str(PurePosixPath(directory).parent) for directory in known_directories
        }
        for prefix in sorted(artifacts.iterdir(), key=lambda value: value.name):
            prefix_key = prefix.relative_to(root).as_posix()
            if prefix.is_symlink() or not prefix.is_dir():
                if prefix_key in known_prefixes:
                    raise self._integrity_error(prefix_key)
                yield "ARTIFACT_ORPHAN", prefix
                continue
            for artifact_dir in sorted(prefix.iterdir(), key=lambda value: value.name):
                directory_key = artifact_dir.relative_to(root).as_posix()
                if directory_key not in known_directories:
                    yield "ARTIFACT_ORPHAN", artifact_dir
                    continue
                if artifact_dir.is_symlink() or not artifact_dir.is_dir():
                    raise self._integrity_error(directory_key)
                expected_key = f"{directory_key}/content"
                for entry in sorted(
                    artifact_dir.iterdir(), key=lambda value: value.name
                ):
                    key = entry.relative_to(root).as_posix()
                    if key == expected_key:
                        if entry.is_symlink() or not entry.is_file():
                            raise self._integrity_error(key)
                    else:
                        yield "ARTIFACT_ORPHAN", entry

    @staticmethod
    def _without_nested_candidates(
        candidates: Iterable[tuple[str, Path]],
    ) -> list[tuple[str, Path]]:
        accepted: list[tuple[str, Path]] = []
        for candidate in candidates:
            if any(candidate[1].is_relative_to(parent) for _, parent in accepted):
                continue
            accepted.append(candidate)
        return accepted

    def _create_quarantine(self, root: Path, recovery_id: str) -> Path:
        current = root
        for segment in ("recovery", "quarantine"):
            current = current / segment
            if current.is_symlink():
                raise self._integrity_error(current.relative_to(root).as_posix())
            if current.exists() and not current.is_dir():
                raise self._integrity_error(current.relative_to(root).as_posix())
            current.mkdir(exist_ok=True)
        destination = current / recovery_id
        if destination.exists() or destination.is_symlink():
            raise ApplicationError(
                code="WORKSPACE_INTEGRITY_FAILED",
                message="recovery quarantine identifier already exists",
                details={"recovery_id": recovery_id},
            )
        destination.mkdir()
        return destination

    @staticmethod
    def _describe(path: Path) -> tuple[str, int | None, str | None]:
        information = path.lstat()
        if stat.S_ISLNK(information.st_mode):
            return "SYMLINK", None, None
        if stat.S_ISDIR(information.st_mode):
            return "DIRECTORY", None, None
        if not stat.S_ISREG(information.st_mode):
            return "OTHER", None, None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return "FILE", information.st_size, digest.hexdigest()

    @staticmethod
    def _write_report(
        quarantine: Path,
        records: list[QuarantineRecord],
        *,
        complete: bool,
    ) -> None:
        payload = {
            "schema": "pig.workspace-recovery-report",
            "version": "1.0",
            "complete": complete,
            "records": [
                {
                    "kind": item.kind,
                    "original_storage_key": item.original_storage_key,
                    "quarantine_storage_key": item.quarantine_storage_key,
                    "entry_type": item.entry_type,
                    "size": item.size,
                    "sha256": item.sha256,
                }
                for item in records
            ],
        }
        temporary = quarantine / "report.json.part"
        final = quarantine / "report.json"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as output:
                json.dump(payload, output, ensure_ascii=False, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, final)
        except OSError:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _remove_known_empty_directories(root: Path) -> None:
        for path in (
            root / "manifests" / ".staging",
            root / "manifests",
            root / ".open-handoff",
            root / ".staging",
            root / "artifacts",
        ):
            try:
                path.rmdir()
            except OSError:
                pass

    @staticmethod
    def _validate_known_keys(
        keys: frozenset[str], root_name: str, leaf_name: str
    ) -> frozenset[str]:
        for key in keys:
            parts = PurePosixPath(key).parts
            if (
                len(parts) != 4
                or parts[0] != root_name
                or parts[-1] != leaf_name
                or parts[1] != parts[2][:2]
                or not _SAFE_ID.fullmatch(parts[2])
                or any(part in {"", ".", ".."} for part in parts)
            ):
                raise ApplicationError(
                    code="WORKSPACE_INTEGRITY_FAILED",
                    message="database contains an invalid workspace Artifact key",
                )
        return keys

    @staticmethod
    def _validate_manifest_keys(keys: frozenset[str]) -> frozenset[str]:
        for key in keys:
            parts = PurePosixPath(key).parts
            if (
                len(parts) != 2
                or parts[0] != "manifests"
                or not parts[1].endswith(".json")
                or not _SAFE_ID.fullmatch(parts[1][:-5])
                or any(part in {"", ".", ".."} for part in parts)
            ):
                raise ApplicationError(
                    code="WORKSPACE_INTEGRITY_FAILED",
                    message="database contains an invalid Manifest storage key",
                )
        return keys

    @staticmethod
    def _controlled_root(project_path: Path) -> Path:
        path = Path(project_path)
        if not path.is_absolute():
            raise ApplicationError(
                code="WORKSPACE_INTEGRITY_FAILED",
                message="Project workspace path must be absolute",
            )
        try:
            if path.is_symlink():
                raise OSError("workspace is a symbolic link")
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ApplicationError(
                code="WORKSPACE_INTEGRITY_FAILED",
                message="Project workspace is unavailable",
            ) from exc
        if not resolved.is_dir():
            raise ApplicationError(
                code="WORKSPACE_INTEGRITY_FAILED",
                message="Project workspace is not a directory",
            )
        return resolved

    @staticmethod
    def _require_member(root: Path, path: Path) -> None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ApplicationError(
                code="WORKSPACE_INTEGRITY_FAILED",
                message="recovery candidate is outside the Project workspace",
            ) from exc

    @staticmethod
    def _safe_id(value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ApplicationError(
                code="WORKSPACE_INTEGRITY_FAILED",
                message="recovery identifier is not a safe storage key",
            )
        return value

    @staticmethod
    def _integrity_error(storage_key: str) -> ApplicationError:
        return ApplicationError(
            code="WORKSPACE_INTEGRITY_FAILED",
            message="workspace structure failed recovery safety validation",
            details={"storage_key": storage_key},
        )
