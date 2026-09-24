from __future__ import annotations

import stat
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from pig.domain.archive_security import evaluate_archive_entry_path
from pig.domain.enums import (
    ArtifactRole,
    ArtifactScope,
    ErrorCategory,
    ErrorCode,
    NodeFormat,
    NodeProcessingStatus,
    RelationshipType,
)
from pig.domain.processing_policy import ProcessingPolicy
from pig.handlers.base import (
    ArtifactWriteSession,
    ChildDescriptor,
    ChildMaterialization,
    ContainerInspection,
    HandlerOutcomeError,
)


class ZipHandler:
    name = "zip-stdlib"
    version = "1.0"
    format = NodeFormat.ZIP
    relationship_type = RelationshipType.ARCHIVE_ENTRY

    def inspect(
        self, path: Path, policy: ProcessingPolicy
    ) -> ContainerInspection:
        try:
            with zipfile.ZipFile(path, "r") as archive:
                infos = archive.infolist()
        except (zipfile.BadZipFile, OSError) as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.CORRUPTED,
                code=ErrorCode.CORRUPTED_CONTAINER,
                category=ErrorCategory.FORMAT,
                message="ZIP central directory could not be read",
            ) from exc
        if len(infos) > policy.max_archive_entries:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.LIMIT_EXCEEDED,
                code=ErrorCode.MAX_ARCHIVE_ENTRIES_EXCEEDED,
                category=ErrorCategory.RESOURCE_LIMIT,
                message="ZIP entry count exceeds the configured limit",
            )

        descriptors: list[ChildDescriptor] = []
        declared_total = 0
        for ordinal, info in enumerate(infos):
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            is_symlink = stat.S_ISLNK(unix_mode)
            decision = evaluate_archive_entry_path(
                info.filename, is_symbolic_link=is_symlink
            )
            blocked_status: Optional[NodeProcessingStatus] = None
            error_code: Optional[ErrorCode] = None
            error_category: Optional[ErrorCategory] = None
            if not decision.allowed:
                blocked_status = NodeProcessingStatus.SECURITY_BLOCKED
                error_code = decision.error_code
                error_category = ErrorCategory.SECURITY
            elif info.flag_bits & 0x1:
                blocked_status = NodeProcessingStatus.PASSWORD_REQUIRED
                error_code = ErrorCode.PASSWORD_REQUIRED
                error_category = ErrorCategory.FORMAT
            elif info.file_size > policy.max_single_file_size:
                blocked_status = NodeProcessingStatus.LIMIT_EXCEEDED
                error_code = ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED
                error_category = ErrorCategory.RESOURCE_LIMIT
            elif not info.is_dir():
                compressed = max(info.compress_size, 1)
                if info.file_size / compressed > policy.max_compression_ratio:
                    blocked_status = NodeProcessingStatus.LIMIT_EXCEEDED
                    error_code = ErrorCode.MAX_COMPRESSION_RATIO_EXCEEDED
                    error_category = ErrorCategory.RESOURCE_LIMIT
                elif declared_total + info.file_size > policy.max_total_expanded_size:
                    blocked_status = NodeProcessingStatus.LIMIT_EXCEEDED
                    error_code = ErrorCode.MAX_TOTAL_EXPANDED_SIZE_EXCEEDED
                    error_category = ErrorCategory.RESOURCE_LIMIT
                else:
                    declared_total += info.file_size
            descriptors.append(
                ChildDescriptor(
                    ordinal=ordinal,
                    discovery_key=f"zip-entry:{ordinal}",
                    original_name=info.filename,
                    safe_parts=decision.safe_parts,
                    is_directory=info.is_dir(),
                    declared_size=info.file_size,
                    token=ordinal,
                    blocked_status=blocked_status,
                    error_code=error_code,
                    error_category=error_category,
                )
            )
        return ContainerInspection(children=tuple(descriptors))

    def materialize(
        self,
        path: Path,
        child: ChildDescriptor,
        artifact_id: str,
        store: ArtifactWriteSession,
        policy: ProcessingPolicy,
        observed_at: datetime,
    ) -> Optional[ChildMaterialization]:
        if child.is_directory or child.blocked_status is not None:
            return None
        try:
            with zipfile.ZipFile(path, "r") as archive:
                info = archive.infolist()[int(child.token)]
                with archive.open(info, "r") as stream:
                    stored = store.write_stream(
                        artifact_id,
                        stream,
                        max_single_file_size=policy.max_single_file_size,
                        max_total_expanded_size=policy.max_total_expanded_size,
                        chunk_size=policy.io_chunk_size,
                    )
        except HandlerOutcomeError:
            raise
        except NotImplementedError as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.UNSUPPORTED,
                code=ErrorCode.UNSUPPORTED_FEATURE,
                category=ErrorCategory.FORMAT,
                message="ZIP compression feature is unsupported",
            ) from exc
        except RuntimeError as exc:
            if "password" in str(exc).lower() or "encrypted" in str(exc).lower():
                raise HandlerOutcomeError(
                    status=NodeProcessingStatus.PASSWORD_REQUIRED,
                    code=ErrorCode.PASSWORD_REQUIRED,
                    category=ErrorCategory.FORMAT,
                    message="ZIP entry requires a password",
                ) from exc
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.CORRUPTED,
                code=ErrorCode.CORRUPTED_CONTAINER,
                category=ErrorCategory.FORMAT,
                message="ZIP entry could not be decoded",
            ) from exc
        except (zipfile.BadZipFile, OSError, EOFError) as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.CORRUPTED,
                code=ErrorCode.CORRUPTED_CONTAINER,
                category=ErrorCategory.FORMAT,
                message="ZIP entry could not be extracted safely",
            ) from exc
        return ChildMaterialization(
            role=ArtifactRole.EXTRACTED_ARTIFACT,
            scope=ArtifactScope.PROJECT_WORKSPACE,
            locator=stored.storage_key,
            size=stored.size,
            sha256=stored.sha256,
            signature=stored.signature,
            observed_at=observed_at,
        )
