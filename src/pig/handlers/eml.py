from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email import policy as email_policy
from email.message import Message
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path
from typing import Optional, Sequence

from pig.domain.enums import (
    ArtifactRole,
    ArtifactScope,
    ErrorCategory,
    ErrorCode,
    MetadataValueType,
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
    MetadataDescriptor,
)
from pig.handlers.email_common import email_metadata


@dataclass(frozen=True, slots=True)
class _EmlAttachmentToken:
    ordinal: int
    embedded: bool


class EmlHandler:
    name = "eml-stdlib"
    version = "1.0"
    format = NodeFormat.EML
    relationship_type = RelationshipType.EMAIL_ATTACHMENT

    def inspect(
        self, path: Path, policy: ProcessingPolicy
    ) -> ContainerInspection:
        message = self._parse(path, policy)
        parts = self._attachment_parts(message, policy)
        children: list[ChildDescriptor] = []
        for ordinal, (part, embedded) in enumerate(parts):
            name = self._attachment_name(part, ordinal, embedded)
            path_decision = evaluate_archive_entry_path(
                name, is_symbolic_link=False
            )
            children.append(
                ChildDescriptor(
                    ordinal=ordinal,
                    discovery_key=f"eml-part:{ordinal}",
                    original_name=name,
                    safe_parts=path_decision.safe_parts,
                    is_directory=False,
                    declared_size=None,
                    token=_EmlAttachmentToken(ordinal, embedded),
                    relationship_type=(
                        RelationshipType.EMBEDDED_MESSAGE
                        if embedded
                        else RelationshipType.EMAIL_ATTACHMENT
                    ),
                    media_type=part.get_content_type(),
                    blocked_status=(
                        None
                        if path_decision.allowed
                        else NodeProcessingStatus.SECURITY_BLOCKED
                    ),
                    error_code=path_decision.error_code,
                    error_category=(
                        None if path_decision.allowed else ErrorCategory.SECURITY
                    ),
                )
            )
        headers = {
            "subject": self._header(message, "subject"),
            "from": self._header(message, "from"),
            "to": self._header(message, "to"),
            "cc": self._header(message, "cc"),
            "bcc": self._header(message, "bcc"),
            "date": self._header(message, "date"),
            "message_id": self._header(message, "message-id"),
        }
        metadata = list(email_metadata(headers, provenance="eml-stdlib"))
        defects = tuple(str(defect) for defect in message.defects)
        if defects:
            metadata.append(
                MetadataDescriptor(
                    namespace="email",
                    key="parser_defects",
                    value_type=MetadataValueType.JSON,
                    value_json=list(defects),
                    provenance="eml-stdlib",
                )
            )
        return ContainerInspection(children=tuple(children), metadata=tuple(metadata))

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
        if not isinstance(token, _EmlAttachmentToken):
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.FAILED,
                code=ErrorCode.HANDLER_FAILURE,
                category=ErrorCategory.INTERNAL,
                message="EML attachment token is invalid",
            )
        try:
            message = self._parse(path, policy)
            parts = self._attachment_parts(message, policy)
            part, embedded = parts[token.ordinal]
            if embedded != token.embedded:
                raise ValueError("EML attachment identity changed during processing")
            payload = self._payload(part, embedded)
        except HandlerOutcomeError:
            raise
        except (IndexError, LookupError, UnicodeError, ValueError, TypeError) as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.CORRUPTED,
                code=ErrorCode.CORRUPTED_CONTAINER,
                category=ErrorCategory.FORMAT,
                message=f"EML attachment could not be decoded: {type(exc).__name__}",
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

    @staticmethod
    def _parse(path: Path, policy: ProcessingPolicy) -> Message:
        try:
            size = path.stat().st_size
            if size > policy.max_single_file_size:
                raise HandlerOutcomeError(
                    status=NodeProcessingStatus.LIMIT_EXCEEDED,
                    code=ErrorCode.MAX_SINGLE_FILE_SIZE_EXCEEDED,
                    category=ErrorCategory.RESOURCE_LIMIT,
                    message="EML size exceeds the configured single-file limit",
                )
            with path.open("rb") as stream:
                return BytesParser(policy=email_policy.default).parse(stream)
        except HandlerOutcomeError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise HandlerOutcomeError(
                status=NodeProcessingStatus.CORRUPTED,
                code=ErrorCode.CORRUPTED_CONTAINER,
                category=ErrorCategory.FORMAT,
                message=f"EML structure could not be parsed: {type(exc).__name__}",
            ) from exc

    @staticmethod
    def _attachment_parts(
        message: Message, policy: ProcessingPolicy
    ) -> Sequence[tuple[Message, bool]]:
        attachments: list[tuple[Message, bool]] = []
        stack = [message]
        part_count = 0
        while stack:
            part = stack.pop()
            part_count += 1
            if part_count > policy.max_email_parts:
                raise HandlerOutcomeError(
                    status=NodeProcessingStatus.LIMIT_EXCEEDED,
                    code=ErrorCode.MAX_NODE_COUNT_EXCEEDED,
                    category=ErrorCategory.RESOURCE_LIMIT,
                    message="EML MIME part count exceeds the configured limit",
                )
            embedded = part is not message and part.get_content_type() == "message/rfc822"
            if embedded:
                attachments.append((part, True))
                continue
            if part.is_multipart():
                payload = part.get_payload()
                if isinstance(payload, list):
                    stack.extend(reversed(payload))
                continue
            if part.get_content_disposition() == "attachment" or part.get_filename():
                attachments.append((part, False))
        return tuple(attachments)

    @staticmethod
    def _attachment_name(part: Message, ordinal: int, embedded: bool) -> str:
        filename = part.get_filename()
        if filename:
            return str(filename)
        if embedded:
            payload = part.get_payload()
            if isinstance(payload, list) and payload:
                subject = payload[0].get("subject")
                if subject:
                    return f"{str(subject).strip() or 'embedded-message'}.eml"
            return f"embedded-message-{ordinal}.eml"
        return f"attachment-{ordinal}.bin"

    @staticmethod
    def _payload(part: Message, embedded: bool) -> bytes:
        if embedded:
            payload = part.get_payload()
            if isinstance(payload, list) and payload:
                return payload[0].as_bytes(policy=email_policy.default)
            decoded = part.get_payload(decode=True)
            if isinstance(decoded, bytes):
                return decoded
            raise ValueError("embedded EML has no message payload")
        decoded = part.get_payload(decode=True)
        if isinstance(decoded, bytes):
            return decoded
        raw = part.get_payload()
        if isinstance(raw, str):
            charset = part.get_content_charset() or "utf-8"
            return raw.encode(charset, errors="replace")
        raise ValueError("attachment has no byte payload")

    @staticmethod
    def _header(message: Message, name: str) -> Optional[str]:
        values = message.get_all(name, [])
        if not values:
            return None
        return ", ".join(str(value) for value in values)
