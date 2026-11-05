"""Edit one timer: what to do, at what time, on which days."""
from __future__ import annotations

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton,
                               QTimeEdit, QVBoxLayout)

from ..core.schedule import ACTIONS, ALL_DAYS, Rule
from ..i18n import tr

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ACTION_NAMES = {"start": "Start downloads", "stop": "Stop downloads", "disconnect": "Disconnect (offline mode)"}
ACTION_HELP = {
    "start": "Goes online and resumes every paused or failed download.",
    "stop": "Pauses every download. Their partial files are kept.",
    "disconnect": "Pauses the connections and goes offline until a Start timer or the Go-online button.",
}


def rule_text(rule: Rule) -> str:
    days = tr("every day") if len(rule.days) == 7 else " ".join(tr(DAY_NAMES[d]) for d in rule.days)
    text = f"{rule.clock_text()}   {tr(ACTION_NAMES[rule.action])}   ({days})"
    if rule.once:
        text += "   " + tr("once")
    if not rule.enabled:
        text += "   " + tr("(off)")
    return text


class RuleDialog(QDialog):
    def __init__(self, rule: Rule | None = None, parent=None):
        super().__init__(parent)
        rule = rule or Rule()
        self.setWindowTitle(tr("Timer"))
        self.setMinimumWidth(420)
        self.action = QComboBox()
        for name in ACTIONS:
            self.action.addItem(tr(ACTION_NAMES[name]))
        self.action.setCurrentIndex(ACTIONS.index(rule.action))
        self.help = QLabel()
        self.help.setProperty("muted", True)
        self.help.setWordWrap(True)
        self.action.currentIndexChanged.connect(lambda *_: self._show_help())
        self.time = QTimeEdit()
        self.time.setDisplayFormat("HH:mm")
        self.time.setTime(QTime(rule.hour, rule.minute))
        days_row = QHBoxLayout()
        self.days = []
        for number, name in enumerate(DAY_NAMES):
            box = QCheckBox(tr(name))
            box.setChecked(number in rule.days)
            self.days.append(box)
            days_row.addWidget(box)
        self.once = QCheckBox(tr("Only once (then switch this timer off)"))
        self.once.setChecked(rule.once)
        self.enabled = QCheckBox(tr("Timer is on"))
        self.enabled.setChecked(rule.enabled)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #D64545;")

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow(tr("Do this"), self.action)
        form.addRow("", self.help)
        form.addRow(tr("At"), self.time)
        form.addRow(tr("On"), days_row)
        form.addRow("", self.once)
        form.addRow("", self.enabled)
        cancel = QPushButton(tr("Cancel"))
        ok = QPushButton(tr("OK"))
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
        root.addWidget(self.error)
        root.addLayout(buttons)
        self._show_help()

    def _show_help(self) -> None:
        self.help.setText(tr(ACTION_HELP[ACTIONS[int(self.action.currentIndex())]]))

    def chosen_days(self) -> list[int]:
        return [n for n, box in enumerate(self.days) if box.isChecked()]

    def accept(self) -> None:
        if not self.chosen_days():
            self.error.setText(tr("Pick at least one day."))
            return
        super().accept()

    def rule(self) -> Rule:
        t = self.time.time()
        return Rule(ACTIONS[int(self.action.currentIndex())], int(t.hour()), int(t.minute()),
                    self.chosen_days() or list(ALL_DAYS), self.once.isChecked(), self.enabled.isChecked())
