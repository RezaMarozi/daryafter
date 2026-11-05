"""The main window."""
from __future__ import annotations

import os
import subprocess
from collections import deque
from dataclasses import fields
from urllib.parse import urlsplit

from PySide6.QtCore import QByteArray, QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QDialog, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu,
                               QMessageBox, QSizePolicy, QSplitter, QStackedWidget, QSystemTrayIcon,
                               QTableView, QToolBar, QToolButton, QWidget)

from ..branding import APP_NAME, AUTHOR_NAME, LICENSE_NAME, REPO_URL, VERSION
from ..core.applock import LockController
from ..core.categories import looks_downloadable
from ..core.fmt import human_speed
from ..core.idle import system_idle_seconds
from ..core.models import RUNNING_STATES, Event, Snapshot, State
from ..core.settings import Settings
from ..errors_text import friendly
from ..i18n import tr
from . import icons, theme
from .add_dialog import AddDownloadDialog
from .detail import DetailPanel
from .extras import SummaryDialog, Toast, Tray
from .lock_screen import LockScreen
from .models import FILTERS, SNAP_ROLE, DownloadsModel, FilterProxy, RowDelegate, matches_filter
from .settings_dialog import SettingsDialog
from .widgets import SAMPLES


class MainWindow(QMainWindow):
    def __init__(self, service, bridge, settings: Settings, private: bool = False,
                 on_settings_changed=None):
        super().__init__()
        self.service, self.settings, self.private = service, settings, private
        self.on_settings_changed = on_settings_changed
        self.tray: Tray | None = None
        self._quitting = False
        self._tray_hint_shown = False
        self._last_clip = ""
        self._pending_clip = ""
        self._summaries: list = []
        self._hist: dict[int, deque] = {}
        self._total_hist: deque = deque(maxlen=SAMPLES)
        self._total_speed = 0.0
        self._icon_actions: list[tuple[QAction, str]] = []
        self._all_actions: list[QAction] = []
        self._pending_url = ""
        self.lock = LockController(settings, system_idle_seconds)

        self._update_title()
        self.resize(1180, 760)
        if settings.window_geometry and not private:
            self.restoreGeometry(QByteArray.fromBase64(settings.window_geometry.encode("ascii")))

        self.model = DownloadsModel(self)
        self.proxy = FilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self._build_toolbar()
        self._build_body()
        self._build_status_bar()
        self._apply_icons()
        self.act_lock.setEnabled(settings.lock_enabled)

        bridge.event.connect(self._on_event)
        self.model.set_all(service.snapshots())
        self._refresh()
        self._setup_tray()
        QGuiApplication.clipboard().dataChanged.connect(self._clipboard_changed)
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self._system_theme_changed())
        except Exception:
            pass
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(10_000)
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start()
        if self.lock.lock():                      # a password is set: start locked
            self._set_locked(True)

    # ------------------------------------------------------------------ building
    def _action(self, text: str, slot, shortcut: str = "", checkable: bool = False,
                icon: str = "") -> QAction:
        action = QAction(tr(text), self)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(lambda _checked=False: slot())
        if icon:
            self._icon_actions.append((action, icon))
        self._all_actions.append(action)
        return action

    def _build_toolbar(self) -> None:
        bar = QToolBar(self)
        self.toolbar = bar
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(bar)
        self.act_add = self._action("Add link", self.add_download, "Ctrl+N", icon="plus")
        self.act_resume = self._action("Resume", self.resume_selected, "Ctrl+R", icon="play")
        self.act_pause = self._action("Pause", self.pause_selected, "Ctrl+P", icon="pause")
        self.act_remove = self._action("Remove", self.remove_selected, "Del", icon="trash")
        self.act_folder = self._action("Open folder", self.open_folder, icon="folder")
        self.act_offline = self._action("Go offline", self._toggle_offline, checkable=True, icon="wifi")
        self.act_lock = self._action("Lock", self.lock_now, "Ctrl+L", icon="lock")
        self.act_settings = self._action("Settings", self.open_settings, "Ctrl+,", icon="sliders")
        for a in (self.act_add, self.act_resume, self.act_pause, self.act_remove):
            bar.addAction(a)
        bar.addSeparator()
        bar.addAction(self.act_folder)
        bar.addAction(self.act_offline)

        self.more = QToolButton()
        self.more.setText(tr("More"))
        self.more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.more)
        for text, slot in (("Pause all", lambda: self.service.pause_all()),
                           ("Resume all", lambda: self.service.resume_all())):
            menu.addAction(self._action(text, slot))
        menu.addSeparator()
        menu.addAction(self._action("Clear completed", lambda: self.service.clear_completed()))
        menu.addAction(self._action("Clear history...", self.clear_history))
        menu.addAction(self._action("About...", self.show_about))
        self.more.setMenu(menu)
        bar.addWidget(self.more)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search downloads"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self.proxy.set_text)
        bar.addWidget(self.search)
        bar.addAction(self.act_lock)
        bar.addAction(self.act_settings)

    def _apply_icons(self) -> None:
        for action, name in self._icon_actions:
            if action is self.act_offline:
                name = "wifi-off" if action.isChecked() else "wifi"
            action.setIcon(icons.icon(name))
        self.more.setIcon(icons.icon("more"))

    def _build_body(self) -> None:
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(190)
        for name in FILTERS:
            self.sidebar.addItem(tr(name))
        self.sidebar.setCurrentRow(0)
        self.sidebar.currentRowChanged.connect(self._filter_changed)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setItemDelegate(RowDelegate(self.table))
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 90), (2, 230), (3, 110), (4, 90), (5, 150)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(col, width)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(self._double_clicked)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._refresh())

        self.empty = QLabel(tr("No downloads yet.\nClick \"Add link\" or press Ctrl+N."))
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setProperty("muted", True)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.table)

        self.detail = DetailPanel()
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.stack)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([440, 260])
        splitter.setChildrenCollapsible(False)

        root = QHBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar)
        root.addWidget(splitter, 1)
        central = QWidget()
        central.setLayout(root)
        self.lock_screen = LockScreen()
        self.lock_screen.unlock_requested.connect(self._try_unlock)
        self.pages = QStackedWidget()               # 0 = the app, 1 = the lock screen
        self.pages.addWidget(central)
        self.pages.addWidget(self.lock_screen)
        self.setCentralWidget(self.pages)
        self.toast = Toast(central)
        self.toast.accepted.connect(lambda url: self.add_download(url))

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.speed_label = QLabel("")
        self.mode_label = QLabel("")
        bar.addWidget(self.speed_label, 1)
        bar.addPermanentWidget(self.mode_label)
        self._update_mode_label()

    def _update_mode_label(self) -> None:
        parts = []
        if self.private:
            parts.append(tr("Private mode"))
        if self.act_offline.isChecked():
            parts.append(tr("Offline"))
        self.mode_label.setText("   ".join(parts))

    def _update_title(self) -> None:
        locked = getattr(self, "lock", None) is not None and self.lock.locked
        private = self.private and not locked
        self.setWindowTitle(APP_NAME + (" - " + tr("Private mode") if private else ""))

    # ------------------------------------------------------------------ app lock
    def lock_now(self) -> None:
        if self.lock.lock():
            self._set_locked(True)

    def _set_locked(self, locked: bool) -> None:
        self.toolbar.setVisible(not locked)
        self.statusBar().setVisible(not locked)
        for action in self._all_actions:
            action.setEnabled(not locked)
        if locked:
            self.toast.hide()
            self._pending_clip = ""
            for dialog in self._open_summaries():
                dialog.close()
            self._summaries = []
            for widget in QApplication.topLevelWidgets():       # open dialogs would show the contents
                if isinstance(widget, QDialog) and widget.isVisible():
                    widget.reject()
            self.lock_screen.reset()
            wait = self.lock.limiter.wait_seconds()
            if wait > 0:
                self.lock_screen.block_for(wait)
            self.pages.setCurrentIndex(1)
            self.lock_screen.focus_input()
        else:
            self.pages.setCurrentIndex(0)
            self.act_lock.setEnabled(self.settings.lock_enabled)
        self._update_title()
        if not locked:
            self._refresh()

    def _try_unlock(self, password: str) -> None:
        result = self.lock.try_unlock(password)
        if result.ok:
            self._set_locked(False)
            url, self._pending_url = self._pending_url, ""
            if url:
                self.add_download(url)
        else:
            self.lock_screen.show_failure(result.wait)

    def _check_idle(self) -> None:
        if self.lock.inactivity_expired():
            self.lock_now()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if (event.type() == QEvent.Type.WindowStateChange and self.isMinimized()
                and self.settings.lock_on_minimize):
            self.lock_now()

    def show_about(self) -> None:
        QMessageBox.about(
            self, tr("About {app}").format(app=APP_NAME),
            f"<b>{APP_NAME}</b> {VERSION} (beta)<br>"
            + tr("Free, open-source download manager for Windows.")
            + f"<br><br>{tr('Author')}: {AUTHOR_NAME}<br>{tr('License')}: {LICENSE_NAME}<br>"
            + f'<a href="{REPO_URL}">{REPO_URL}</a>')

    # ------------------------------------------------------------------ history
    def clear_history(self, parent=None) -> None:
        """Remove finished and failed downloads from the list and from the database."""
        box = QMessageBox(parent or self)
        box.setWindowTitle(tr("Clear history"))
        box.setText(tr("Remove all finished and failed downloads from the list?"))
        box.setInformativeText(tr("Downloaded files stay on your disk. "
                                  "Partial files of failed downloads are deleted."))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.service.clear_history()
            self.statusBar().showMessage(tr("History cleared."), 6000)

    # ------------------------------------------------------------------ selection
    def _selected(self) -> list[Snapshot]:
        rows = {i.row() for i in self.table.selectionModel().selectedRows()}
        return [s for s in (self.proxy.index(r, 0).data(SNAP_ROLE) for r in sorted(rows)) if s]

    def _filter_changed(self, row: int) -> None:
        if 0 <= row < len(FILTERS):
            self.proxy.set_state_filter(FILTERS[row])

    # ------------------------------------------------------------------ events
    def _on_event(self, ev: Event) -> None:
        kind = ev.kind
        if kind in ("added", "updated") and ev.snapshot is not None:
            self.model.upsert(ev.snapshot)
        elif kind == "progress":
            self.model.update_many(ev.snapshots)
            for s in ev.snapshots:
                self._hist.setdefault(s.id, deque(maxlen=SAMPLES)).append(s.speed)
            self._total_hist.append(ev.speed)
            self._total_speed = ev.speed
            self.speed_label.setText(human_speed(ev.speed) if ev.speed > 0 else "")
            self._update_detail()
        elif kind == "removed":
            self.model.remove(ev.item_id)
            self._hist.pop(ev.item_id, None)
        elif kind == "completed" and ev.snapshot is not None:
            self._on_completed(ev.snapshot)
        elif kind == "offline":
            self.act_offline.setChecked(ev.flag)
            self._apply_icons()
            self._update_mode_label()
        elif kind == "schedule":
            self._on_timer(ev)
        if kind != "progress":
            self._refresh()

    def _on_timer(self, ev: Event) -> None:
        """A timer ran (see Settings > Timers). The message never contains file names."""
        text = {"start": tr("Timer: downloads started."), "stop": tr("Timer: downloads stopped."),
                "disconnect": tr("Timer: disconnected (offline mode).")}.get(ev.text, "")
        if text:
            self.statusBar().showMessage(text, 20000)
            if self.tray is not None:
                self.tray.notify(APP_NAME, text)
        if ev.flag:                                   # a "once" timer switched itself off: save that
            self.apply_new_settings(self.settings.copy())

    def _on_completed(self, snap: Snapshot) -> None:
        self.statusBar().showMessage(tr("Finished: {name}").format(name=snap.filename), 8000)
        QApplication.alert(self)
        if self.settings.notify_on_complete and self.tray is not None:
            if self.private or self.lock.locked:      # Windows keeps notifications in its history
                self.tray.notify(tr("Download complete"), tr("A download has finished."))
            else:
                self.tray.notify(tr("Download complete"), snap.filename)
        if self.settings.show_summary and not self.lock.locked:
            self._summaries = self._open_summaries()
            dialog = SummaryDialog(snap, self)
            self._summaries.append(dialog)
            dialog.show()

    def _open_summaries(self) -> list:
        """Summary windows delete themselves when closed; touching a deleted one raises RuntimeError."""
        alive = []
        for dialog in self._summaries:
            try:
                if dialog.isVisible():
                    alive.append(dialog)
            except RuntimeError:
                pass
        return alive

    def _refresh(self) -> None:
        snaps = self.model.snapshots()
        for row, name in enumerate(FILTERS):
            count = sum(1 for s in snaps if matches_filter(s, name))
            self.sidebar.item(row).setText(f"{tr(name)}   {count}" if count else tr(name))
        self.stack.setCurrentIndex(1 if snaps else 0)
        if self.lock.locked:
            return
        selected = self._selected()
        self.act_pause.setEnabled(any(s.state in RUNNING_STATES or s.state == State.QUEUED for s in selected))
        self.act_resume.setEnabled(any(s.state in (State.PAUSED, State.FAILED) for s in selected))
        self.act_remove.setEnabled(bool(selected))
        self.act_folder.setEnabled(len(selected) == 1)
        self._update_detail()

    def _update_detail(self) -> None:
        selected = self._selected()
        if len(selected) == 1:
            snap = self.model.get(selected[0].id) or selected[0]
            self.detail.show_snapshot(snap, self._hist.get(snap.id, ()))
        else:
            self.detail.show_overview(self._total_speed, self._total_hist)

    # ------------------------------------------------------------------ actions
    def add_download(self, url: str = "") -> None:
        self._show_window()
        if self.lock.locked:                          # asked from the tray or the command line
            if url:
                self._pending_url = url
            return
        dialog = AddDownloadDialog(self.service, self.settings, self, url)
        if dialog.exec():
            self.service.add(dialog.request()).add_done_callback(self._report_failure)

    def _report_failure(self, future) -> None:
        if not future.cancelled() and future.exception() is not None:
            self.statusBar().showMessage(friendly(future.exception()), 10000)

    def pause_selected(self) -> None:
        for s in self._selected():
            self.service.pause(s.id)

    def resume_selected(self) -> None:
        for s in self._selected():
            self.service.resume(s.id)

    def remove_selected(self) -> None:
        selected = self._selected()
        if not selected:
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr("Remove"))
        box.setText(tr("Remove {n} download(s) from the list?").format(n=len(selected)))
        check = QCheckBox(tr("Also delete the downloaded file(s) from the disk"))
        box.setCheckBox(check)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() == QMessageBox.StandardButton.Yes:
            for s in selected:
                self.service.remove(s.id, check.isChecked())

    def open_file(self, snap: Snapshot) -> None:
        if snap.state == State.COMPLETED and os.path.exists(snap.final_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(snap.final_path))

    def open_folder(self) -> None:
        selected = self._selected()
        if len(selected) != 1:
            return
        snap = selected[0]
        if os.name == "nt" and os.path.exists(snap.final_path):
            subprocess.Popen(f'explorer /select,"{os.path.normpath(snap.final_path)}"')
        elif os.path.isdir(snap.directory):
            QDesktopServices.openUrl(QUrl.fromLocalFile(snap.directory))

    def _toggle_offline(self) -> None:
        self.service.set_offline(self.act_offline.isChecked())
        self._apply_icons()
        self._update_mode_label()

    def _double_clicked(self, index) -> None:
        snap = index.sibling(index.row(), 0).data(SNAP_ROLE)
        if snap is None:
            return
        if snap.state == State.COMPLETED:
            self.open_file(snap)
        elif snap.state in (State.PAUSED, State.FAILED):
            self.service.resume(snap.id)
        else:
            self.service.pause(snap.id)

    def _rename(self, snap: Snapshot) -> None:
        name, ok = QInputDialog.getText(self, tr("Rename"), tr("File name:"), QLineEdit.EchoMode.Normal,
                                        snap.filename)
        if ok and name.strip():
            self.service.rename(snap.id, name.strip())

    def _refresh_link(self, snap: Snapshot) -> None:
        url, ok = QInputDialog.getText(self, tr("Refresh link"), tr("New link for this file:"),
                                       QLineEdit.EchoMode.Normal, snap.url)
        if ok and url.strip():
            self.service.update_url(snap.id, url.strip()).add_done_callback(self._report_failure)

    def _copy_link(self, url: str) -> None:
        self._last_clip = url                 # don't offer to download our own copy
        QGuiApplication.clipboard().setText(url)

    def _add(self, menu: QMenu, text: str, slot) -> None:
        action = QAction(text, menu)
        action.triggered.connect(lambda _checked=False: slot())
        menu.addAction(action)

    def _context_menu(self, pos) -> None:
        selected = self._selected()
        if not selected:
            return
        one = selected[0] if len(selected) == 1 else None
        menu = QMenu(self)
        if any(s.state in (State.PAUSED, State.FAILED) for s in selected):
            self._add(menu, tr("Resume"), self.resume_selected)
        if any(s.state in RUNNING_STATES or s.state == State.QUEUED for s in selected):
            self._add(menu, tr("Pause"), self.pause_selected)
        if one is not None:
            if one.state == State.COMPLETED:
                self._add(menu, tr("Open file"), lambda: self.open_file(one))
            self._add(menu, tr("Open folder"), self.open_folder)
            menu.addSeparator()
            self._add(menu, tr("Copy link"), lambda: self._copy_link(one.url))
            if one.state not in RUNNING_STATES:
                self._add(menu, tr("Rename..."), lambda: self._rename(one))
                if one.state != State.COMPLETED:
                    self._add(menu, tr("Refresh link..."), lambda: self._refresh_link(one))
                    self._add(menu, tr("Download again from the start"), lambda: self.service.restart(one.id))
            if one.state != State.COMPLETED:
                menu.addSeparator()
                for label, where in ((tr("Move to top of the queue"), "top"), (tr("Move up in the queue"), "up"),
                                     (tr("Move down in the queue"), "down"), (tr("Move to bottom of the queue"), "bottom")):
                    self._add(menu, label, lambda w=where: self.service.move_in_queue(one.id, w))
        menu.addSeparator()
        self._add(menu, tr("Remove"), self.remove_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ settings & theme
    def open_settings(self) -> None:
        if self.lock.locked:
            return
        dialog = SettingsDialog(self.settings, self, private=self.private, on_clear_history=self.clear_history)
        if dialog.exec():
            self.apply_new_settings(dialog.result_settings())

    def apply_new_settings(self, new: Settings) -> None:
        old_theme = self.settings.theme
        for f in fields(Settings):
            setattr(self.settings, f.name, getattr(new, f.name))
        self.service.apply_settings(self.settings.copy())
        if self.on_settings_changed is not None:
            self.on_settings_changed(self.settings)
        if self.settings.theme != old_theme:
            self._retheme()
        self._setup_tray()
        self.act_lock.setEnabled(self.settings.lock_enabled)

    def _system_theme_changed(self) -> None:
        if self.settings.theme == "system":
            self._retheme()

    def _retheme(self) -> None:
        theme.apply_theme(QApplication.instance(), self.settings.theme)
        icons.clear_cache()
        self._apply_icons()
        self.table.viewport().update()
        self.detail.chart.update()
        self.detail.segmap.update()
        self.lock_screen.refresh_icon()

    # ------------------------------------------------------------------ tray & clipboard
    def _setup_tray(self) -> None:
        want = self.settings.tray_enabled and QSystemTrayIcon.isSystemTrayAvailable()
        if want and self.tray is None:
            self.tray = Tray(QApplication.windowIcon(), self)
            self.tray.show_requested.connect(self._show_window)
            self.tray.add_requested.connect(lambda: self.add_download())
            self.tray.quit_requested.connect(self._quit)
            self.tray.message_clicked.connect(self._tray_message_clicked)
        elif not want and self.tray is not None:
            self.tray.hide()
            self.tray = None

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._quitting = True
        self.close()

    def _tray_message_clicked(self) -> None:
        url, self._pending_clip = self._pending_clip, ""
        if url:
            self.add_download(url)
        else:
            self._show_window()

    def _clipboard_changed(self) -> None:
        if not self.settings.clipboard_watch or self.lock.locked:
            return
        text = QGuiApplication.clipboard().text().strip()
        if not text or text == self._last_clip or "\n" in text or len(text) > 2000:
            return
        parts = urlsplit(text)
        if parts.scheme not in ("http", "https") or not parts.netloc or not looks_downloadable(text):
            return
        self._last_clip = text
        if self.isVisible() and not self.isMinimized():
            self.toast.popup(text)
        elif self.tray is not None:
            self._pending_clip = text
            self.tray.notify(tr("Link copied"), tr("Click to download it"))

    # ------------------------------------------------------------------ closing
    def running_count(self) -> int:
        return sum(1 for s in self.model.snapshots() if s.state in RUNNING_STATES)

    def save_state(self) -> str:
        return bytes(self.saveGeometry().toBase64()).decode("ascii")

    def _confirm_exit(self) -> bool:
        if self.private:
            unfinished = sum(1 for s in self.model.snapshots() if s.state != State.COMPLETED)
            if unfinished:
                answer = QMessageBox.question(
                    self, APP_NAME,
                    tr("Private mode: {n} unfinished download(s) will be deleted when you exit. "
                       "Exit anyway?").format(n=unfinished),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                return answer == QMessageBox.StandardButton.Yes
            return True
        if self.running_count():
            answer = QMessageBox.question(
                self, APP_NAME, tr("Downloads are in progress. Pause them and exit?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes)
            return answer == QMessageBox.StandardButton.Yes
        return True

    def closeEvent(self, event) -> None:
        if self.settings.minimize_to_tray and self.tray is not None and not self._quitting:
            event.ignore()
            if self.settings.lock_on_minimize:
                self.lock_now()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.notify(APP_NAME, tr("Still running in the notification area."))
            return
        if not self._confirm_exit():
            self._quitting = False
            event.ignore()
            return
        if self.tray is not None:
            self.tray.hide()
        event.accept()
        QApplication.quit()
