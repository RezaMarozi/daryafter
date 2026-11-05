"""Custom-painted widgets: live speed chart and the segment map."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..core.fmt import human_speed
from . import theme

SAMPLES = 120          # 60 seconds at two samples per second
_STEPS = [100e3, 250e3, 500e3, 1e6, 2e6, 5e6, 10e6, 20e6, 50e6, 100e6, 200e6, 500e6, 1e9, 2e9, 5e9]


def nice_max(value: float) -> float:
    target = max(value * 1.1, 100e3)
    for step in _STEPS:
        if step >= target:
            return step
    return target


class SpeedChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._values: list[float] = []
        self.setMinimumHeight(110)

    def set_values(self, values) -> None:
        self._values = list(values)[-SAMPLES:]
        self.update()

    def paintEvent(self, _event) -> None:
        c = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(1, 8, -1, -4)
        top = nice_max(max(self._values, default=0.0))
        small = QFont(p.font())
        small.setPointSizeF(8)
        p.setFont(small)
        for i in range(4):
            y = area.top() + area.height() * i / 3
            p.setPen(QPen(QColor(c["border"]), 1))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            if i < 3:
                p.setPen(QColor(c["muted"]))
                p.drawText(QPointF(area.left() + 4, y + 12), human_speed(top * (1 - i / 3)))
        values = self._values
        if len(values) >= 2:
            def point(k: int, v: float) -> QPointF:
                x = area.left() + area.width() * (SAMPLES - len(values) + k) / (SAMPLES - 1)
                return QPointF(x, area.bottom() - area.height() * min(v / top, 1.0))

            line = QPainterPath(point(0, values[0]))
            for k in range(1, len(values)):
                line.lineTo(point(k, values[k]))
            fill = QPainterPath(line)
            fill.lineTo(QPointF(point(len(values) - 1, 0).x(), area.bottom()))
            fill.lineTo(QPointF(point(0, 0).x(), area.bottom()))
            fill.closeSubpath()
            top_color, bottom_color = QColor(c["accent"]), QColor(c["accent"])
            top_color.setAlpha(110)
            bottom_color.setAlpha(8)
            gradient = QLinearGradient(0, area.top(), 0, area.bottom())
            gradient.setColorAt(0, top_color)
            gradient.setColorAt(1, bottom_color)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(gradient)
            p.drawPath(fill)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(c["accent"]), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.drawPath(line)
            last = point(len(values) - 1, values[-1])
            p.setBrush(QColor(c["accent"]))
            p.setPen(QPen(QColor(c["surface"]), 2))
            p.drawEllipse(last, 4, 4)
        p.end()


class SegmentMap(QWidget):
    """One bar for the whole file; each connection's part is filled as it downloads."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._total = 0
        self._segments: tuple = ()
        self.setFixedHeight(16)

    def set_data(self, total: int, segments) -> None:
        self._total = total
        self._segments = tuple(segments)
        self.update()

    def paintEvent(self, _event) -> None:
        c = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 3, 0, -3)
        clip = QPainterPath()
        clip.addRoundedRect(r, 5, 5)
        p.setClipPath(clip)
        p.fillRect(r, QColor(c["track"]))
        if self._total > 0:
            scale = r.width() / self._total
            for start, end, received in self._segments:
                done = max(0, received - start)
                if done > 0:
                    p.fillRect(QRectF(r.left() + start * scale, r.top(), max(1.0, done * scale), r.height()),
                               QColor(c["accent"]))
            p.setPen(QPen(QColor(c["surface"]), 1))
            for start, _end, _received in self._segments[1:]:
                x = r.left() + start * scale
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        p.end()
