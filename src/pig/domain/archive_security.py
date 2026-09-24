from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional

from pig.domain.enums import ErrorCode


_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchivePathDecision:
    allowed: bool
    safe_parts: tuple[str, ...]
    error_code: Optional[ErrorCode] = None


def evaluate_archive_entry_path(
    original_name: str, *, is_symbolic_link: bool
) -> ArchivePathDecision:
    """Platform-neutral policy; the raw name is never used as a physical path."""

    if is_symbolic_link:
        return ArchivePathDecision(
            allowed=False,
            safe_parts=(),
            error_code=ErrorCode.SYMLINK_BLOCKED,
        )
    if "\x00" in original_name:
        return ArchivePathDecision(
            allowed=False,
            safe_parts=(),
            error_code=ErrorCode.INVALID_FILENAME,
        )
    normalized = original_name.replace("\\", "/")
    lowered = normalized.lower()
    if lowered.startswith(("//?/", "//./")):
        return ArchivePathDecision(
            allowed=False,
            safe_parts=(),
            error_code=ErrorCode.DEVICE_PATH_BLOCKED,
        )
    if normalized.startswith("/") or _DRIVE_PREFIX.match(normalized):
        return ArchivePathDecision(
            allowed=False,
            safe_parts=(),
            error_code=ErrorCode.ABSOLUTE_PATH_BLOCKED,
        )
    raw_parts = PurePosixPath(normalized).parts
    if not raw_parts or any(part == ".." for part in raw_parts):
        return ArchivePathDecision(
            allowed=False,
            safe_parts=(),
            error_code=ErrorCode.PATH_TRAVERSAL_BLOCKED,
        )
    safe_parts = tuple(part for part in raw_parts if part not in {"", "."})
    if not safe_parts:
        return ArchivePathDecision(
            allowed=False,
            safe_parts=(),
            error_code=ErrorCode.INVALID_FILENAME,
        )
    return ArchivePathDecision(allowed=True, safe_parts=safe_parts)
