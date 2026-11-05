"""Ask for a new password, a new + old one, or the old one (to remove the lock)."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from ..core.applock import check_new_password
from ..core.settings import Settings
from ..i18n import tr

SET, CHANGE, REMOVE = "set", "change", "remove"


def _password_edit() -> QLineEdit:
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    return edit


class PasswordDialog(QDialog):
    def __init__(self, settings: Settings, mode: str, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.mode = mode
        titles = {SET: tr("Set a password"), CHANGE: tr("Change password"), REMOVE: tr("Remove password")}
        self.setWindowTitle(titles[mode])
        self.setMinimumWidth(380)
        self.current = _password_edit()
        self.new = _password_edit()
        self.confirm = _password_edit()
        form = QFormLayout()
        form.setVerticalSpacing(10)
        if mode in (CHANGE, REMOVE):
            form.addRow(tr("Current password"), self.current)
        if mode in (SET, CHANGE):
            form.addRow(tr("New password"), self.new)
            form.addRow(tr("Type it again"), self.confirm)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        note = QLabel(tr("There is no way to recover a forgotten password."))
        note.setProperty("muted", True)
        note.setWordWrap(True)

        cancel = QPushButton(tr("Cancel"))
        ok = QPushButton(tr("Remove") if mode == REMOVE else tr("OK"))
        ok.setProperty("primary", True)
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.addLayout(form)
        if mode != REMOVE:
            root.addWidget(note)
        root.addWidget(self.error)
        root.addLayout(buttons)

    def problem(self) -> str:
        """Returns "" when everything typed is fine, otherwise the message to show."""
        if self.mode in (CHANGE, REMOVE) and not self._settings.check_password(self.current.text()):
            return tr("The current password is wrong.")
        if self.mode in (SET, CHANGE):
            return tr(check_new_password(self.new.text(), self.confirm.text()))
        return ""

    def accept(self) -> None:
        message = self.problem()
        if message:
            self.error.setStyleSheet("color: #D64545;")
            self.error.setText(message)
            return
        super().accept()

    def new_password(self) -> str:
        """The password to store; empty when the lock is being removed."""
        return "" if self.mode == REMOVE else self.new.text()
