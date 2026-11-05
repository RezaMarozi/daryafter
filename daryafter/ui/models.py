"""Table model, filter and painting for the download list."""
from __future__ import annotations

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QRectF, QSize, QSortFilterProxyModel,
                            Qt)
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..core.categories import category_for
from ..core.fmt import human_size, human_speed, human_time
from ..core.models import RUNNING_STATES, Snapshot, State
from ..i18n import tr
from . import theme

COLUMNS = ["Name", "Size", "Progress", "Speed", "Time left", "Status"]
SNAP_ROLE = Qt.ItemDataRole.UserRole
FILTERS = ["All", "Active", "Queued", "Paused", "Completed", "Failed"]

_BADGE = {"Video": "#8E5CF0", "Music": "#E0628A", "Compressed": "#D9902B", "Documents": "#3B82D6",
          "Programs": "#2FA866", "Images": "#14A3A3", "Other": "#7A8699"}


def status_text(s: Snapshot) -> str:
    if s.state == State.QUEUED:
        return tr("Queued")
    if s.state == State.CONNECTING:
        return tr("Connecting...")
    if s.state == State.DOWNLOADING:
        return s.message or tr("Downloading")
    if s.state == State.VERIFYING:
        return tr("Verifying {p}%").format(p=int(s.verify_progress * 100))
    if s.state == State.PAUSED:
        return tr("Paused") if s.downloaded > 0 else tr("Not started")
    if s.state == State.COMPLETED:
        return tr("Completed")
    return tr("Failed")


def matches_filter(s: Snapshot, name: str) -> bool:
    return {"All": True, "Active": s.state in RUNNING_STATES, "Queued": s.state == State.QUEUED,
            "Paused": s.state == State.PAUSED, "Completed": s.state == State.COMPLETED,
            "Failed": s.state == State.FAILED}.get(name, True)


class DownloadsModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[Snapshot] = []
        self._index: dict[int, int] = {}
        self._qpos: dict[int, int] | None = None        # place of each waiting download in the queue

    def _queue_position(self, snap_id: int) -> int:
        if self._qpos is None:
            waiting = sorted((s for s in self._rows if s.state == State.QUEUED), key=lambda s: (-s.priority, s.id))
            self._qpos = {s.id: n for n, s in enumerate(waiting, 1)}
        return self._qpos.get(snap_id, 0)

    def _reindex(self) -> None:
        self._index = {s.id: i for i, s in enumerate(self._rows)}
        self._qpos = None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(COLUMNS[section])
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        s = self._rows[index.row()]
        if role == SNAP_ROLE:
            return s
        if role == Qt.ItemDataRole.DisplayRole:
            col = index.column()
            if col == 0:
                return s.filename
            if col == 1:
                return human_size(s.total) if s.total >= 0 else "-"
            if col == 3:
                return human_speed(s.speed) if s.state == State.DOWNLOADING else ""
            if col == 4:
                return human_time(s.eta) if s.state == State.DOWNLOADING else ""
            if col == 5:
                if s.state == State.QUEUED:
                    return tr("Queued #{n}").format(n=self._queue_position(s.id))
                return status_text(s)
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 0:
            return f"{s.final_path}\n{s.url}"
        return None

    # ---- updates from the engine ----------------------------------------
    def set_all(self, snaps: list[Snapshot]) -> None:
        self.beginResetModel()
        self._rows = sorted(snaps, key=lambda s: s.id, reverse=True)
        self._reindex()
        self.endResetModel()

    def upsert(self, snap: Snapshot) -> None:
        row = self._index.get(snap.id)
        if row is None:
            self.beginInsertRows(QModelIndex(), 0, 0)
            self._rows.insert(0, snap)
            self._reindex()
            self.endInsertRows()
        else:
            self._rows[row] = snap
            self._qpos = None
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))

    def update_many(self, snaps: list[Snapshot]) -> None:
        for snap in snaps:
            row = self._index.get(snap.id)
            if row is not None:
                self._rows[row] = snap
                self._qpos = None
                self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))

    def remove(self, item_id: int) -> None:
        row = self._index.get(item_id)
        if row is not None:
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._rows[row]
            self._reindex()
            self.endRemoveRows()

    def snapshots(self) -> list[Snapshot]:
        return list(self._rows)

    def get(self, item_id: int) -> Snapshot | None:
        row = self._index.get(item_id)
        return self._rows[row] if row is not None else None


class FilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state_filter = "All"
        self.text = ""

    def set_state_filter(self, name: str) -> None:
        self.state_filter = name
        self.invalidateFilter()

    def set_text(self, text: str) -> None:
        self.text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        s = self.sourceModel().index(row, 0, parent).data(SNAP_ROLE)
        if s is None:
            return False
        if not matches_filter(s, self.state_filter):
            return False
        return not self.text or self.text in s.filename.lower() or self.text in s.url.lower()


class RowDelegate(QStyledItemDelegate):
    """Paints the name column (type badge + two lines) and the progress column (bar)."""

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 56)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        col = index.column()
        snap = index.data(SNAP_ROLE)
        if col not in (0, 2) or snap is None:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        c = theme.colors()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect)
        if col == 0:
            self._paint_name(painter, r, snap, c)
        else:
            self._paint_progress(painter, r, snap, c)
        painter.restore()

    def _paint_name(self, p: QPainter, r: QRectF, s: Snapshot, c: dict) -> None:
        badge = QRectF(r.left() + 10, r.center().y() - 16, 32, 32)
        category = s.category or category_for(s.filename)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_BADGE.get(category, _BADGE["Other"])))
        p.drawRoundedRect(badge, 7, 7)
        ext = (s.filename.rsplit(".", 1)[-1] if "." in s.filename else "")[:4].upper()
        f = QFont(p.font())
        f.setPointSizeF(7.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, ext)
        text_rect = QRectF(badge.right() + 10, r.top() + 8, r.width() - 62, 22)
        f = QFont(p.font())
        f.setPointSizeF(10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(c["text"]))
        metrics = p.fontMetrics()
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   metrics.elidedText(s.filename, Qt.TextElideMode.ElideMiddle, int(text_rect.width())))
        sub = QRectF(text_rect.left(), r.top() + 30, text_rect.width(), 18)
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(c["muted"]))
        line = s.host if s.state != State.FAILED else s.error
        p.drawText(sub, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(line, Qt.TextElideMode.ElideRight, int(sub.width())))

    def _paint_progress(self, p: QPainter, r: QRectF, s: Snapshot, c: dict) -> None:
        bar = QRectF(r.left() + 10, r.center().y() - 3, r.width() - 70, 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["track"]))
        p.drawRoundedRect(bar, 3, 3)
        color = {State.COMPLETED: c["ok"], State.FAILED: c["bad"], State.PAUSED: c["warn"]}.get(
            s.state, c["accent"])
        if s.total > 0 or s.state == State.COMPLETED:
            fill = QRectF(bar)
            fill.setWidth(max(0.0, bar.width() * s.progress))
            p.setBrush(QColor(color))
            p.drawRoundedRect(fill, 3, 3)
            label = f"{int(s.progress * 100)}%"
        else:
            label = human_size(s.downloaded)
        f = QFont(p.font())
        f.setPointSizeF(9)
        p.setFont(f)
        p.setPen(QColor(c["text"]))
        p.drawText(QRectF(bar.right() + 6, r.top(), 56, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
