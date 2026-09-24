from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

@dataclass(slots=True)
class ApplicationError(Exception):
    """Expected, structured failure at an application boundary."""

    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
