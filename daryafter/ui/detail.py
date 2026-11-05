"""Bottom panel: big live speed, chart, min/max/average, connection map and facts."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..core.fmt import human_size, human_speed, human_time
from ..core.models import Snapshot, State
from ..i18n import tr
from .models import status_text
from .widgets import SegmentMap, SpeedChart


class DetailPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setMinimumHeight(190)
        self.title = QLabel(tr("All downloads"))
        self.title.setProperty("muted", True)
        self.speed = QLabel(human_speed(0))
        self.speed.setProperty("big", True)
        self.stats = QLabel(" ")
        self.stats.setProperty("muted", True)
        self.chart = SpeedChart()
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(self.title)
        left.addWidget(self.speed)
        left.addWidget(self.stats)
        left.addWidget(self.chart, 1)

        self.segmap = SegmentMap()
        self.facts: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        for row, key in enumerate(("Status", "Size", "Downloaded", "Time left", "Connections",
                                   "Resume", "Time spent", "Saved to", "Link")):
            name = QLabel(tr(key))
            name.setProperty("muted", True)
            value = QLabel("-")
            value.setWordWrap(False)
            value.setMinimumWidth(120)
            grid.addWidget(name, row, 0)
            grid.addWidget(value, row, 1)
            self.facts[key] = value
        grid.setColumnStretch(1, 1)
        right = QVBoxLayout()
        right.addWidget(self.segmap)
        right.addLayout(grid)
        right.addStretch(1)
        rw = QWidget()
        rw.setLayout(right)
        rw.setMinimumWidth(320)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(24)
        root.addLayout(left, 3)
        root.addWidget(rw, 2)

    def show_overview(self, total_speed: float, history) -> None:
        self.title.setText(tr("All downloads"))
        self.speed.setText(human_speed(total_speed))
        self.stats.setText(" ")
        self.chart.set_values(history)
        self.segmap.set_data(0, ())
        for label in self.facts.values():
            label.setText("-")
            label.setToolTip("")

    def show_snapshot(self, s: Snapshot, history) -> None:
        self.title.setText(s.filename)
        running = s.state == State.DOWNLOADING
        self.speed.setText(human_speed(s.speed) if running else
                           (human_speed(s.avg_speed) if s.state == State.COMPLETED else "-"))
        if s.active_seconds >= 1 and (s.avg_speed > 0):
            self.stats.setText(tr("Average {a}   Max {m}   Min {n}").format(
                a=human_speed(s.avg_speed), m=human_speed(s.max_speed), n=human_speed(s.min_speed)))
        else:
            self.stats.setText(" ")
        self.chart.set_values(history)
        self.segmap.set_data(s.total, s.segments)
        values = {
            "Status": s.error if s.state == State.FAILED else status_text(s),
            "Size": human_size(s.total) if s.total >= 0 else tr("unknown"),
            "Downloaded": f"{human_size(s.downloaded)}  ({s.progress * 100:.1f}%)" if s.total > 0
            else human_size(s.downloaded),
            "Time left": human_time(s.eta) if running else "-",
            "Connections": str(s.connections) if running else "-",
            "Resume": tr("Supported") if s.resumable else tr("Not supported"),
            "Time spent": human_time(s.active_seconds),
            "Saved to": s.directory,
            "Link": s.url,
        }
        for key, text in values.items():
            label = self.facts[key]
            metrics = label.fontMetrics()
            label.setText(metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, 340))
            label.setToolTip(text)

