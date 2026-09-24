from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogPolicy:
    max_search_query_length: int = 256
    max_search_page_size: int = 200
    max_manifest_size: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_search_query_length <= 0:
            raise ValueError("max_search_query_length must be positive")
        if self.max_search_page_size <= 0:
            raise ValueError("max_search_page_size must be positive")
        if self.max_manifest_size <= 0:
            raise ValueError("max_manifest_size must be positive")
