"""Dialog that asks for the link and lets you edit the file name and folder."""
from __future__ import annotations

import os
from urllib.parse import urlsplit

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ..core.categories import category_for
from ..core.filenames import sanitize_filename, split_ext
from ..core.fmt import human_size
from ..core.hashing import guess_algorithm
from ..core.models import AddRequest, DownloadOptions, ProbeResult
from ..errors_text import friendly
from ..i18n import tr
from . import theme


def _valid_url(url: str) -> bool:
    parts = urlsplit(url.strip())
    return parts.scheme in ("http", "https") and bool(parts.netloc)


class AddDownloadDialog(QDialog):
    probed = Signal(int, object, str)

    def __init__(self, service, settings, parent=None, url: str = ""):
        super().__init__(parent)
        self.service, self.settings = service, settings
        self._seq = 0
        self._probe: ProbeResult | None = None
        self._name_edited = False
        self._start_now = True
        self.setWindowTitle(tr("Add download"))
        self.setMinimumWidth(580)
        self.probed.connect(self._on_probed)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(tr("Paste a direct download link"))
        self.info = QLabel(" ")
        self.info.setWordWrap(True)
        self.info.setProperty("muted", True)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr("File name"))
        self.reset_name = QToolButton()
        self.reset_name.setText(tr("Reset"))
        self.folder_edit = QLineEdit(settings.resolved_download_dir())
        browse = QPushButton(tr("Browse..."))
        self.category_box = QCheckBox(tr("Sort into a folder by file type (Video, Music, ...)"))
        self.category_box.setChecked(settings.auto_categorize)
        self.target_label = QLabel(" ")
        self.target_label.setProperty("muted", True)
        self.target_label.setWordWrap(True)
        self.conn_spin = QSpinBox()
        self.conn_spin.setRange(1, 32)
        self.conn_spin.setValue(settings.connections)
        self.max_box = QCheckBox(tr("Use the full bandwidth (up to 32 connections)"))
        self.max_box.setChecked(settings.max_speed_mode)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 10_000_000)
        self.limit_spin.setSuffix(" KB/s")
        self.limit_spin.setSpecialValueText(tr("Unlimited"))

        form = QFormLayout()
        form.addRow(tr("Link"), self.url_edit)
        form.addRow("", self.info)
        name_row = QHBoxLayout()
        name_row.addWidget(self.name_edit, 1)
        name_row.addWidget(self.reset_name)
        form.addRow(tr("Save as"), name_row)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse)
        form.addRow(tr("Folder"), folder_row)
        form.addRow("", self.category_box)
        form.addRow("", self.target_label)
        form.addRow(tr("Connections"), self.conn_spin)
        form.addRow("", self.max_box)
        form.addRow(tr("Speed limit"), self.limit_spin)

        self.adv_toggle = QToolButton()
        self.adv_toggle.setText(tr("Advanced options"))
        self.adv_toggle.setCheckable(True)
        self.adv = QWidget()
        adv_form = QFormLayout(self.adv)
        adv_form.setContentsMargins(0, 0, 0, 0)
        self.referer_edit, self.cookie_edit = QLineEdit(), QLineEdit()
        self.user_edit, self.pass_edit = QLineEdit(), QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.hash_edit = QLineEdit()
        self.hash_edit.setPlaceholderText(tr("MD5, SHA-1, SHA-256 or SHA-512 (optional)"))
        adv_form.addRow(tr("Referer"), self.referer_edit)
        adv_form.addRow(tr("Cookies"), self.cookie_edit)
        adv_form.addRow(tr("User name"), self.user_edit)
        adv_form.addRow(tr("Password"), self.pass_edit)
        adv_form.addRow(tr("Checksum"), self.hash_edit)
        self.adv.setVisible(False)

        self.cancel_btn = QPushButton(tr("Cancel"))
        self.later_btn = QPushButton(tr("Add to list"))
        self.now_btn = QPushButton(tr("Download now"))
        self.now_btn.setProperty("primary", True)
        self.now_btn.setDefault(True)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for b in (self.cancel_btn, self.later_btn, self.now_btn):
            buttons.addWidget(b)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)
        heading = QLabel(tr("Add download"))
        heading.setProperty("heading", True)
        root.addWidget(heading)
        root.addLayout(form)
        root.addWidget(self.adv_toggle)
        root.addWidget(self.adv)
        root.addSpacing(6)
        root.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._check_link)
        self.url_edit.textChanged.connect(self._url_changed)
        self.name_edit.textEdited.connect(self._name_typed)
        self.name_edit.textChanged.connect(self._update_target)
        self.folder_edit.textChanged.connect(self._update_target)
        self.category_box.toggled.connect(self._update_target)
        self.reset_name.clicked.connect(self._reset_name)
        browse.clicked.connect(self._browse)
        self.adv_toggle.toggled.connect(self.adv.setVisible)
        self.cancel_btn.clicked.connect(self.reject)
        self.later_btn.clicked.connect(lambda: self._finish(False))
        self.now_btn.clicked.connect(lambda: self._finish(True))
        self.max_box.toggled.connect(lambda on: self.conn_spin.setEnabled(not on))
        self.conn_spin.setEnabled(not self.max_box.isChecked())

        if url:
            self.url_edit.setText(url)
        self._update_buttons()

    # ---- helpers ----------------------------------------------------------
    def _options(self) -> DownloadOptions:
        return DownloadOptions(
            connections=self.conn_spin.value(), max_speed=self.max_box.isChecked(),
            speed_limit=self.limit_spin.value() * 1024, referer=self.referer_edit.text().strip(),
            cookies=self.cookie_edit.text().strip(), username=self.user_edit.text().strip(),
            password=self.pass_edit.text(),
            expected_hash=self.hash_edit.text().strip(),
            expected_hash_algo=guess_algorithm(self.hash_edit.text().strip()))

    def _update_buttons(self) -> None:
        ok = _valid_url(self.url_edit.text()) and bool(self.name_edit.text().strip())
        self.now_btn.setEnabled(ok)
        self.later_btn.setEnabled(ok)

    def _url_changed(self, _text: str) -> None:
        self._probe = None
        self._timer.start()
        self._update_buttons()

    def _name_typed(self, _text: str) -> None:
        self._name_edited = True

    def _reset_name(self) -> None:
        if self._probe:
            self.name_edit.setText(self._probe.filename)
            self._name_edited = False

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("Choose a folder"), self.folder_edit.text())
        if folder:
            self.folder_edit.setText(os.path.normpath(folder))

    def target_dir(self) -> str:
        base = self.folder_edit.text().strip() or self.settings.resolved_download_dir()
        category = category_for(self.name_edit.text())
        if self.category_box.isChecked() and category != "Other":
            return os.path.join(base, category)
        return base

    def _update_target(self, *_args) -> None:
        self._update_buttons()
        name = sanitize_filename(self.name_edit.text()) if self.name_edit.text().strip() else ""
        if not name:
            self.target_label.setText(" ")
            return
        path = os.path.join(self.target_dir(), name)
        if os.path.exists(path):
            stem, ext = split_ext(name)
            self.target_label.setText(tr("A file with this name already exists. It will be saved as "
                                         "\"{stem} (1){ext}\".").format(stem=stem, ext=ext))
        else:
            self.target_label.setText(tr("Will be saved to: {path}").format(path=path))

    # ---- link check -------------------------------------------------------
    def _check_link(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            self.info.setText(" ")
            return
        if not _valid_url(url):
            self.info.setText(tr("Enter a full link that starts with http:// or https://"))
            return
        self._seq += 1
        seq = self._seq
        self.info.setText(tr("Checking link..."))
        future = self.service.probe(url, self._options())
        future.add_done_callback(lambda f, s=seq: self._probe_finished(s, f))

    def _probe_finished(self, seq: int, future) -> None:        # engine thread
        if future.cancelled():
            return
        error = future.exception()
        if error is not None:
            self.probed.emit(seq, None, friendly(error))
        else:
            self.probed.emit(seq, future.result(), "")

    def _on_probed(self, seq: int, result, error: str) -> None:   # GUI thread
        if seq != self._seq:
            return
        c = theme.colors()
        if result is None:
            self.info.setText(f'<span style="color:{c["bad"]}">{error}</span>')
            return
        self._probe = result
        resume = tr("resume supported") if result.resumable else tr("no resume support")
        text = f"{human_size(result.total_size)}  -  {resume}"
        if result.is_html:
            text += f'  -  <span style="color:{c["warn"]}">' + tr(
                "this looks like a web page, not a file") + "</span>"
        self.info.setText(text)
        if not self._name_edited:
            self.name_edit.setText(result.filename)
            stem, _ext = split_ext(result.filename)
            self.name_edit.setFocus()
            self.name_edit.setSelection(0, len(stem))
        self._update_target()

    # ---- result -----------------------------------------------------------
    def _finish(self, start_now: bool) -> None:
        self._start_now = start_now
        self.accept()

    def request(self) -> AddRequest:
        return AddRequest(
            url=self.url_edit.text().strip(), filename=sanitize_filename(self.name_edit.text()),
            directory=self.folder_edit.text().strip(), use_category_folder=self.category_box.isChecked(),
            options=self._options(), start_now=self._start_now, probe=self._probe)
