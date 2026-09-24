from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional, Protocol, Sequence

from pig.domain.enums import ErrorCode
from pig.domain.processing_policy import ProcessingPolicy
from pig.handlers.archive import (
    ArchiveBackendCorruptedError,
    ArchiveBackendDependencyError,
    ArchiveBackendExecutionError,
    ArchiveBackendLimitError,
    ArchiveBackendPasswordError,
    ArchiveBackendTimeoutError,
    ArchiveBackendVersionError,
    ArchiveInspection,
    ArchiveMemberInfo,
    ArchiveMemberToken,
)


_VERSION_PATTERN = re.compile(r"7-Zip(?: \(z\))?\s+(\d+)\.(\d+)", re.IGNORECASE)
_UNIX_SYMLINK_PATTERN = re.compile(r"(?:^|\s)l[rwx-]{9}(?:\s|$)")
_UNIX_DIRECTORY_PATTERN = re.compile(r"(?:^|\s)d[rwx-]{9}(?:\s|$)")


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandResult:
    return_code: int
    stdout: bytes = b""
    stderr: bytes = b""


class CommandTimeoutError(Exception):
    pass


class CommandOutputLimitError(Exception):
    pass


class CommandRunner(Protocol):
    def capture(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: float,
        max_stdout_size: int,
        max_stderr_size: int,
    ) -> CommandResult: ...

    def stream_stdout(
        self,
        arguments: Sequence[str],
        output: BinaryIO,
        *,
        timeout_seconds: float,
        max_stderr_size: int,
    ) -> CommandResult: ...


