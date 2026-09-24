from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from pig.application.errors import ApplicationError


STAGING_MANIFEST_SCHEMA_VERSION = "1.0"


def _safe_token(value: str, field: str) -> str:
    if not value or len(value) > 128 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in value
    ):
        raise ApplicationError(
            "INVALID_STAGING_MANIFEST",
            f"{field} is not a safe generated token",
        )
    return value


def _safe_storage_key(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or any(part in {"", "."} for part in path.parts)
    ):
        raise ApplicationError(
            "INVALID_STAGING_MANIFEST",
            "manifest storage keys must be project-relative POSIX paths",
        )
    return path.as_posix()


@dataclass(frozen=True, slots=True)
class LoadedStagingManifest:
    path: Path
    payload: Mapping[str, Any]


class StagingOperationManifest:
    """Durable evidence for one filesystem/SQLite spanning operation."""

    def __init__(
        self,
        project_path: Path,
        operation_id: str,
        operation_type: str,
        project_id: str,
        *,
        source_keys: Sequence[str] = (),
        target_keys: Sequence[str] = (),
        entries: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self._project = Path(project_path).resolve(strict=True)
        self._operation_id = _safe_token(operation_id, "operation_id")
        self._operation_type = _safe_token(operation_type, "operation_type")
        self._project_id = _safe_token(project_id, "project_id")
        self._path = (
            self._project
            / ".staging"
            / "operations"
            / f"{self._operation_id}.json"
        )
        self._payload: dict[str, Any] = {
            "schema_version": STAGING_MANIFEST_SCHEMA_VERSION,
            "operation_id": self._operation_id,
            "operation_type": self._operation_type,
            "project_id": self._project_id,
            "phase": "PREPARED",
            "source_keys": [_safe_storage_key(value) for value in source_keys],
            "target_keys": [_safe_storage_key(value) for value in target_keys],
            "entries": [dict(value) for value in entries],
            "expected_size": None,
            "expected_sha256": None,
        }
        self._write(create=True)

    @property
    def storage_key(self) -> str:
        return self._path.relative_to(self._project).as_posix()

    def update(
        self,
        phase: str,
        *,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
        entries: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self._payload["phase"] = _safe_token(phase, "phase")
        if expected_size is not None:
            if expected_size < 0:
                raise ApplicationError(
                    "INVALID_STAGING_MANIFEST", "expected_size must be nonnegative"
                )
            self._payload["expected_size"] = expected_size
        if expected_sha256 is not None:
            canonical = expected_sha256.lower()
            if len(canonical) != 64 or any(c not in "0123456789abcdef" for c in canonical):
                raise ApplicationError(
                    "INVALID_STAGING_MANIFEST", "expected_sha256 is not canonical"
                )
            self._payload["expected_sha256"] = canonical
        if entries is not None:
            self._payload["entries"] = [dict(value) for value in entries]
        self._write(create=False)

    def complete(self) -> None:
        self._path.unlink(missing_ok=True)
        self._fsync_directory(self._path.parent)
        self._remove_empty_parents(self._path.parent)

    def _write(self, *, create: bool) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.parent.is_symlink():
            raise ApplicationError(
                "UNSAFE_WORKSPACE", "staging operation directory is a symbolic link"
            )
        temporary = self._path.with_suffix(".json.tmp")
        if create and (self._path.exists() or temporary.exists()):
            raise ApplicationError(
                "STAGING_MANIFEST_COLLISION", "staging operation already exists"
            )
        payload = json.dumps(
            self._payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self._path)
        self._fsync_directory(self._path.parent)

    def _remove_empty_parents(self, value: Path) -> None:
        stop = self._project / ".staging"
        current = value
        while current != stop:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
        try:
            stop.rmdir()
        except OSError:
            pass

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)


def load_staging_manifests(project_path: Path) -> tuple[LoadedStagingManifest, ...]:
    project = Path(project_path).resolve(strict=True)
    root = project / ".staging" / "operations"
    if not root.exists():
        return ()
    if root.is_symlink() or not root.is_dir():
        raise ApplicationError(
            "UNSAFE_WORKSPACE", "staging operation directory is not controlled"
        )
    result: list[LoadedStagingManifest] = []
    for path in sorted(root.iterdir(), key=lambda value: value.name.casefold()):
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ApplicationError(
                "INVALID_STAGING_MANIFEST",
                "a staging operation manifest is unreadable",
                {"storage_key": path.relative_to(project).as_posix()},
            ) from exc
        if payload.get("schema_version") != STAGING_MANIFEST_SCHEMA_VERSION:
            raise ApplicationError(
                "UNSUPPORTED_STAGING_MANIFEST",
                "staging operation manifest version is unsupported",
                {"storage_key": path.relative_to(project).as_posix()},
            )
        result.append(LoadedStagingManifest(path=path, payload=payload))
    return tuple(result)


def finalize_staging_manifest(project_path: Path, operation_id: str) -> None:
    """Mark the SQLite commit boundary and remove its durable operation evidence."""

    project = Path(project_path).resolve(strict=True)
    operation = _safe_token(operation_id, "operation_id")
    path = project / ".staging" / "operations" / f"{operation}.json"
    if not path.exists():
        return
    if path.is_symlink() or not path.is_file():
        raise ApplicationError(
            "UNSAFE_WORKSPACE", "staging manifest is not a regular file"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ApplicationError(
            "INVALID_STAGING_MANIFEST", "staging manifest cannot be finalized"
        ) from exc
    payload["phase"] = "DATABASE_COMMITTED"
    temporary = path.with_suffix(".json.tmp")
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    with temporary.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    StagingOperationManifest._fsync_directory(path.parent)
    path.unlink()
    StagingOperationManifest._fsync_directory(path.parent)
    current = path.parent
    stop = project / ".staging"
    while current != stop:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
    try:
        stop.rmdir()
    except OSError:
        pass
