from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Mapping, Optional, Protocol, Sequence

from pig.domain.enums import (
    ArtifactRole,
    ArtifactScope,
    ErrorCategory,
    ErrorCode,
    NodeFormat,
    NodeProcessingStatus,
    RelationshipType,
)
from pig.domain.archive_security import evaluate_archive_entry_path
from pig.domain.processing_policy import ProcessingPolicy
from pig.handlers.base import (
    ArtifactWriteSession,
    ChildDescriptor,
    ChildMaterialization,
    ContainerInspection,
    HandlerOutcomeError,
)
from pig.handlers.email_common import email_metadata


class MsgAttachmentKind(str, Enum):
    DATA = "DATA"
    EMBEDDED_MESSAGE = "EMBEDDED_MESSAGE"
    WEB_REFERENCE = "WEB_REFERENCE"
    BROKEN = "BROKEN"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True, kw_only=True)
class MsgAttachmentInfo:
    ordinal: int
    name: str
    kind: MsgAttachmentKind
    media_type: Optional[str] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MsgInspection:
    headers: Mapping[str, Optional[str]]
    attachments: Sequence[MsgAttachmentInfo]


@dataclass(frozen=True, slots=True, kw_only=True)
class MsgAttachmentToken:
    ordinal: int
    kind: MsgAttachmentKind


class MsgBackendError(Exception):
    pass


class MsgBackendCorruptedError(MsgBackendError):
    pass


class MsgBackendUnsupportedError(MsgBackendError):
    pass


class MsgBackendLimitError(MsgBackendError):
    pass


class MsgBackend(Protocol):
    name: str
    version: str

    def inspect(self, path: Path, *, max_attachments: int) -> MsgInspection: ...

    def read_attachment(self, path: Path, token: MsgAttachmentToken) -> bytes: ...


class MsgHandler:
    format = NodeFormat.MSG
    relationship_type = RelationshipType.EMAIL_ATTACHMENT

    def __init__(self, backend: MsgBackend) -> None:
        self._backend = backend
        self.name = f"msg-{backend.name}"
        self.version = backend.version

    def inspect(
        self, path: Path, policy: ProcessingPolicy
    ) -> ContainerInspection:
        try:
            if path.stat().st_size > policy.max_single_file_size:
                raise HandlerOutcomeError(
                    status=NodeProcessingStatus.LIMIT_EXCEEDED,
                    code=ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED,
                    category=ErrorCategory.RESOURCE_LIMIT,
                    message="MSG size exceeds the configured single-file limit",
                )
            inspection = self._backend.inspect(
                path, max_attachments=policy.max_email_parts
            )
            if len(inspection.attachments) > policy.max_email_parts:
                raise MsgBackendLimitError(
                    "MSG attachment count exceeds the configured limit"
                )
        except HandlerOutcomeError:
            raise
        except MsgBackendLimitError as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.LIMIT_EXCEEDED,
                code=ErrorCode.MAX_NODE_COUNT_EXCEEDED,
                category=ErrorCategory.RESOURCE_LIMIT,
                message=str(exc) or "MSG attachment count exceeds the configured limit",
            ) from exc
        except MsgBackendUnsupportedError as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.UNSUPPORTED,
                code=ErrorCode.UNSUPPORTED_FEATURE,
                category=ErrorCategory.FORMAT,
                message=str(exc) or "MSG type is unsupported by the configured backend",
            ) from exc
        except (MsgBackendCorruptedError, OSError) as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.CORRUPTED,
                code=ErrorCode.CORRUPTED_CONTAINER,
                category=ErrorCategory.FORMAT,
                message=str(exc) or "MSG structure could not be parsed",
            ) from exc

        children: list[ChildDescriptor] = []
        for attachment in inspection.attachments:
            status: Optional[NodeProcessingStatus] = None
            code: Optional[ErrorCode] = None
            category: Optional[ErrorCategory] = None
            if attachment.kind == MsgAttachmentKind.WEB_REFERENCE:
                status = NodeProcessingStatus.SECURITY_BLOCKED
                code = ErrorCode.UNSUPPORTED_FEATURE
                category = ErrorCategory.SECURITY
            elif attachment.kind == MsgAttachmentKind.BROKEN:
                status = NodeProcessingStatus.CORRUPTED
                code = ErrorCode.CORRUPTED_CONTAINER
                category = ErrorCategory.FORMAT
            elif attachment.kind == MsgAttachmentKind.UNSUPPORTED:
                status = NodeProcessingStatus.UNSUPPORTED
                code = ErrorCode.UNSUPPORTED_FEATURE
                category = ErrorCategory.FORMAT
            path_decision = evaluate_archive_entry_path(
                attachment.name, is_symbolic_link=False
            )
            if not path_decision.allowed:
                status = NodeProcessingStatus.SECURITY_BLOCKED
                code = path_decision.error_code
                category = ErrorCategory.SECURITY
            embedded = attachment.kind == MsgAttachmentKind.EMBEDDED_MESSAGE
            children.append(
                ChildDescriptor(
                    ordinal=attachment.ordinal,
                    discovery_key=f"msg-attachment:{attachment.ordinal}",
                    original_name=attachment.name,
                    safe_parts=path_decision.safe_parts,
                    is_directory=False,
                    declared_size=None,
                    token=MsgAttachmentToken(
                        ordinal=attachment.ordinal, kind=attachment.kind
                    ),
                    blocked_status=status,
                    error_code=code,
                    error_category=category,
                    relationship_type=(
                        RelationshipType.EMBEDDED_MESSAGE
                        if embedded
                        else RelationshipType.EMAIL_ATTACHMENT
                    ),
                    media_type=attachment.media_type,
                )
            )
        return ContainerInspection(
            children=tuple(children),
            metadata=email_metadata(
                inspection.headers, provenance=f"msg:{self._backend.name}"
            ),
        )

    def materialize(
        self,
        path: Path,
        child: ChildDescriptor,
        artifact_id: str,
        store: ArtifactWriteSession,
        policy: ProcessingPolicy,
        observed_at: datetime,
    ) -> Optional[ChildMaterialization]:
        token = child.token
        if not isinstance(token, MsgAttachmentToken):
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.FAILED,
                code=ErrorCode.HANDLER_FAILURE,
                category=ErrorCategory.INTERNAL,
                message="MSG attachment token is invalid",
            )
        try:
            payload = self._backend.read_attachment(path, token)
        except MsgBackendUnsupportedError as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.UNSUPPORTED,
                code=ErrorCode.UNSUPPORTED_FEATURE,
                category=ErrorCategory.FORMAT,
                message=str(exc) or "MSG attachment type is unsupported",
            ) from exc
        except (MsgBackendCorruptedError, OSError) as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.CORRUPTED,
                code=ErrorCode.CORRUPTED_CONTAINER,
                category=ErrorCategory.FORMAT,
                message=str(exc) or "MSG attachment could not be read",
            ) from exc
        stored = store.write_stream(
            artifact_id,
            BytesIO(payload),
            max_single_file_size=policy.max_single_file_size,
            max_total_expanded_size=policy.max_total_expanded_size,
            chunk_size=policy.io_chunk_size,
        )
        return ChildMaterialization(
            role=ArtifactRole.EXTRACTED_ARTIFACT,
            scope=ArtifactScope.PROJECT_WORKSPACE,
            locator=stored.storage_key,
            size=stored.size,
            sha256=stored.sha256,
            signature=stored.signature,
            observed_at=observed_at,
        )
