"""Settings window."""
from __future__ import annotations

import os

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox, QTabWidget,
                               QVBoxLayout,
                               QWidget)

from ..core.settings import Settings
from ..i18n import tr
from ..paths import locales_dir
from ..core.schedule import Rule, Scheduler
from .password_dialog import CHANGE, REMOVE, SET, PasswordDialog
from .schedule_dialog import DAY_NAMES, RuleDialog, rule_text


def _page() -> tuple[QWidget, QFormLayout]:
    widget = QWidget()
    form = QFormLayout(widget)
    form.setContentsMargins(16, 16, 16, 16)
    form.setVerticalSpacing(10)
    return widget, form


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None, private: bool = False, on_clear_history=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Settings"))
        self.setMinimumWidth(560)
        self._s = settings.copy()
        self._private = private
        self._password_touched = False
        s = self._s

        tabs = QTabWidget()
        # ---- General -------------------------------------------------------
        page, form = _page()
        self.folder = QLineEdit(s.resolved_download_dir())
        browse = QPushButton(tr("Browse..."))
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        form.addRow(tr("Default folder"), row)
        self.categorize = self._check(tr("Sort files into folders by type (Video, Music, ...)"), s.auto_categorize)
        self.ask_name = self._check(tr("Ask for the file name when a copied link is added"), s.ask_name_each_time)
        self.prevent_sleep = self._check(tr("Prevent system sleep while downloading"), s.prevent_sleep)
        self.file_time = self._check(tr("Set the file date to the date on the server"), s.set_file_time)
        self.clipboard = self._check(tr("Offer to download links I copy"), s.clipboard_watch)
        self.notify = self._check(tr("Show a notification when a download finishes"), s.notify_on_complete)
        self.summary = self._check(tr("Show a speed summary when a download finishes"), s.show_summary)
        self.tray = self._check(tr("Show an icon in the notification area"), s.tray_enabled)
        self.to_tray = self._check(tr("Closing the window keeps the app running in the tray"), s.minimize_to_tray)
        for box in (self.categorize, self.ask_name, self.prevent_sleep, self.file_time, self.clipboard,
                    self.notify, self.summary, self.tray, self.to_tray):
            form.addRow("", box)
        tabs.addTab(page, tr("General"))

        # ---- Network -------------------------------------------------------
        page, form = _page()
        self.connections = self._spin(1, 32, s.connections)
        self.concurrent = self._spin(1, 20, s.max_concurrent)
        self.global_limit = self._spin(0, 10_000_000, s.global_speed_limit // 1024, " KB/s")
        self.global_limit.setSpecialValueText(tr("Unlimited"))
        self.full_speed = self._check(tr("Use the full bandwidth by default (up to 32 connections)"),
                                      s.max_speed_mode)
        self.retries = self._spin(-1, 100, s.retry_max)
        self.retries.setSpecialValueText(tr("Never give up"))
        self.proxy_mode = QComboBox()
        for code, label in (("system", tr("Use system settings")), ("none", tr("No proxy")),
                            ("manual", tr("Manual"))):
            self.proxy_mode.addItem(label, code)
        self.proxy_mode.setCurrentIndex(max(0, self.proxy_mode.findData(s.proxy_mode)))
        self.proxy_url = QLineEdit(s.proxy_url)
        self.proxy_url.setPlaceholderText("http://host:8080  or  socks5://host:1080")
        self.http2 = self._check(tr("Use HTTP/2 (one shared connection, usually slower for big files)"), s.use_http2)
        self.verify = self._check(tr("Check website security certificates"), s.verify_tls)
        self.agent = QLineEdit(s.user_agent)
        form.addRow(tr("Connections per download"), self.connections)
        form.addRow(tr("Downloads at the same time"), self.concurrent)
        form.addRow(tr("Total speed limit"), self.global_limit)
        form.addRow("", self.full_speed)
        form.addRow(tr("Retries"), self.retries)
        form.addRow(tr("Proxy"), self.proxy_mode)
        form.addRow("", self.proxy_url)
        form.addRow("", self.http2)
        form.addRow("", self.verify)
        form.addRow(tr("User agent"), self.agent)
        tabs.addTab(page, tr("Network"))

        # ---- Appearance ----------------------------------------------------
        page, form = _page()
        self.theme = QComboBox()
        for code, label in (("system", tr("System default")), ("light", tr("Light")), ("dark", tr("Dark"))):
            self.theme.addItem(label, code)
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.theme)))
        self.language = QComboBox()
        self.language.addItem("English", "en")
        try:
            for path in sorted(locales_dir().glob("*.json")):
                self.language.addItem(path.stem, path.stem)
        except OSError:
            pass
        self.language.setCurrentIndex(max(0, self.language.findData(s.language)))
        note = QLabel(tr("A new language is used after restarting the app."))
        note.setProperty("muted", True)
        form.addRow(tr("Theme"), self.theme)
        form.addRow(tr("Language"), self.language)
        form.addRow("", note)
        tabs.addTab(page, tr("Appearance"))

        # ---- Privacy -------------------------------------------------------
        page, form = _page()
        if private:
            note = QLabel(tr("Private mode: changes made here are not saved."))
            note.setProperty("muted", True)
            note.setWordWrap(True)
            form.addRow("", note)
        self.private = self._check(tr("Start in private mode (nothing is saved on this computer)"), s.start_private)
        self.clear_exit = self._check(tr("Clear the finished downloads list when I exit"), s.clear_history_on_exit)
        self.remember = self._check(tr("Remember passwords (protected for this user)"), s.remember_passwords)
        for box in (self.private, self.clear_exit, self.remember):
            form.addRow("", box)
        hint = QLabel(tr('To switch "Start in private mode" off again, start Daryafter with '
                         '"run.bat --normal" on Windows or "./run.sh --normal" on Linux and untick it here.'))
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        form.addRow("", hint)
        if on_clear_history is not None:
            clear_btn = QPushButton(tr("Clear history now..."))
            clear_btn.clicked.connect(lambda: on_clear_history(self))
            row = QHBoxLayout()
            row.addWidget(clear_btn)
            row.addStretch(1)
            form.addRow("", row)

        heading = QLabel(tr("App lock"))
        heading.setProperty("heading", True)
        form.addRow(heading)
        self.lock_status = QLabel()
        self.set_pw = QPushButton()
        self.remove_pw = QPushButton(tr("Remove password..."))
        self.set_pw.clicked.connect(self._set_or_change_password)
        self.remove_pw.clicked.connect(self._remove_password)
        row = QHBoxLayout()
        row.addWidget(self.set_pw)
        row.addWidget(self.remove_pw)
        row.addStretch(1)
        self.lock_minutes = self._spin(0, 1440, s.lock_after_minutes, tr(" min"))
        self.lock_minutes.setSpecialValueText(tr("Never"))
        self.lock_minimize = self._check(tr("Lock when the window is minimized or sent to the tray"),
                                         s.lock_on_minimize)
        lock_note = QLabel(tr("The lock hides the window. It does not encrypt your files or the download list."))
        lock_note.setProperty("muted", True)
        lock_note.setWordWrap(True)
        form.addRow(tr("Status"), self.lock_status)
        form.addRow("", row)
        form.addRow(tr("Lock after no activity for"), self.lock_minutes)
        form.addRow("", self.lock_minimize)
        form.addRow("", lock_note)
        self._update_lock_ui()
        tabs.addTab(page, tr("Privacy"))

        # ---- Timers --------------------------------------------------------
        page = QWidget()
        col = QVBoxLayout(page)
        intro = QLabel(tr("Start, stop or disconnect downloads at a time of day. "
                          "Timers work only while Daryafter is running."))
        intro.setProperty("muted", True)
        intro.setWordWrap(True)
        self.rule_list = QListWidget()
        self.rule_list.itemDoubleClicked.connect(lambda *_: self._edit_rule())
        add_btn, edit_btn, del_btn = QPushButton(tr("Add...")), QPushButton(tr("Edit...")), QPushButton(tr("Remove"))
        add_btn.clicked.connect(self._add_rule)
        edit_btn.clicked.connect(self._edit_rule)
        del_btn.clicked.connect(self._remove_rule)
        row = QHBoxLayout()
        for button in (add_btn, edit_btn, del_btn):
            row.addWidget(button)
        row.addStretch(1)
        self.next_label = QLabel()
        self.next_label.setProperty("muted", True)
        col.addWidget(intro)
        col.addWidget(self.rule_list, 1)
        col.addLayout(row)
        col.addWidget(self.next_label)
        tabs.addTab(page, tr("Timers"))
        self._refresh_rules()

        cancel = QPushButton(tr("Cancel"))
        save = QPushButton(tr("Save"))
        save.setProperty("primary", True)
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.addWidget(tabs)
        root.addLayout(buttons)

    @staticmethod
    def _check(text: str, value: bool) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(bool(value))
        return box

    @staticmethod
    def _spin(low: int, high: int, value: int, suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(int(value))
        if suffix:
            spin.setSuffix(suffix)
        return spin

    # ---- timers ---------------------------------------------------------
    def _refresh_rules(self) -> None:
        self.rule_list.clear()
        rules = []
        for data in self._s.schedule:
            rule = Rule.from_dict(data)
            self.rule_list.addItem(rule_text(rule) if rule else tr("(unreadable timer)"))
            if rule:
                rules.append(rule)
        soon = Scheduler().next_run(rules)
        if soon is None:
            self.next_label.setText(tr("No timer is waiting to run."))
        else:
            when, rule = soon
            self.next_label.setText(tr("Next: {when}").format(when=f"{tr(DAY_NAMES[when.weekday()])} {rule.clock_text()}"))

    def _add_rule(self) -> None:
        dialog = RuleDialog(None, self)
        if dialog.exec():
            self._s.schedule.append(dialog.rule().to_dict())
            self._refresh_rules()

    def _edit_rule(self) -> None:
        row = int(self.rule_list.currentRow())
        if not 0 <= row < len(self._s.schedule):
            return
        dialog = RuleDialog(Rule.from_dict(self._s.schedule[row]), self)
        if dialog.exec():
            self._s.schedule[row] = dialog.rule().to_dict()
            self._refresh_rules()

    def _remove_rule(self) -> None:
        row = int(self.rule_list.currentRow())
        if 0 <= row < len(self._s.schedule):
            del self._s.schedule[row]
            self._refresh_rules()

    # ---- app lock -------------------------------------------------------
    def _update_lock_ui(self) -> None:
        on = self._s.lock_enabled
        text = tr("The lock is on.") if on else tr("The lock is off.")
        if self._password_touched:
            text += " " + tr("Press Save to apply.")
        if self._private:
            text += " " + tr("(Can't be changed in private mode.)")
        self.lock_status.setText(text)
        self.set_pw.setText(tr("Change password...") if on else tr("Set password..."))
        self.set_pw.setEnabled(not self._private)
        self.remove_pw.setEnabled(on and not self._private)
        self.lock_minutes.setEnabled(on and not self._private)
        self.lock_minimize.setEnabled(on and not self._private)

    def _set_or_change_password(self) -> None:
        dialog = PasswordDialog(self._s, CHANGE if self._s.lock_enabled else SET, self)
        if dialog.exec():
            self._s.set_password(dialog.new_password())
            self._password_touched = True
            self._update_lock_ui()

    def _remove_password(self) -> None:
        dialog = PasswordDialog(self._s, REMOVE, self)
        if dialog.exec():
            self._s.set_password("")
            self._password_touched = True
            self._update_lock_ui()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("Choose a folder"), self.folder.text())
        if folder:
            self.folder.setText(os.path.normpath(folder))

    def result_settings(self) -> Settings:
        s = self._s
        s.download_dir = self.folder.text().strip()
        s.auto_categorize = self.categorize.isChecked()
        s.ask_name_each_time = self.ask_name.isChecked()
        s.prevent_sleep = self.prevent_sleep.isChecked()
        s.set_file_time = self.file_time.isChecked()
        s.clipboard_watch = self.clipboard.isChecked()
        s.notify_on_complete = self.notify.isChecked()
        s.show_summary = self.summary.isChecked()
        s.tray_enabled = self.tray.isChecked()
        s.minimize_to_tray = self.to_tray.isChecked()
        s.connections = self.connections.value()
        s.max_concurrent = self.concurrent.value()
        s.global_speed_limit = self.global_limit.value() * 1024
        s.max_speed_mode = self.full_speed.isChecked()
        s.retry_max = self.retries.value()
        s.proxy_mode = str(self.proxy_mode.currentData())
        s.proxy_url = self.proxy_url.text().strip()
        s.use_http2 = self.http2.isChecked()
        s.verify_tls = self.verify.isChecked()
        s.user_agent = self.agent.text().strip() or s.user_agent
        s.theme = str(self.theme.currentData())
        s.language = str(self.language.currentData())
        s.start_private = self.private.isChecked()
        s.clear_history_on_exit = self.clear_exit.isChecked()
        s.remember_passwords = self.remember.isChecked()
        s.lock_after_minutes = self.lock_minutes.value()
        s.lock_on_minimize = self.lock_minimize.isChecked()
        return s
