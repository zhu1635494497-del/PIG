from __future__ import annotations

import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from pig.application.errors import ApplicationError
from pig.application.ports import SourceInspector
from pig.domain.enums import (
    ArtifactRole,
    ArtifactScope,
    ErrorCategory,
    ErrorCode,
    NodeFormat,
    NodeProcessingStatus,
    RelationshipType,
    SourceKind,
)
from pig.domain.processing_policy import ProcessingPolicy
from pig.handlers.base import (
    ArtifactWriteSession,
    ChildDescriptor,
    ChildMaterialization,
    ContainerInspection,
    HandlerOutcomeError,
)


class FolderHandler:
    name = "folder"
    version = "1.0"
    format = NodeFormat.FOLDER
    relationship_type = RelationshipType.FOLDER_CONTAINS

    def __init__(self, source_inspector: SourceInspector) -> None:
        self._source_inspector = source_inspector

    def inspect(
        self, path: Path, policy: ProcessingPolicy
    ) -> ContainerInspection:
        try:
            entries = []
            with os.scandir(path) as iterator:
                for entry in iterator:
                    entries.append(entry)
                    if len(entries) > policy.max_node_count:
                        raise HandlerOutcomeError(
                            status=NodeProcessingStatus.LIMIT_EXCEEDED,
                            code=ErrorCode.MAX_NODE_COUNT_EXCEEDED,
                            category=ErrorCategory.RESOURCE_LIMIT,
                            message="folder child count exceeds the configured limit",
                        )
        except HandlerOutcomeError:
            raise
        except OSError as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.FAILED,
                code=ErrorCode.HANDLER_FAILURE,
                category=ErrorCategory.PROCESSING,
                message=f"folder could not be enumerated: {type(exc).__name__}",
                retryable=True,
            ) from exc

        descriptors: list[ChildDescriptor] = []
        for ordinal, entry in enumerate(sorted(entries, key=lambda item: item.name)):
            try:
                item_stat = entry.stat(follow_symlinks=False)
            except OSError:
                descriptors.append(
                    self._blocked(
                        ordinal,
                        entry.name,
                        NodeProcessingStatus.FAILED,
                        ErrorCode.HANDLER_FAILURE,
                        ErrorCategory.PROCESSING,
                    )
                )
                continue
            mode = item_stat.st_mode
            if stat.S_ISLNK(mode):
                descriptors.append(
                    self._blocked(
                        ordinal,
                        entry.name,
                        NodeProcessingStatus.SECURITY_BLOCKED,
                        ErrorCode.SYMLINK_BLOCKED,
                        ErrorCategory.SECURITY,
                    )
                )
            elif stat.S_ISDIR(mode):
                descriptors.append(
                    ChildDescriptor(
                        ordinal=ordinal,
                        discovery_key=f"folder-entry:{entry.name}",
                        original_name=entry.name,
                        safe_parts=(entry.name,),
                        is_directory=True,
                        declared_size=None,
                        token=Path(entry.path),
                    )
                )
            elif stat.S_ISREG(mode):
                if item_stat.st_size > policy.max_single_file_size:
                    descriptors.append(
                        self._blocked(
                            ordinal,
                            entry.name,
                            NodeProcessingStatus.LIMIT_EXCEEDED,
                            ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED,
                            ErrorCategory.RESOURCE_LIMIT,
                            declared_size=item_stat.st_size,
                        )
                    )
                else:
                    descriptors.append(
                        ChildDescriptor(
                            ordinal=ordinal,
                            discovery_key=f"folder-entry:{entry.name}",
                            original_name=entry.name,
                            safe_parts=(entry.name,),
                            is_directory=False,
                            declared_size=item_stat.st_size,
                            token=Path(entry.path),
                        )
                    )
            else:
                descriptors.append(
                    self._blocked(
                        ordinal,
                        entry.name,
                        NodeProcessingStatus.UNSUPPORTED,
                        ErrorCode.UNSUPPORTED_FEATURE,
                        ErrorCategory.FORMAT,
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
            observation = self._source_inspector.inspect(
                Path(child.token), SourceKind.FILE
            )
        except ApplicationError as exc:
            if exc.code == ErrorCode.SOURCE_NOT_FOUND.value:
                status = NodeProcessingStatus.SOURCE_MISSING
                code = ErrorCode.SOURCE_NOT_FOUND
                category = ErrorCategory.SOURCE
            elif exc.code == ErrorCode.SYMLINK_BLOCKED.value:
                status = NodeProcessingStatus.SECURITY_BLOCKED
                code = ErrorCode.SYMLINK_BLOCKED
                category = ErrorCategory.SECURITY
            elif exc.code == "SOURCE_CHANGED_DURING_READ":
                status = NodeProcessingStatus.SOURCE_CHANGED
                code = ErrorCode.SOURCE_FINGERPRINT_MISMATCH
                category = ErrorCategory.SOURCE
            else:
                status = NodeProcessingStatus.FAILED
                code = ErrorCode.HANDLER_FAILURE
                category = ErrorCategory.PROCESSING
            raise HandlerOutcomeError(
                status=status,
                code=code,
                category=category,
                message=f"folder child could not be verified: {exc.code}",
                retryable=code != ErrorCode.SYMLINK_BLOCKED,
            ) from exc
        return ChildMaterialization(
            role=ArtifactRole.ORIGINAL_REFERENCE,
            scope=ArtifactScope.EXTERNAL_SOURCE,
            locator=observation.locator,
            size=observation.size or 0,
            sha256=observation.sha256 or "",
            signature=observation.signature,
            observed_at=observation.verified_at,
        )

    @staticmethod
    def _blocked(
        ordinal: int,
        name: str,
        status: NodeProcessingStatus,
        code: ErrorCode,
        category: ErrorCategory,
        declared_size: Optional[int] = None,
    ) -> ChildDescriptor:
        return ChildDescriptor(
            ordinal=ordinal,
            discovery_key=f"folder-entry:{name}",
            original_name=name,
            safe_parts=(name,),
            is_directory=False,
            declared_size=declared_size,
            token=None,
            blocked_status=status,
            error_code=code,
            error_category=category,
        )
