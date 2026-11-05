"""Small pieces: finished-download summary, clipboard toast, tray icon."""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QSystemTrayIcon, QVBoxLayout)

from ..core.fmt import human_size, human_speed, human_time
from ..core.models import Snapshot
from ..i18n import tr


class SummaryDialog(QDialog):
    """Shown when a download finishes: time and average / maximum / minimum speed."""

    def __init__(self, snap: Snapshot, parent=None):
        super().__init__(parent)
        self.snap = snap
        self.setWindowTitle(tr("Download complete"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumWidth(420)
        title = QLabel(snap.filename)
        title.setProperty("heading", True)
        title.setWordWrap(True)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        rows = [(tr("Size"), human_size(snap.total if snap.total >= 0 else snap.downloaded)),
                (tr("Time"), human_time(snap.active_seconds)),
                (tr("Average speed"), human_speed(snap.avg_speed)),
                (tr("Maximum speed"), human_speed(snap.max_speed)),
                (tr("Minimum speed"), human_speed(snap.min_speed)),
                (tr("Saved to"), snap.directory)]
        if snap.hash_result:
            rows.append((tr("Checksum"), tr("verified")))
        for i, (name, value) in enumerate(rows):
            label = QLabel(name)
            label.setProperty("muted", True)
            val = QLabel(value)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(label, i, 0)
            grid.addWidget(val, i, 1)
        open_file = QPushButton(tr("Open file"))
        open_file.setProperty("primary", True)
        open_folder = QPushButton(tr("Open folder"))
        close = QPushButton(tr("Close"))
        open_file.clicked.connect(self._open_file)
        open_folder.clicked.connect(self._open_folder)
        close.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for b in (close, open_folder, open_file):
            buttons.addWidget(b)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        root.addWidget(title)
        root.addLayout(grid)
        root.addSpacing(6)
        root.addLayout(buttons)

    def _open_file(self) -> None:
        if os.path.exists(self.snap.final_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.snap.final_path))
        self.close()

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.snap.directory))
        self.close()


class Toast(QFrame):
    """Small card at the bottom-right: 'Download this link?'"""

    accepted = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self._url = ""
        self.label = QLabel()
        self.label.setMaximumWidth(380)
        yes = QPushButton(tr("Download"))
        yes.setProperty("primary", True)
        no = QPushButton(tr("Dismiss"))
        yes.clicked.connect(self._yes)
        no.clicked.connect(self.hide)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(no)
        row.addWidget(yes)
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 12)
        col.addWidget(QLabel(tr("Link copied")))
        col.addWidget(self.label)
        col.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def popup(self, url: str) -> None:
        self._url = url
        metrics = self.label.fontMetrics()
        self.label.setText(metrics.elidedText(url, Qt.TextElideMode.ElideMiddle, 380))
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self.move(max(0, parent.width() - self.width() - 24), max(0, parent.height() - self.height() - 24))
        self.show()
        self.raise_()
        self._timer.start(12000)

    def _yes(self) -> None:
        self.hide()
        self.accepted.emit(self._url)


class Tray(QObject):
    show_requested = Signal()
    add_requested = Signal()
    quit_requested = Signal()
    message_clicked = Signal()

    def __init__(self, icon, parent=None):
        super().__init__(parent)
        self.tray = QSystemTrayIcon(icon, parent)
        self.menu = QMenu()
        for text, signal in ((tr("Open"), self.show_requested), (tr("Add link"), self.add_requested)):
            action = QAction(text, self.menu)
            action.triggered.connect(lambda _c=False, sig=signal: sig.emit())
            self.menu.addAction(action)
        self.menu.addSeparator()
        quit_action = QAction(tr("Exit"), self.menu)
        quit_action.triggered.connect(lambda _c=False: self.quit_requested.emit())
        self.menu.addAction(quit_action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.tray.messageClicked.connect(lambda: self.message_clicked.emit())
        self.tray.setToolTip("Daryafter")
        self.tray.show()

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_requested.emit()

    def notify(self, title: str, text: str) -> None:
        self.tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 6000)

    def hide(self) -> None:
        self.tray.hide()
