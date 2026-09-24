from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessingPolicy:
    max_depth: int = 20
    max_node_count: int = 100_000
    max_archive_entries: int = 50_000
    max_email_parts: int = 10_000
    max_single_file_size: int = 2 * 1024 * 1024 * 1024
    max_total_expanded_size: int = 20 * 1024 * 1024 * 1024
    max_compression_ratio: float = 200.0
    io_chunk_size: int = 1024 * 1024
    max_external_listing_size: int = 64 * 1024 * 1024
    external_process_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        positive_integer_limits = (
            self.max_depth,
            self.max_node_count,
            self.max_archive_entries,
            self.max_email_parts,
            self.max_single_file_size,
            self.io_chunk_size,
            self.max_external_listing_size,
        )
        if any(value <= 0 for value in positive_integer_limits):
            raise ValueError("all integer processing limits must be positive")
        if self.max_total_expanded_size < 0:
            raise ValueError("max_total_expanded_size must be nonnegative")
        if self.max_compression_ratio <= 0:
            raise ValueError("max_compression_ratio must be positive")
        if self.external_process_timeout_seconds <= 0:
            raise ValueError("external_process_timeout_seconds must be positive")

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)