class BoundedSubprocessRunner:
    """Run one explicit executable without a shell or inherited stdin."""

    def capture(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: float,
        max_stdout_size: int,
        max_stderr_size: int,
    ) -> CommandResult:
        process = self._start(arguments)
        stdout: list[bytes] = []
        stderr: list[bytes] = []
        output_limited = threading.Event()
        stdout_thread = threading.Thread(
            target=self._capture_pipe,
            args=(process.stdout, stdout, max_stdout_size, output_limited, process),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._capture_pipe,
            args=(process.stderr, stderr, max_stderr_size, output_limited, process),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise CommandTimeoutError("external process timed out") from exc
        finally:
            stdout_thread.join()
            stderr_thread.join()
        if output_limited.is_set():
            raise CommandOutputLimitError("external process output exceeded its limit")
        return CommandResult(
            return_code=process.returncode,
            stdout=b"".join(stdout),
            stderr=b"".join(stderr),
        )

    def stream_stdout(
        self,
        arguments: Sequence[str],
        output: BinaryIO,
        *,
        timeout_seconds: float,
        max_stderr_size: int,
    ) -> CommandResult:
        process = self._start(arguments)
        stderr: list[bytes] = []
        stderr_limited = threading.Event()
        stderr_thread = threading.Thread(
            target=self._capture_pipe,
            args=(
                process.stderr,
                stderr,
                max_stderr_size,
                stderr_limited,
                process,
            ),
            daemon=True,
        )
        stderr_thread.start()
        timed_out = threading.Event()

        def terminate_on_timeout() -> None:
            if process.poll() is None:
                timed_out.set()
                process.kill()

        timer = threading.Timer(timeout_seconds, terminate_on_timeout)
        timer.daemon = True
        timer.start()
        try:
            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
            process.wait()
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            timer.cancel()
            stderr_thread.join()
        if timed_out.is_set():
            raise CommandTimeoutError("external process timed out")
        if stderr_limited.is_set():
            raise CommandOutputLimitError("external process stderr exceeded its limit")
        return CommandResult(
            return_code=process.returncode,
            stderr=b"".join(stderr),
        )

    @staticmethod
    def _capture_pipe(
        pipe,
        chunks: list[bytes],
        limit: int,
        limited: threading.Event,
        process: subprocess.Popen,
    ) -> None:
        if pipe is None:
            return
        total = 0
        while True:
            chunk = pipe.read(64 * 1024)
            if not chunk:
                return
            total += len(chunk)
            if total > limit:
                limited.set()
                process.kill()
                return
            chunks.append(chunk)

    @staticmethod
    def _start(arguments: Sequence[str]) -> subprocess.Popen:
        if not arguments or not Path(arguments[0]).is_absolute():
            raise ValueError("external command requires an absolute executable path")
        environment = {
            key: value
            for key in ("SystemRoot", "WINDIR")
            if (value := os.environ.get(key)) is not None
        }
        environment.update({"LANG": "C", "LC_ALL": "C"})
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.Popen(
            list(arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            cwd=str(Path(arguments[0]).parent),
            env=environment,
            creationflags=creation_flags,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SevenZipIdentity:
    path: Path
    version: str
    sha256: str


class SevenZipRarBackend:
    name = "7zip-system"
    version = "1.0"
    minimum_version = (25, 1)
    maximum_version = (27, 0)

    def __init__(
        self,
        executable: Optional[Path],
        *,
        runner: Optional[CommandRunner] = None,
    ) -> None:
        self._configured_executable = (
            Path(executable).absolute()
            if executable is not None
            else self.discover_standard_windows_installation()
        )
        self._runner = runner or BoundedSubprocessRunner()
        self._accepted_identity: Optional[SevenZipIdentity] = None

    @staticmethod
    def discover_standard_windows_installation() -> Optional[Path]:
        """Find 7-Zip only in controlled Windows installation locations."""

        if os.name != "nt":
            return None
        candidates: list[Path] = []
        for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(variable)
            if root:
                candidate = Path(root) / "7-Zip" / "7z.exe"
                if candidate not in candidates:
                    candidates.append(candidate)
        for candidate in candidates:
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            if (
                resolved.is_file()
                and not SevenZipRarBackend._path_contains_symlink(candidate)
            ):
                return resolved
        return None

    def inspect(
        self, path: Path, *, policy: ProcessingPolicy
    ) -> ArchiveInspection:
        identity = self._identity(policy)
        arguments = (
            str(identity.path),
            "l",
            "-slt",
            "-ba",
            "-sccUTF-8",
            "-y",
            "--",
            str(path.resolve(strict=True)),
        )
        try:
            result = self._runner.capture(
                arguments,
                timeout_seconds=policy.external_process_timeout_seconds,
                max_stdout_size=policy.max_external_listing_size,
                max_stderr_size=min(policy.max_external_listing_size, 1024 * 1024),
            )
        except CommandTimeoutError as exc:
            raise ArchiveBackendTimeoutError("7-Zip listing timed out") from exc
        except CommandOutputLimitError as exc:
            raise ArchiveBackendLimitError(
                "7-Zip listing output exceeded the configured limit",
                code=ErrorCode.EXTERNAL_PROCESS_OUTPUT_EXCEEDED,
            ) from exc
        if result.return_code != 0:
            self._raise_command_failure(result, operation="listing")
        members = self._parse_listing(result.stdout)
        if len(members) > policy.max_archive_entries:
            raise ArchiveBackendLimitError(
                "RAR entry count exceeds the configured limit",
                code=ErrorCode.MAX_ARCHIVE_ENTRIES_EXCEEDED,
            )
        return ArchiveInspection(
            members=members,
            details={
                "backend": self.name,
                "backend_version": identity.version,
                "executable_sha256": identity.sha256,
            },
        )

    def validated_identity(self, policy: ProcessingPolicy) -> SevenZipIdentity:
        """Return the controlled backend identity for release/runtime evidence."""

        return self._identity(policy)

    def write_member(
        self,
        path: Path,
        token: ArchiveMemberToken,
        output: BinaryIO,
        *,
        policy: ProcessingPolicy,
    ) -> None:
        identity = self._identity(policy)
        current = self.inspect(path, policy=policy)
        try:
            member = current.members[token.ordinal]
        except IndexError as exc:
            raise ArchiveBackendCorruptedError(
                "RAR member identity changed during processing"
            ) from exc
        if (
            member.name != token.name
            or member.is_directory
            or member.is_symbolic_link
            or member.encrypted
        ):
            raise ArchiveBackendCorruptedError(
                "RAR member identity changed during processing"
            )
        arguments = (
            str(identity.path),
            "x",
            "-so",
            "-y",
            "-spd",
            "-sccUTF-8",
            "--",
            str(path.resolve(strict=True)),
            token.name,
        )
        try:
            result = self._runner.stream_stdout(
                arguments,
                output,
                timeout_seconds=policy.external_process_timeout_seconds,
                max_stderr_size=min(policy.max_external_listing_size, 1024 * 1024),
            )
        except CommandTimeoutError as exc:
            raise ArchiveBackendTimeoutError("7-Zip extraction timed out") from exc
        except CommandOutputLimitError as exc:
            raise ArchiveBackendLimitError(
                "7-Zip diagnostic output exceeded the configured limit",
                code=ErrorCode.EXTERNAL_PROCESS_OUTPUT_EXCEEDED,
            ) from exc
        if result.return_code != 0:
            self._raise_command_failure(result, operation="extraction")

    def _identity(self, policy: ProcessingPolicy) -> SevenZipIdentity:
        configured = self._configured_executable
        if configured is None:
            raise ArchiveBackendDependencyError(
                "RAR processing requires 7-Zip in a standard Windows installation "
                "location or an explicit --seven-zip path"
            )
        if not configured.is_absolute():
            raise ArchiveBackendDependencyError(
                "configured 7-Zip path must be absolute"
            )
        try:
            executable = configured.resolve(strict=True)
        except OSError as exc:
            raise ArchiveBackendDependencyError(
                "configured 7-Zip executable does not exist"
            ) from exc
        if self._path_contains_symlink(configured) or not executable.is_file():
            raise ArchiveBackendDependencyError(
                "configured 7-Zip path must be a non-symbolic-link regular file"
            )
        if os.name != "nt" and not os.access(executable, os.X_OK):
            raise ArchiveBackendDependencyError(
                "configured 7-Zip file is not executable"
            )
        digest = self._sha256(executable)
        if self._accepted_identity is not None:
            if (
                executable != self._accepted_identity.path
                or digest != self._accepted_identity.sha256
            ):
                raise ArchiveBackendDependencyError(
                    "configured 7-Zip executable changed after validation"
                )
            return self._accepted_identity

        try:
            probe = self._runner.capture(
                (str(executable), "i"),
                timeout_seconds=min(policy.external_process_timeout_seconds, 10.0),
                max_stdout_size=1024 * 1024,
                max_stderr_size=1024 * 1024,
            )
        except (CommandTimeoutError, CommandOutputLimitError, OSError) as exc:
            raise ArchiveBackendDependencyError(
                "configured 7-Zip executable could not be validated"
            ) from exc
        text = (probe.stdout + b"\n" + probe.stderr).decode(
            "utf-8", errors="replace"
        )
        match = _VERSION_PATTERN.search(text)
        if probe.return_code != 0 or match is None:
            raise ArchiveBackendDependencyError(
                "configured executable did not identify itself as 7-Zip"
            )
        numeric = (int(match.group(1)), int(match.group(2)))
        if not self.minimum_version <= numeric < self.maximum_version:
            raise ArchiveBackendVersionError(
                f"7-Zip {match.group(1)}.{match.group(2)} is outside the supported range "
                "25.01 <= version < 27.00"
            )
        identity = SevenZipIdentity(
            path=executable,
            version=f"{numeric[0]}.{numeric[1]:02d}",
            sha256=digest,
        )
        self._accepted_identity = identity
        return identity

    @staticmethod
    def _parse_listing(payload: bytes) -> tuple[ArchiveMemberInfo, ...]:
        try:
            text = payload.decode("utf-8", errors="strict").replace(
                "\r\n", "\n"
            )
        except UnicodeDecodeError as exc:
            raise ArchiveBackendCorruptedError(
                "7-Zip listing was not valid UTF-8"
            ) from exc
        records: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in text.split("\n"):
            if not line:
                if current:
                    records.append(current)
                    current = {}
                continue
            if " = " not in line:
                raise ArchiveBackendCorruptedError(
                    "7-Zip listing contained an unparseable record"
                )
            key, value = line.split(" = ", 1)
            if key in current:
                raise ArchiveBackendCorruptedError(
                    "7-Zip listing contained a duplicate field"
                )
            current[key] = value
        if current:
            records.append(current)

        members: list[ArchiveMemberInfo] = []
        for ordinal, record in enumerate(records):
            name = record.get("Path")
            if name is None:
                raise ArchiveBackendCorruptedError(
                    "7-Zip listing record has no member path"
                )
            attributes = record.get("Attributes", "")
            is_directory = (
                record.get("Folder") == "+"
                or attributes.startswith("D")
                or bool(_UNIX_DIRECTORY_PATTERN.search(attributes))
            )
            is_symbolic_link = (
                "Symbolic Link" in record
                or "Hard Link" in record
                or bool(_UNIX_SYMLINK_PATTERN.search(attributes))
            )
            size = SevenZipRarBackend._optional_integer(record.get("Size"))
            packed = SevenZipRarBackend._optional_integer(
                record.get("Packed Size")
            )
            members.append(
                ArchiveMemberInfo(
                    ordinal=ordinal,
                    name=name,
                    is_directory=is_directory,
                    is_symbolic_link=is_symbolic_link,
                    size=size,
                    compressed_size=packed,
                    encrypted=record.get("Encrypted") == "+",
                    token=ArchiveMemberToken(ordinal=ordinal, name=name),
                    supported=True,
                )
            )
        return tuple(members)

    @staticmethod
    def _optional_integer(value: Optional[str]) -> Optional[int]:
        if value is None or not value.strip():
            return None
        try:
            result = int(value)
        except ValueError as exc:
            raise ArchiveBackendCorruptedError(
                "7-Zip listing contained an invalid size"
            ) from exc
        if result < 0:
            raise ArchiveBackendCorruptedError(
                "7-Zip listing contained a negative size"
            )
        return result

    @staticmethod
    def _raise_command_failure(
        result: CommandResult, *, operation: str
    ) -> None:
        message = (result.stdout + b"\n" + result.stderr).decode(
            "utf-8", errors="replace"
        )
        lowered = message.lower()
        if "password" in lowered or "encrypted" in lowered:
            raise ArchiveBackendPasswordError(
                f"RAR {operation} requires a password"
            )
        if result.return_code == 8:
            raise ArchiveBackendExecutionError(
                f"7-Zip reported insufficient memory during RAR {operation}"
            )
        if result.return_code in {7, 255}:
            raise ArchiveBackendExecutionError(
                f"7-Zip could not execute the controlled RAR {operation} command"
            )
        raise ArchiveBackendCorruptedError(
            f"RAR {operation} failed with 7-Zip exit code {result.return_code}"
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise ArchiveBackendDependencyError(
                "configured 7-Zip executable could not be fingerprinted"
            ) from exc
        return digest.hexdigest()

    @staticmethod
    def _path_contains_symlink(path: Path) -> bool:
        absolute = path.absolute()
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current = current / part
            if current.is_symlink():
                return True
        return False
