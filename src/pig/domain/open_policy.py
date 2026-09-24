from __future__ import annotations

from dataclasses import dataclass, field

from pig.domain.enums import NodeFormat


DEFAULT_OPEN_FORMATS = frozenset(
    {
        NodeFormat.XLSX,
        NodeFormat.XLS,
        NodeFormat.CSV,
        NodeFormat.PDF,
        NodeFormat.DOCX,
        NodeFormat.DOC,
        NodeFormat.PPTX,
        NodeFormat.PPT,
        NodeFormat.TXT,
        NodeFormat.JPG,
        NodeFormat.JPEG,
        NodeFormat.PNG,
        NodeFormat.MSG,
        NodeFormat.EML,
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenPolicy:
    allowed_formats: frozenset[NodeFormat] = field(
        default_factory=lambda: DEFAULT_OPEN_FORMATS
    )
    verification_chunk_size: int = 1024 * 1024
    maximum_working_file_size: int = 2 * 1024 * 1024 * 1024
    stability_retries: int = 1

    def __post_init__(self) -> None:
        if not self.allowed_formats:
            raise ValueError("allowed_formats must not be empty")
        if any(not isinstance(item, NodeFormat) for item in self.allowed_formats):
            raise ValueError("allowed_formats contains an invalid format")
        if self.verification_chunk_size <= 0:
            raise ValueError("verification_chunk_size must be positive")
        if self.maximum_working_file_size <= 0:
            raise ValueError("maximum_working_file_size must be positive")
        if self.stability_retries < 0:
            raise ValueError("stability_retries must be nonnegative")
