"""
ui/models.py - Shared table model and filter/sort proxy used by every table.

RecordTableModel shows a list of dicts. Each Column says which dict key to show,
its header, alignment, optional formatter and whether it can be edited.
TableProxy adds sorting (numbers sort as numbers, dates as dates) and filtering.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate, QTableView,
)

import logic

SORT_ROLE = Qt.UserRole + 1

# (background, text) colours for status values.
GREEN = ("#dcf3e5", "#17663a")
AMBER = ("#fdefd3", "#8a5300")
RED = ("#fbdcdc", "#9b1c1c")
GREY = ("#eceff4", "#5b6778")
BLUE = ("#e2eafb", "#24479e")

STATUS_COLOURS = {
    logic.STATUS_OK: GREEN,
    logic.STATUS_LOW: AMBER,
    logic.STATUS_OUT: RED,
    logic.BATCH_EXPIRING: AMBER,
    logic.BATCH_EXPIRED: RED,
    logic.BATCH_USED_UP: GREY,
    logic.STOCK_IN: GREEN,
    logic.DISPENSED: BLUE,
}

@dataclass
class Column:
    key: str
    header: str
    align: str = "left"                             # "left", "right" or "center"
    fmt: Optional[Callable[[Any], str]] = None      # value -> display text
    editable: bool = False


def int_fmt(value) -> str:
    return "" if value is None else f"{int(value):,}"


class RecordTableModel(QAbstractTableModel):
    """A read-only (optionally editable) table over a list of dicts."""

    def __init__(self, columns: list[Column], parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows: list[dict] = []
        # colour_fn(row_dict, column_key) -> (background, text) or None
        self.colour_fn: Optional[Callable[[dict, str], Optional[tuple[str, str]]]] = None
        # edit_fn(row_dict, column_key, new_value) -> True if saved
        self.edit_fn: Optional[Callable[[dict, str, Any], bool]] = None

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def row_dict(self, source_row: int) -> dict:
        return self.rows[source_row]

    # --- Qt model interface -------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = self.columns[index.column()]
        value = row.get(col.key)

        if role == Qt.DisplayRole:
            if col.fmt:
                return col.fmt(value)
            return "" if value is None else str(value)
        if role == Qt.EditRole:
            return value
        if role == SORT_ROLE:
            return value
        if role == Qt.TextAlignmentRole:
            horizontal = {"right": Qt.AlignRight, "center": Qt.AlignHCenter}.get(col.align,
                                                                                Qt.AlignLeft)
            return int(horizontal | Qt.AlignVCenter)
        if role in (Qt.BackgroundRole, Qt.ForegroundRole) and self.colour_fn:
            colours = self.colour_fn(row, col.key)
            if colours:
                return QBrush(QColor(colours[0] if role == Qt.BackgroundRole else colours[1]))
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return self.columns[section].header
        if role == Qt.TextAlignmentRole:
            horizontal = {"right": Qt.AlignRight, "center": Qt.AlignHCenter}.get(
                self.columns[section].align, Qt.AlignLeft)
            return int(horizontal | Qt.AlignVCenter)
        return None

    def flags(self, index):
        base = super().flags(index)
        if index.isValid() and self.columns[index.column()].editable:
            return base | Qt.ItemIsEditable
        return base

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid() or self.edit_fn is None:
            return False
        row = self.rows[index.row()]
        key = self.columns[index.column()].key
        if self.edit_fn(row, key, value):
            row[key] = value
            self.dataChanged.emit(index, index)
            return True
        return False


class TableProxy(QSortFilterProxyModel):
    """
    Sorts by the raw values (not the displayed text) and filters rows with:
      * filter_fn(row_dict) -> bool   (custom filters, e.g. date range)
      * the standard text filter across all columns (setFilterFixedString)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_fn: Optional[Callable[[dict], bool]] = None
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setFilterKeyColumn(-1)       # search every column
        self.setSortRole(SORT_ROLE)

    def refilter(self) -> None:
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if self.filter_fn is not None:
            if not self.filter_fn(self.sourceModel().row_dict(source_row)):
                return False
        return super().filterAcceptsRow(source_row, source_parent)

    def lessThan(self, left, right):
        a, b = left.data(SORT_ROLE), right.data(SORT_ROLE)
        if a is None or b is None:           # blanks sort first
            return a is None and b is not None
        try:
            return a < b
        except TypeError:
            return str(a).casefold() < str(b).casefold()

    def visible_rows(self) -> list[dict]:
        """Rows currently shown, in the order shown (used for exports)."""
        src = self.sourceModel()
        return [src.row_dict(self.mapToSource(self.index(r, 0)).row())
                for r in range(self.rowCount())]


def make_table(model: RecordTableModel, proxy: TableProxy) -> QTableView:
    """Create a QTableView with the standard MedTracker settings."""
    proxy.setSourceModel(model)
    view = QTableView()
    view.setModel(proxy)
    view.setSortingEnabled(True)
    view.setAlternatingRowColors(True)
    view.setShowGrid(False)
    view.setFocusPolicy(Qt.StrongFocus)
    view.setWordWrap(False)
    view.sortByColumn(-1, Qt.AscendingOrder)   # keep the original row order until a header is clicked
    view.setSelectionBehavior(QAbstractItemView.SelectRows)
    view.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(36)
    header = view.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(True)
    header.setHighlightSections(False)
    model.modelReset.connect(view.resizeColumnsToContents)
    return view


def status_colour_fn(status_key: str = "status"):
    """colour_fn that colours only the status column."""
    def fn(row: dict, key: str):
        if key == status_key:
            return STATUS_COLOURS.get(row.get(status_key))
        return None
    return fn


class PillDelegate(QStyledItemDelegate):
    """Draws a column's value as a coloured rounded "pill" badge (for status columns)."""

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        hint.setWidth(hint.width() + 36)
        return hint

    def paint(self, painter: QPainter, option, index):
        # Draw the normal row background (selection / alternate colour) first.
        opt = option.__class__(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.backgroundBrush = QBrush()
        style = opt.widget.style() if opt.widget else None
        if style:
            style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        text = index.data(Qt.DisplayRole) or ""
        colours = STATUS_COLOURS.get(index.data(Qt.EditRole)) or GREY
        if not text:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont(option.font)
        font.setBold(True)
        font.setPointSizeF(max(font.pointSizeF() - 1.5, 8))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 20
        height = metrics.height() + 6
        rect = option.rect
        x = rect.x() + max((rect.width() - width) / 2, 4)
        y = rect.y() + (rect.height() - height) / 2
        pill = QRectF(x, y, min(width, rect.width() - 8), height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colours[0]))
        painter.drawRoundedRect(pill, height / 2, height / 2)
        painter.setPen(QColor(colours[1]))
        painter.drawText(pill, Qt.AlignCenter, text)
        painter.restore()


def use_pills(view: QTableView, columns: list[Column], *keys: str) -> None:
    """Show the given columns of a table as pill badges."""
    delegate = PillDelegate(view)
    for i, col in enumerate(columns):
        if col.key in keys:
            view.setItemDelegateForColumn(i, delegate)
