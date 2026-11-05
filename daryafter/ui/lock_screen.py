"""The page that replaces the main window's content while the app is locked."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..branding import APP_NAME
from ..i18n import tr
from . import icons, theme


class LockScreen(QWidget):
    """Asks for the password. It only reports what was typed; the check happens elsewhere."""

    unlock_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._deadline = 0.0
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(APP_NAME)
        title.setProperty("heading", True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel(tr("The app is locked. Downloads keep running in the background."))
        hint.setProperty("muted", True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText(tr("Password"))
        self.edit.setFixedWidth(280)
        self.button = QPushButton(tr("Unlock"))
        self.button.setProperty("primary", True)
        self.button.setFixedWidth(280)
        self.error = QLabel("")
        self.error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error.setWordWrap(True)
        self.edit.returnPressed.connect(self._submit)
        self.button.clicked.connect(self._submit)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)

        centre = Qt.AlignmentFlag.AlignHCenter
        col = QVBoxLayout(self)
        col.setContentsMargins(32, 32, 32, 32)
        col.setSpacing(12)
        col.addStretch(1)
        col.addWidget(self.icon_label, 0, centre)
        col.addWidget(title, 0, centre)
        col.addWidget(hint, 0, centre)
        col.addSpacing(8)
        col.addWidget(self.edit, 0, centre)
        col.addWidget(self.button, 0, centre)
        col.addWidget(self.error, 0, centre)
        col.addStretch(2)
        self.refresh_icon()

    def refresh_icon(self) -> None:
        self.icon_label.setPixmap(icons.icon("lock", theme.colors()["accent"], 48).pixmap(48, 48))

    # ---- state ---------------------------------------------------------
    def reset(self) -> None:
        """Called every time the app locks: empty field, no old message, no old countdown."""
        self._timer.stop()
        self._deadline = 0.0
        self.edit.clear()
        self.error.setText("")
        self._set_input_enabled(True)
        self.refresh_icon()

    def focus_input(self) -> None:
        self.edit.setFocus()

    def show_failure(self, wait: float) -> None:
        self._show_error(tr("Wrong password."))
        if wait > 0:
            self.block_for(wait)
        else:
            self.focus_input()

    def block_for(self, seconds: float) -> None:
        """Refuse input for a while after too many wrong passwords."""
        self._deadline = time.monotonic() + seconds
        self._set_input_enabled(False)
        self._tick()
        self._timer.start()

    # ---- internals -----------------------------------------------------
    def _submit(self) -> None:
        if self._deadline > time.monotonic():
            return
        text = self.edit.text()
        self.edit.clear()                      # never keep the typed password around
        if text:
            self.unlock_requested.emit(text)

    def _tick(self) -> None:
        left = math.ceil(self._deadline - time.monotonic())
        if left <= 0:
            self._timer.stop()
            self.error.setText("")
            self._set_input_enabled(True)
            self.focus_input()
        else:
            self._show_error(tr("Too many wrong passwords. Try again in {s} s.").format(s=left))

    def _set_input_enabled(self, enabled: bool) -> None:
        self.edit.setEnabled(enabled)
        self.button.setEnabled(enabled)

    def _show_error(self, text: str) -> None:
        self.error.setStyleSheet(f"color: {theme.colors()['bad']};")
        self.error.setText(text)
