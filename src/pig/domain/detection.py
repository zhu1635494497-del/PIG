from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from pig.domain.enums import NodeFormat, NodeKind


@dataclass(frozen=True, slots=True, kw_only=True)
class DetectionResult:
    kind: NodeKind
    format: NodeFormat
    method: str
    confidence: float
    details: dict[str, object]


_EXTENSIONS: dict[str, NodeFormat] = {
    ".zip": NodeFormat.ZIP,
    ".rar": NodeFormat.RAR,
    ".7z": NodeFormat.SEVEN_Z,
    ".msg": NodeFormat.MSG,
    ".eml": NodeFormat.EML,
    ".xlsx": NodeFormat.XLSX,
    ".xls": NodeFormat.XLS,
    ".csv": NodeFormat.CSV,
    ".pdf": NodeFormat.PDF,
    ".docx": NodeFormat.DOCX,
    ".doc": NodeFormat.DOC,
    ".pptx": NodeFormat.PPTX,
    ".ppt": NodeFormat.PPT,
    ".txt": NodeFormat.TXT,
    ".jpg": NodeFormat.JPG,
    ".jpeg": NodeFormat.JPEG,
    ".png": NodeFormat.PNG,
}

_CONTAINERS = {
    NodeFormat.FOLDER,
    NodeFormat.ZIP,
    NodeFormat.RAR,
    NodeFormat.SEVEN_Z,
    NodeFormat.MSG,
    NodeFormat.EML,
}

_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_SEVEN_Z_SIGNATURE = b"7z\xbc\xaf\x27\x1c"
_RAR_SIGNATURES = (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")


def detect_node_format(
    original_name: str, signature: bytes, *, is_directory: bool = False
) -> DetectionResult:
    if is_directory:
        return DetectionResult(
            kind=NodeKind.CONTAINER,
            format=NodeFormat.FOLDER,
            method="filesystem_kind",
            confidence=1.0,
            details={},
        )
    extension = PurePosixPath(original_name.replace("\\", "/")).suffix.lower()
    extension_format = _EXTENSIONS.get(extension)
    if extension_format in {NodeFormat.XLSX, NodeFormat.DOCX, NodeFormat.PPTX}:
        detected = extension_format
        method = "terminal_office_extension"
        confidence = 0.9
    elif signature.startswith(_ZIP_SIGNATURES):
        detected = NodeFormat.ZIP
        method = "zip_signature"
        confidence = 1.0
    elif signature.startswith(_SEVEN_Z_SIGNATURE):
        detected = NodeFormat.SEVEN_Z
        method = "seven_z_signature"
        confidence = 1.0
    elif signature.startswith(_RAR_SIGNATURES):
        detected = NodeFormat.RAR
        method = "rar_signature"
        confidence = 1.0
    elif extension_format is not None:
        detected = extension_format
        method = "extension"
        confidence = 0.8
    else:
        detected = NodeFormat.UNKNOWN
        method = "fallback"
        confidence = 0.0
    return DetectionResult(
        kind=(NodeKind.CONTAINER if detected in _CONTAINERS else NodeKind.FILE),
        format=detected,
        method=method,
        confidence=confidence,
        details={"extension": extension, "signature_hex": signature[:8].hex()},
    )
