from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from typing import BinaryIO

import py7zr
from py7zr import Py7zIO, WriterFactory
from py7zr.exceptions import (
    Bad7zFile,
    CrcError,
    DecompressionBombError,
    DecompressionError,
    PasswordRequired,
    UnsupportedCompressionMethodError,
)

from pig.domain.enums import ErrorCode
from pig.domain.processing_policy import ProcessingPolicy
from pig.handlers.archive import (
    ArchiveBackendCorruptedError,
    ArchiveBackendLimitError,
    ArchiveBackendPasswordError,
    ArchiveBackendUnsupportedError,
    ArchiveInspection,
    ArchiveMemberInfo,
    ArchiveMemberToken,
)


class _OutputIO(Py7zIO):
    """Sequential py7zr output mapped to PIG's bounded Artifact writer."""

    def __init__(self, output: BinaryIO) -> None:
        self._output = output
        self._size = 0

    def write(self, data: bytes | bytearray) -> int:
        count = self._output.write(data)
        self._size += count
        return count

    def read(self, size: int | None = None) -> bytes:
        return b""

    def seek(self, offset: int, whence: int = 0) -> int:
        if offset == 0 and whence == 0:
            return 0
        if offset == self._size and whence == 0:
            return self._size
        raise OSError("py7zr requested a non-sequential Artifact seek")

    def flush(self) -> None:
        self._output.flush()

    def size(self) -> int:
        return self._size


class _SingleMemberFactory(WriterFactory):
    def __init__(self, expected_name: str, output: BinaryIO) -> None:
        self._expected_name = expected_name.rstrip("/\\")
        self._output = output
        self.created = 0

    def create(self, filename: str) -> Py7zIO:
        if filename.rstrip("/\\") != self._expected_name or self.created:
            raise ArchiveBackendCorruptedError(
                "7z extraction returned an unexpected member identity"
            )
        self.created += 1
        return _OutputIO(self._output)


class Py7zrBackend:
    name = "py7zr"

    def __init__(self) -> None:
        self.version = version("py7zr")

    def inspect(
        self, path: Path, *, policy: ProcessingPolicy
    ) -> ArchiveInspection:
        try:
            with py7zr.SevenZipFile(path, mode="r", password=None) as archive:
                if archive.needs_password():
                    raise ArchiveBackendPasswordError(
                        "7z archive requires a password"
                    )
                infos = archive.list()
                archive_info = archive.archiveinfo()
        except ArchiveBackendPasswordError:
            raise
        except PasswordRequired as exc:
            raise ArchiveBackendPasswordError(
                "7z archive requires a password"
            ) from exc
        except UnsupportedCompressionMethodError as exc:
            raise ArchiveBackendUnsupportedError(
                "7z compression method is unsupported"
            ) from exc
        except DecompressionBombError as exc:
            raise ArchiveBackendLimitError(
                "py7zr rejected a probable decompression bomb",
                code=ErrorCode.MAX_COMPRESSION_RATIO_EXCEEDED,
            ) from exc
        except (Bad7zFile, CrcError, DecompressionError, OSError, EOFError, ValueError) as exc:
            raise ArchiveBackendCorruptedError(
                "7z structure could not be inspected"
            ) from exc

        if len(infos) > policy.max_archive_entries:
            raise ArchiveBackendLimitError(
                "7z entry count exceeds the configured limit",
                code=ErrorCode.MAX_ARCHIVE_ENTRIES_EXCEEDED,
            )
        members = tuple(
            ArchiveMemberInfo(
                ordinal=ordinal,
                name=info.filename,
                is_directory=info.is_directory,
                is_symbolic_link=info.is_symlink,
                size=info.uncompressed,
                compressed_size=info.compressed,
                encrypted=False,
                token=ArchiveMemberToken(ordinal=ordinal, name=info.filename),
                supported=(info.is_file or info.is_directory or info.is_symlink),
            )
            for ordinal, info in enumerate(infos)
        )
        return ArchiveInspection(
            members=members,
            details={
                "backend": self.name,
                "backend_version": self.version,
                "solid": archive_info.solid,
                "blocks": archive_info.blocks,
                "methods": tuple(archive_info.method_names),
            },
        )

    def write_member(
        self,
        path: Path,
        token: ArchiveMemberToken,
        output: BinaryIO,
        *,
        policy: ProcessingPolicy,
    ) -> None:
        factory = _SingleMemberFactory(token.name, output)
        try:
            with py7zr.SevenZipFile(path, mode="r", password=None) as archive:
                if archive.needs_password():
                    raise ArchiveBackendPasswordError(
                        "7z archive requires a password"
                    )
                infos = archive.list()
                try:
                    info = infos[token.ordinal]
                except IndexError as exc:
                    raise ArchiveBackendCorruptedError(
                        "7z member identity changed during processing"
                    ) from exc
                if info.filename != token.name or not info.is_file:
                    raise ArchiveBackendCorruptedError(
                        "7z member identity changed during processing"
                    )
                archive.extract(targets=[token.name], factory=factory)
            if factory.created != 1:
                raise ArchiveBackendCorruptedError(
                    "7z member produced no deterministic output"
                )
        except (
            ArchiveBackendCorruptedError,
            ArchiveBackendPasswordError,
        ):
            raise
        except PasswordRequired as exc:
            raise ArchiveBackendPasswordError(
                "7z archive requires a password"
            ) from exc
        except UnsupportedCompressionMethodError as exc:
            raise ArchiveBackendUnsupportedError(
                "7z compression method is unsupported"
            ) from exc
        except DecompressionBombError as exc:
            raise ArchiveBackendLimitError(
                "py7zr rejected a probable decompression bomb",
                code=ErrorCode.MAX_COMPRESSION_RATIO_EXCEEDED,
            ) from exc
        except (Bad7zFile, CrcError, DecompressionError, OSError, EOFError, ValueError) as exc:
            raise ArchiveBackendCorruptedError(
                "7z member could not be decoded"
            ) from exc
