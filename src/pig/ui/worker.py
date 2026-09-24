from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot


class BackgroundAction(QObject):
    """Run one existing synchronous Application action off the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, action: Callable[[], object]) -> None:
        super().__init__()
        self._action = action

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(self._action())
        except Exception as exc:
            self.failed.emit(exc)
        finally:
            self.finished.emit()
