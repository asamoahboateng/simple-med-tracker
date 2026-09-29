"""
ui/responsive.py - Layout helpers that adapt to the window size.

* FlowGrid   - puts widgets in as many equal columns as fit, wrapping to new rows
               (e.g. 4 summary cards -> 2 x 2 -> 1 per row as the window narrows).
* FlowLayout - like text wrapping for widgets of different widths (filter bars).
"""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QGridLayout, QLayout, QSizePolicy, QWidget


class FlowGrid(QWidget):
    """
    Shows `widgets` in a grid whose column count depends on the available width:
    as many columns as fit with at least `min_item_width` pixels each, but never
    more than `max_columns`. Every column gets the same width.
    """

    def __init__(self, widgets, min_item_width: int = 220, max_columns: int | None = None,
                 spacing: int = 16, parent=None):
        super().__init__(parent)
        self.items = list(widgets)
        self.min_item_width = min_item_width
        self.max_columns = max_columns or len(self.items)
        self.spacing = spacing
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(spacing)
        # Don't let the current column count dictate a minimum width, otherwise the
        # window could never get narrow enough to switch to fewer columns.
        self.grid.setSizeConstraint(QLayout.SetNoConstraint)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._arrange(self.max_columns)

    def columns_for(self, width: int) -> int:
        fit = (width + self.spacing) // (self.min_item_width + self.spacing)
        fit = max(1, min(self.max_columns, fit))
        # Keep rows balanced: 5 cards that can't fit in one row become 3 + 2 (not 4 + 1),
        # 4 cards that can't fit in one row become 2 + 2 (not 3 + 1).
        rows = -(-len(self.items) // fit)          # ceiling division
        return -(-len(self.items) // rows)

    def _arrange(self, columns: int) -> None:
        if columns == self.columns:
            return
        for widget in self.items:
            self.grid.removeWidget(widget)
        for c in range(max(self.columns, columns, 1)):
            self.grid.setColumnStretch(c, 0)
        for i, widget in enumerate(self.items):
            self.grid.addWidget(widget, i // columns, i % columns)
        for c in range(columns):
            self.grid.setColumnStretch(c, 1)
        self.columns = columns

    def resizeEvent(self, event):
        before = self.columns
        self._arrange(self.columns_for(event.size().width()))
        super().resizeEvent(event)
        # Always re-apply child positions for the new size (the grid may have just been
        # rearranged while Qt was already in the middle of a layout pass).
        self.grid.activate()
        self.grid.setGeometry(self.rect())
        if self.columns != before:
            self.updateGeometry()   # our height changed: ask the parent to re-layout

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), self.min_item_width), hint.height())


class FlowLayout(QLayout):
    """Places widgets left to right and wraps to a new line when the row is full."""

    def __init__(self, parent=None, spacing: int = 10):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # --- QLayout interface ---
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self):
        """Preferred size: everything on one line."""
        hints = [item.sizeHint() for item in self._items]
        m = self.contentsMargins()
        width = sum(h.width() for h in hints) + self._spacing * max(len(hints) - 1, 0)
        height = max((h.height() for h in hints), default=0)
        return QSize(width + m.left() + m.right(), height + m.top() + m.bottom())

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, apply: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_height = area.x(), area.y(), 0
        rows: list[list] = [[]]
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and rows[-1]:
                rows.append([])
                x = area.x()
                y += line_height + self._spacing
                line_height = 0
            rows[-1].append((item, x, y, hint))
            x += hint.width() + self._spacing
            line_height = max(line_height, hint.height())
        if apply:
            for row in rows:
                if not row:
                    continue
                # Items that may grow (e.g. a search box) share the row's spare width.
                used = row[-1][1] + row[-1][3].width() - area.x()
                spare = max(0, area.width() - used)
                growers = [it for it, *_ in row
                           if it.widget() and it.widget().sizePolicy().horizontalPolicy()
                           in (QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)]
                extra = spare // len(growers) if growers else 0
                shift = 0
                height = max(h.height() for *_, h in row)
                for item, ix, iy, hint in row:
                    width = hint.width() + (extra if item in growers else 0)
                    item.setGeometry(QRect(QPoint(ix + shift, iy + (height - hint.height()) // 2),
                                           QSize(width, hint.height())))
                    if item in growers:
                        shift += extra
        return y + line_height - rect.y() + m.bottom()
