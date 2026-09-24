from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotImportPolicy:
    """Central resource limits for immutable Original Snapshot capture."""

    max_input_count: int = 1_000
    max_entry_count: int = 100_000
    max_single_file_size: int = 2 * 1024 * 1024 * 1024
    max_total_size: int = 20 * 1024 * 1024 * 1024
    io_chunk_size: int = 1024 * 1024

    def __post_init__(self) -> None:
        values = (
            self.max_input_count,
            self.max_entry_count,
            self.max_single_file_size,
            self.io_chunk_size,
        )
        if any(value <= 0 for value in values):
            raise ValueError("snapshot import limits must be positive")
        if self.max_total_size < 0:
            raise ValueError("max_total_size must be nonnegative")

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)
