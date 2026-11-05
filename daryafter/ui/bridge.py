"""Moves engine events (engine thread) onto the Qt thread."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class EngineBridge(QObject):
    event = Signal(object)

    def push(self, ev) -> None:           # called from the engine thread
        self.event.emit(ev)
