"""Light/dark theme that follows the Windows setting (or a fixed choice)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = dict(window="#F3F5F8", surface="#FFFFFF", border="#DDE2E9", text="#18202B", muted="#667085",
             accent="#0B7F99", accent_text="#FFFFFF", ok="#2FA866", warn="#D9902B", bad="#D64545",
             hover="#E9EEF4", select="#D3EAF0", track="#E4E9F0")
DARK = dict(window="#14181F", surface="#1B2029", border="#2B3340", text="#E6EAF0", muted="#8B95A5",
            accent="#3CC3DE", accent_text="#06222A", ok="#4CC38A", warn="#E5A94B", bad="#EE6B6B",
            hover="#242B37", select="#1F3A44", track="#2B3340")

_current = dict(LIGHT)


def colors() -> dict[str, str]:
    return _current


def is_dark(mode: str) -> bool:
    if mode == "dark":
        return True
    if mode == "light":
        return False
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def _stylesheet(c: dict[str, str]) -> str:
    return f"""
* {{ outline: 0; }}
QMainWindow, QDialog {{ background: {c['window']}; }}
QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px; }}
QLabel[muted="true"] {{ color: {c['muted']}; }}
QLabel[heading="true"] {{ font-size: 15pt; font-weight: 600; }}
QLabel[big="true"] {{ font-size: 24pt; font-weight: 600; }}
QFrame#panel {{ background: {c['surface']}; border: none; border-top: 1px solid {c['border']}; }}
QFrame#toast {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 8px; background: {c['surface']}; top: -1px; }}
QTabBar::tab {{ padding: 8px 16px; border: none; color: {c['muted']}; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
QCheckBox {{ spacing: 8px; }}
QToolBar {{ background: {c['surface']}; border: none; border-bottom: 1px solid {c['border']}; padding: 6px; spacing: 4px; }}
QToolButton {{ padding: 6px 12px; border-radius: 6px; border: 1px solid transparent; }}
QToolButton:hover {{ background: {c['hover']}; }}
QToolButton:checked {{ background: {c['select']}; border-color: {c['accent']}; }}
QToolButton:disabled {{ color: {c['muted']}; }}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 6px 8px; selection-background-color: {c['accent']}; selection-color: {c['accent_text']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QPushButton {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 7px 16px; }}
QPushButton:hover {{ background: {c['hover']}; }}
QPushButton:disabled {{ color: {c['muted']}; }}
QPushButton[primary="true"] {{ background: {c['accent']}; color: {c['accent_text']}; border-color: {c['accent']}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {c['accent']}; }}
QPushButton[primary="true"]:disabled {{ background: {c['track']}; color: {c['muted']}; border-color: {c['track']}; }}
QListWidget {{ background: {c['surface']}; border: none; border-right: 1px solid {c['border']}; padding: 6px; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 6px; }}
QListWidget::item:hover {{ background: {c['hover']}; }}
QListWidget::item:selected {{ background: {c['select']}; color: {c['text']}; }}
QTableView {{ background: {c['surface']}; border: none; gridline-color: transparent; selection-background-color: {c['select']}; selection-color: {c['text']}; }}
QHeaderView::section {{ background: {c['surface']}; color: {c['muted']}; border: none; border-bottom: 1px solid {c['border']}; padding: 8px 10px; font-weight: 500; }}
QStatusBar {{ background: {c['surface']}; border-top: 1px solid {c['border']}; color: {c['muted']}; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['select']}; color: {c['text']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QSplitter::handle {{ background: {c['border']}; }}
"""


def apply_theme(app: QApplication, mode: str = "system") -> None:
    global _current
    try:                                   # Qt 6.8+: follow the system again, or force light/dark
        scheme = {"dark": Qt.ColorScheme.Dark, "light": Qt.ColorScheme.Light}.get(mode, Qt.ColorScheme.Unknown)
        app.styleHints().setColorScheme(scheme)
    except Exception:
        pass
    dark = is_dark(mode)
    c = DARK if dark else LIGHT
    _current = dict(c)
    app.setStyle("Fusion")
    pal = QPalette()
    for role, key in ((QPalette.ColorRole.Window, "window"), (QPalette.ColorRole.WindowText, "text"),
                      (QPalette.ColorRole.Base, "surface"), (QPalette.ColorRole.AlternateBase, "window"),
                      (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "surface"),
                      (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.ToolTipBase, "surface"),
                      (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.Highlight, "accent"),
                      (QPalette.ColorRole.HighlightedText, "accent_text"),
                      (QPalette.ColorRole.PlaceholderText, "muted")):
        pal.setColor(role, QColor(c[key]))
    app.setPalette(pal)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(_stylesheet(c))
