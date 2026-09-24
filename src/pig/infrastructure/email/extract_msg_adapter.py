from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from typing import Callable, Optional

import extract_msg
from extract_msg.enums import AttachmentType
from extract_msg.exceptions import (
    InvalidFileFormatError,
    StandardViolationError,
    UnrecognizedMSGTypeError,
    UnsupportedMSGTypeError,
)
from olefile.olefile import OleFileError

from pig.handlers.msg import (
    MsgAttachmentInfo,
    MsgAttachmentKind,
    MsgAttachmentToken,
    MsgBackendCorruptedError,
    MsgBackendLimitError,
    MsgBackendUnsupportedError,
    MsgInspection,
)


MsgOpener = Callable[..., object]


class ExtractMsgBackend:
    """Narrow adapter over extract-msg; no third-party objects escape this class."""

    name = "extract-msg"

    def __init__(self, opener: MsgOpener = extract_msg.openMsg) -> None:
        self._open = opener
        self.version = version("extract-msg")

    def inspect(self, path: Path, *, max_attachments: int) -> MsgInspection:
        try:
            with self._open(path, strict=True, delayAttachments=False) as message:
                attachments = tuple(message.attachments)
                if len(attachments) > max_attachments:
                    raise MsgBackendLimitError(
                        "MSG attachment count exceeds the configured limit"
                    )
                discovered = tuple(
                    MsgAttachmentInfo(
                        ordinal=ordinal,
                        name=self._name(attachment, ordinal),
                        kind=self._kind(attachment.type),
                        media_type=self._media_type(attachment),
                    )
                    for ordinal, attachment in enumerate(attachments)
                )
                headers = {
                    "subject": self._text(getattr(message, "subject", None)),
                    "from": self._text(getattr(message, "sender", None)),
                    "to": self._text(getattr(message, "to", None)),
                    "cc": self._text(getattr(message, "cc", None)),
                    "bcc": self._text(getattr(message, "bcc", None)),
                    "date": self._text(getattr(message, "date", None)),
                    "message_id": self._text(getattr(message, "messageId", None)),
                }
            return MsgInspection(headers=headers, attachments=discovered)
        except MsgBackendLimitError:
            raise
        except (UnsupportedMSGTypeError, UnrecognizedMSGTypeError) as exc:
            raise MsgBackendUnsupportedError(str(exc)) from exc
        except (InvalidFileFormatError, StandardViolationError, OleFileError) as exc:
            raise MsgBackendCorruptedError(str(exc)) from exc

    def read_attachment(self, path: Path, token: MsgAttachmentToken) -> bytes:
        try:
            with self._open(path, strict=True, delayAttachments=False) as message:
                attachments = tuple(message.attachments)
                try:
                    attachment = attachments[token.ordinal]
                except IndexError as exc:
                    raise MsgBackendCorruptedError(
                        "MSG attachment identity changed during processing"
                    ) from exc
                actual_kind = self._kind(attachment.type)
                if actual_kind != token.kind:
                    raise MsgBackendCorruptedError(
                        "MSG attachment type changed during processing"
                    )
                data = attachment.data
                if token.kind == MsgAttachmentKind.EMBEDDED_MESSAGE:
                    if not hasattr(data, "exportBytes"):
                        raise MsgBackendCorruptedError(
                            "embedded MSG attachment has no exportable message data"
                        )
                    payload = data.exportBytes()
                elif token.kind == MsgAttachmentKind.DATA:
                    payload = data
                else:
                    raise MsgBackendUnsupportedError(
                        f"MSG attachment kind is not materializable: {token.kind.value}"
                    )
                if not isinstance(payload, bytes):
                    raise MsgBackendCorruptedError(
                        "MSG attachment did not yield a byte payload"
                    )
                return payload
        except (MsgBackendCorruptedError, MsgBackendUnsupportedError):
            raise
        except (UnsupportedMSGTypeError, UnrecognizedMSGTypeError) as exc:
            raise MsgBackendUnsupportedError(str(exc)) from exc
        except (InvalidFileFormatError, StandardViolationError, OleFileError) as exc:
            raise MsgBackendCorruptedError(str(exc)) from exc

    @staticmethod
    def _kind(value: AttachmentType) -> MsgAttachmentKind:
        if value in {AttachmentType.DATA, AttachmentType.SIGNED}:
            return MsgAttachmentKind.DATA
        if value in {AttachmentType.MSG, AttachmentType.SIGNED_EMBEDDED}:
            return MsgAttachmentKind.EMBEDDED_MESSAGE
        if value == AttachmentType.WEB:
            return MsgAttachmentKind.WEB_REFERENCE
        if value == AttachmentType.BROKEN:
            return MsgAttachmentKind.BROKEN
        return MsgAttachmentKind.UNSUPPORTED

    @staticmethod
    def _name(attachment: object, ordinal: int) -> str:
        name = getattr(attachment, "name", None)
        if name:
            return str(name)
        kind = ExtractMsgBackend._kind(attachment.type)
        extension = ".msg" if kind == MsgAttachmentKind.EMBEDDED_MESSAGE else ".bin"
        return f"attachment-{ordinal}{extension}"

    @staticmethod
    def _media_type(attachment: object) -> Optional[str]:
        try:
            value = getattr(attachment, "mimetype", None)
        except Exception:
            return None
        return None if value is None else str(value)

    @staticmethod
    def _text(value: object) -> Optional[str]:
        if value is None:
            return None
        return str(value)
