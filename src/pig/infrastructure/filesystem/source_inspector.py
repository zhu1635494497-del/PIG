from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

from pig.application.errors import ApplicationError
from pig.application.ports import SourceObservation
from pig.domain.entities import Artifact, Source
from pig.domain.enums import ErrorCode, PathFlavor, SourceKind


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class SourceInspectionPolicy:
    hash_chunk_size: int = 1024 * 1024

    def __post_init__(self) -> None:
        if self.hash_chunk_size <= 0:
            raise ValueError("hash_chunk_size must be positive")


class LocalSourceInspector:
    """Read a local Source without modifying it or following a source symlink."""

    def __init__(
        self,
        policy: SourceInspectionPolicy = SourceInspectionPolicy(),
        clock: Clock = _utc_now,
    ) -> None:
        self._policy = policy
        self._clock = clock

    def inspect(self, path: Path, expected_kind: SourceKind) -> SourceObservation:
        value = Path(path)
        if not value.is_absolute():
            raise ApplicationError(
                code="INVALID_REQUEST",
                message="source path must be absolute",
                details={"path": str(value)},
            )
        value = Path(os.path.abspath(value))
        started_at = self._clock()
        self._reject_symlink_components(value)
        try:
            before = value.lstat()
        except FileNotFoundError as exc:
            raise ApplicationError(
                code=ErrorCode.SOURCE_NOT_FOUND.value,
                message="source path does not exist",
                details={"path": str(value)},
            ) from exc
        except OSError as exc:
            raise ApplicationError(
                code="SOURCE_UNREADABLE",
                message="source metadata could not be read",
                details={"path": str(value), "os_error": type(exc).__name__},
            ) from exc

        if stat.S_ISLNK(before.st_mode):
            raise ApplicationError(
                code=ErrorCode.SYMLINK_BLOCKED.value,
                message="symbolic-link sources are not followed",
                details={"path": str(value)},
            )
        actual_kind = self._kind(before.st_mode)
        if actual_kind is None:
            raise ApplicationError(
                code=ErrorCode.UNSUPPORTED_FEATURE.value,
                message="source is neither a regular file nor a directory",
                details={"path": str(value)},
            )
        if actual_kind != expected_kind:
            raise ApplicationError(
                code="SOURCE_KIND_MISMATCH",
                message="source kind does not match the import request",
                details={
                    "path": str(value),
                    "expected": expected_kind.value,
                    "actual": actual_kind.value,
                },
            )

        sha256: str | None = None
        size: int | None = None
        signature = b""
        if actual_kind == SourceKind.FILE:
            sha256, size, signature = self._hash_stable_file(value, before)
        verified_at = self._clock()
        absolute = value.absolute()
        original_name = value.name or value.anchor
        return SourceObservation(
            path=absolute,
            locator=absolute.as_uri(),
            path_flavor=(PathFlavor.WINDOWS if os.name == "nt" else PathFlavor.POSIX),
            kind=actual_kind,
            original_name=original_name,
            display_name=self._safe_display_name(original_name),
            size=size,
            sha256=sha256,
            signature=signature,
            modified_at=datetime.fromtimestamp(before.st_mtime, timezone.utc),
            verification_started_at=started_at,
            verified_at=verified_at,
        )

    def revalidate(self, source: Source) -> SourceObservation:
        current_flavor = PathFlavor.WINDOWS if os.name == "nt" else PathFlavor.POSIX
        if source.path_flavor != current_flavor:
            raise ApplicationError(
                code="UNSUPPORTED_SOURCE_LOCATOR",
                message="source path flavor is not native to this host",
                details={
                    "source_id": source.id,
                    "recorded_flavor": source.path_flavor.value,
                    "host_flavor": current_flavor.value,
                },
            )
        path = self._path_from_locator(source.locator)
        observation = self.inspect(path, source.kind)
        if source.kind == SourceKind.FILE and (
            observation.size != source.observed_size
            or observation.sha256 != source.observed_sha256
        ):
            raise ApplicationError(
                code=ErrorCode.SOURCE_FINGERPRINT_MISMATCH.value,
                message="external source no longer matches its accepted fingerprint",
                details={"source_id": source.id, "locator": source.locator},
            )
        return observation

    def inspect_descendant(
        self,
        source: Source,
        relative_parts: Sequence[str],
        expected_kind: SourceKind,
        expected_artifact: Optional[Artifact] = None,
    ) -> SourceObservation:
        """Resolve a catalogued Folder descendant inside its immutable boundary."""

        if source.kind != SourceKind.FOLDER:
            raise ApplicationError(
                code=ErrorCode.SOURCE_OUTSIDE_BOUNDARY.value,
                message="only Folder Sources can have external descendants",
                details={"source_id": source.id},
            )
        root = Path(os.path.abspath(self._path_from_locator(source.locator)))
        safe_parts: list[str] = []
        for part in relative_parts:
            if (
                not part
                or part in {".", ".."}
                or "\x00" in part
                or "/" in part
                or "\\" in part
                or Path(part).is_absolute()
            ):
                raise ApplicationError(
                    code=ErrorCode.PATH_TRAVERSAL_BLOCKED.value,
                    message="catalogued descendant contains an unsafe path segment",
                    details={"source_id": source.id},
                )
            safe_parts.append(part)
        candidate = Path(os.path.abspath(root.joinpath(*safe_parts)))
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ApplicationError(
                code=ErrorCode.SOURCE_OUTSIDE_BOUNDARY.value,
                message="catalogued descendant resolves outside its Source boundary",
                details={"source_id": source.id},
            ) from exc
        observation = self.inspect(candidate, expected_kind)
        if expected_artifact is not None:
            if observation.locator != expected_artifact.locator:
                raise ApplicationError(
                    code=ErrorCode.SOURCE_OUTSIDE_BOUNDARY.value,
                    message="external Artifact locator does not match its lineage path",
                    details={"artifact_id": expected_artifact.id},
                )
            if (
                observation.size != expected_artifact.size
                or observation.sha256 != expected_artifact.sha256
            ):
                raise ApplicationError(
                    code=ErrorCode.SOURCE_FINGERPRINT_MISMATCH.value,
                    message="external descendant no longer matches its accepted fingerprint",
                    details={"artifact_id": expected_artifact.id},
                )
        return observation

    @staticmethod
    def _reject_symlink_components(path: Path) -> None:
        for candidate in reversed((path, *path.parents)):
            try:
                candidate_stat = candidate.lstat()
            except FileNotFoundError:
                break
            except OSError as exc:
                raise ApplicationError(
                    code="SOURCE_UNREADABLE",
                    message="source path component could not be inspected",
                    details={
                        "path": str(path),
                        "component": str(candidate),
                        "os_error": type(exc).__name__,
                    },
                ) from exc
            if stat.S_ISLNK(candidate_stat.st_mode):
                raise ApplicationError(
                    code=ErrorCode.SYMLINK_BLOCKED.value,
                    message="source path traverses a symbolic link",
                    details={"path": str(path), "component": str(candidate)},
                )

    def _hash_stable_file(
        self, path: Path, before: os.stat_result
    ) -> tuple[str, int, bytes]:
        digest = hashlib.sha256()
        signature = bytearray()
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or not self._same_identity(before, opened):
                    raise ApplicationError(
                        code="SOURCE_CHANGED_DURING_READ",
                        message="source identity changed before hashing",
                        details={"path": str(path)},
                    )
                for chunk in iter(
                    lambda: stream.read(self._policy.hash_chunk_size), b""
                ):
                    if len(signature) < 8:
                        signature.extend(chunk[: 8 - len(signature)])
                    digest.update(chunk)
                after_handle = os.fstat(stream.fileno())
        except ApplicationError:
            raise
        except FileNotFoundError as exc:
            raise ApplicationError(
                code=ErrorCode.SOURCE_NOT_FOUND.value,
                message="source disappeared before it could be hashed",
                details={"path": str(path)},
            ) from exc
        except OSError as exc:
            raise ApplicationError(
                code="SOURCE_UNREADABLE",
                message="source bytes could not be read",
                details={"path": str(path), "os_error": type(exc).__name__},
            ) from exc
        try:
            after_path = path.lstat()
        except OSError as exc:
            raise ApplicationError(
                code="SOURCE_CHANGED_DURING_READ",
                message="source disappeared while it was being hashed",
                details={"path": str(path)},
            ) from exc
        if (
            stat.S_ISLNK(after_path.st_mode)
            or not self._same_snapshot(before, after_handle)
            or not self._same_identity(after_handle, after_path)
        ):
            raise ApplicationError(
                code="SOURCE_CHANGED_DURING_READ",
                message="source changed while it was being hashed",
                details={"path": str(path)},
            )
        return digest.hexdigest(), after_handle.st_size, bytes(signature)

    @staticmethod
    def _path_from_locator(locator: str) -> Path:
        from urllib.parse import unquote, urlparse
        from urllib.request import url2pathname

        parsed = urlparse(locator)
        if parsed.scheme != "file" or (parsed.netloc and parsed.netloc != "localhost"):
            raise ApplicationError(
                code="UNSUPPORTED_SOURCE_LOCATOR",
                message="only local file URI sources can be resolved in V1",
                details={"scheme": parsed.scheme},
            )
        native = url2pathname(unquote(parsed.path))
        if os.name == "nt" and native.startswith("/") and len(native) >= 3:
            if native[2] == ":":
                native = native[1:]
        return Path(native)

    @staticmethod
    def _kind(mode: int) -> SourceKind | None:
        if stat.S_ISREG(mode):
            return SourceKind.FILE
        if stat.S_ISDIR(mode):
            return SourceKind.FOLDER
        return None

    @staticmethod
    def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
        return (
            left.st_dev == right.st_dev
            and left.st_ino == right.st_ino
            and stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
        )

    @staticmethod
    def _same_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
        return (
            LocalSourceInspector._same_identity(left, right)
            and left.st_size == right.st_size
            and left.st_mtime_ns == right.st_mtime_ns
        )

    @staticmethod
    def _safe_display_name(value: str) -> str:
        cleaned = "".join(
            "\ufffd"
            if unicodedata.category(character) in {"Cc", "Cf"}
            else character
            for character in value
        )
        return cleaned or "(unnamed source)"
