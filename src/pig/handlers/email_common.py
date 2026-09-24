from __future__ import annotations

from typing import Mapping, Optional

from pig.domain.enums import MetadataValueType
from pig.handlers.base import MetadataDescriptor


_HEADER_KEYS = (
    "subject",
    "from",
    "to",
    "cc",
    "bcc",
    "date",
    "message_id",
)


def email_metadata(
    values: Mapping[str, Optional[str]], *, provenance: str
) -> tuple[MetadataDescriptor, ...]:
    descriptors: list[MetadataDescriptor] = []
    for key in _HEADER_KEYS:
        value = values.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if not normalized:
            continue
        descriptors.append(
            MetadataDescriptor(
                namespace="email",
                key=key,
                value_type=MetadataValueType.TEXT,
                value_text=normalized,
                provenance=provenance,
            )
        )
    return tuple(descriptors)
