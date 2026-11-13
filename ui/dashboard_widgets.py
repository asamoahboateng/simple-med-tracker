"""
ui/dashboard_widgets.py - The building blocks of the dashboard.

* DividedPanel   - one white panel split into equal cells with thin dividers
* StatCell       - a summary figure (label, big number, note, icon badge)
* AttentionGroup - one "Needs attention" group: heading, count, advice and a list
* ColumnList     - rows of (name, detail) spread over as many columns as fit
* ExpiryShelf    - batches stacked on a shelf, one bay per month (click to select)
* LevelBars, HealthBars, TopList, DailyBars - small charts drawn with QPainter
"""

from datetime import date
import calendar

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolTip, QVBoxLayout,
    QWidget,
)

import logic
from ui import icons, theme
from ui.responsive import FlowGrid

STATUS_FILL = {
    logic.BATCH_EXPIRED: theme.RED, logic.BATCH_EXPIRING: theme.AMBER, logic.BATCH_OK: theme.GREEN,
    logic.STATUS_OUT: theme.RED, logic.STATUS_LOW: theme.AMBER, logic.STATUS_OK: theme.GREEN,
}
STATUS_TEXT = {logic.BATCH_EXPIRED: theme.RED, logic.BATCH_EXPIRING: theme.AMBER_TEXT,
               logic.BATCH_OK: theme.TEXT}


def _font(widget: QWidget, px: int, weight=QFont.Normal) -> QFont:
    font = QFont(widget.font())
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


def _label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


# --------------------------------------------------------------------------
# Panels
# --------------------------------------------------------------------------

class DividedPanel(FlowGrid):
    """A white rounded panel whose cells are separated by thin lines, not gaps."""

    def __init__(self, widgets, min_item_width: int, max_columns: int, parent=None):
        super().__init__(widgets, min_item_width=min_item_width, max_columns=max_columns,
                         spacing=0, parent=parent)

    def columns_for(self, width: int) -> int:
        # Only use column counts that fill every row (3 items: 3 or 1, never 2 + 1).
        columns = super().columns_for(width)
        while columns > 1 and len(self.items) % columns:
            columns -= 1
        return columns

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawRoundedRect(QRectF(self.rect()), 12, 12)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(QPen(QColor(theme.SHELF), 1))
        for widget in self.items:
            g = widget.geometry()
            if g.left() > 2:
                painter.drawLine(g.left(), g.top(), g.left(), g.bottom())
            if g.top() > 2:
                painter.drawLine(g.left(), g.top(), g.right(), g.top())


class Panel(QFrame):
    """A white rounded panel with a heading row. Put content in panel.body."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 22, 24, 24)
        self.body.setSpacing(12)
        self.header = QHBoxLayout()
        self.header.setSpacing(10)
        self.title_label = _label(title, "panelHeading")
        self.header.addWidget(self.title_label)
        self.header.addStretch()
        self.body.addLayout(self.header)
        if subtitle:
            self.body.addWidget(_label(subtitle, "muted", wrap=True))


def sample_tag(text: str) -> QLabel:
    return _label(text, "sampleTag")


# --------------------------------------------------------------------------
# Summary figures
# --------------------------------------------------------------------------

class StatCell(QWidget):
    def __init__(self, title: str, icon_name: str, icon_colour: str, icon_bg: str, parent=None):
        super().__init__(parent)
        self.setObjectName("panelCell")
        self.setMinimumWidth(180)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = _label(title, "statLabel", wrap=True)
        self.value = _label("-", "statValue")
        self.note = _label("", "statNote", wrap=True)
        for label in (self.title, self.value, self.note):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            text.addWidget(label)
        badge = QLabel()
        badge.setPixmap(icons.badge(icon_name, icon_colour, icon_bg))
        row = QHBoxLayout(self)
        row.setContentsMargins(24, 18, 20, 18)
        row.setSpacing(14)
        row.addLayout(text, 1)
        row.addWidget(badge, 0, Qt.AlignTop)

    def set_value(self, value: int, note: str, colour: str | None = None) -> None:
        self.value.setText(f"{value:,}")
        self.value.setStyleSheet(f"color: {colour or theme.TEXT};")
        self.note.setText(note)


# --------------------------------------------------------------------------
# Lists
# --------------------------------------------------------------------------

class ListRow(QWidget):
    """One list line: name on the left, a short detail on the right, a rule above."""

    def __init__(self, name: str, detail: str, detail_colour: str, bold_detail: bool, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 8, 0, 8)
        row.setSpacing(12)
        name_label = _label(name, wrap=True)
        name_label.setStyleSheet("font-weight: 500;")
        name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        detail_label = _label(detail)
        detail_label.setStyleSheet(f"color: {detail_colour};"
                                   + (" font-weight: 700;" if bold_detail else ""))
        row.addWidget(name_label, 1)
        row.addWidget(detail_label, 0, Qt.AlignTop)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QPen(QColor(theme.RULE), 1))
        painter.drawLine(0, 0, self.width(), 0)


class ColumnList(QWidget):
    """(name, detail) rows laid out top-to-bottom in as many columns as fit the width."""

    def __init__(self, min_column_width: int = 300, max_columns: int = 4, parent=None):
        super().__init__(parent)
        self.min_column_width = min_column_width
        self.max_columns = max_columns
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(32)
        self.grid.setVerticalSpacing(0)
        self.rows: list[ListRow] = []
        self.columns = 0

    def set_rows(self, rows, detail_colour: str | None = None, bold_detail: bool = False):
        for widget in self.rows:
            widget.deleteLater()
        detail_colour = detail_colour or theme.TEXT_MUTED
        self.rows = [ListRow(name, detail, detail_colour, bold_detail) for name, detail in rows]
        self.columns = 0
        self._arrange(self.width())

    def _columns_for(self, width: int) -> int:
        return max(1, min(self.max_columns, (width + 32) // (self.min_column_width + 32)))

    def _arrange(self, width: int) -> None:
        columns = self._columns_for(width)
        if columns == self.columns:
            return
        self.columns = columns
        for widget in self.rows:
            self.grid.removeWidget(widget)
        per_column = -(-len(self.rows) // columns) if self.rows else 0
        for i, widget in enumerate(self.rows):
            self.grid.addWidget(widget, i % per_column, i // per_column)
        for c in range(self.max_columns):
            self.grid.setColumnStretch(c, 1 if c < columns else 0)
        self.updateGeometry()

    def resizeEvent(self, event):
        self._arrange(event.size().width())
        super().resizeEvent(event)


class AttentionGroup(QWidget):
    """Heading with a status mark and count, one line of advice, then the first few items."""

    SHOWN = 6

    def __init__(self, title: str, advice: str, colour: str, count_colour: str,
                 diamond: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("panelCell")
        self.setMinimumWidth(260)
        self.count_colour = count_colour
        self.rows: list[tuple[str, str]] = []
        self.detail_colour = theme.TEXT_MUTED
        self.expanded = False

        mark = QLabel()
        mark.setFixedSize(12, 12)
        mark.setStyleSheet(f"background: {colour}; border-radius: {2 if diamond else 6}px;")
        self.count = _label("0")
        self.count.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {count_colour};")
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(mark)
        head.addWidget(_label(title, "groupHeading"), 1)
        head.addWidget(self.count)

        self.list = ColumnList(max_columns=1)
        self.empty = _label("Nothing here.", "muted")
        self.toggle = QPushButton()
        self.toggle.setProperty("kind", "link")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.clicked.connect(self._toggle)

        col = QVBoxLayout(self)
        col.setContentsMargins(24, 22, 24, 16)
        col.setSpacing(10)
        col.addLayout(head)
        col.addWidget(_label(advice, "muted", wrap=True))
        col.addWidget(self.list)
        col.addWidget(self.empty)
        col.addWidget(self.toggle, 0, Qt.AlignLeft)
        col.addStretch()

    def set_rows(self, rows: list[tuple[str, str]], detail_colour: str, bold_detail: bool = True):
        self.rows, self.detail_colour, self.bold_detail = rows, detail_colour, bold_detail
        self.count.setText(f"{len(rows):,}")
        self._render()

    def _toggle(self):
        self.expanded = not self.expanded
        self._render()

    def _render(self):
        shown = self.rows if self.expanded else self.rows[:self.SHOWN]
        self.list.set_rows(shown, self.detail_colour, self.bold_detail)
        self.empty.setVisible(not self.rows)
        self.toggle.setVisible(len(self.rows) > self.SHOWN)
        self.toggle.setText("Show fewer" if self.expanded else f"Show all {len(self.rows):,}")


# --------------------------------------------------------------------------
# Expiry shelf
# --------------------------------------------------------------------------

class ExpiryShelf(QWidget):
    """
    One bay per bucket (Expired, then each month). Every block in a bay is one batch.
    The bays inside the expiry warning period sit on an amber band. Click a bay, or
    use the arrow keys, to select it.
    """

    selected_changed = Signal(int)

    BAND_H, BAY_H, PLANK_H, LABEL_H, GAP = 30, 270, 6, 44, 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.buckets: list[dict] = []
        self.selected = 0
        self.hovered = -1
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(480)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(self.BAND_H + self.BAY_H + self.PLANK_H + self.LABEL_H)

    def sizeHint(self):
        return QSize(900, self.height())

    def set_buckets(self, buckets: list[dict]) -> None:
        self.buckets = buckets
        self.selected = min(self.selected, max(len(buckets) - 1, 0))
        self._update_accessible()
        self.update()

    def select(self, index: int) -> None:
        if 0 <= index < len(self.buckets) and index != self.selected:
            self.selected = index
            self._update_accessible()
            self.update()
            self.selected_changed.emit(index)

    def bucket_name(self, index: int) -> str:
        b = self.buckets[index]
        return "Expired" if not b["year"] else f"{b['label']} {b['year']}"

    def _update_accessible(self):
        if self.buckets:
            b = self.buckets[self.selected]
            self.setAccessibleName(f"Expiry shelf, {self.bucket_name(self.selected)} selected, "
                                   f"{len(b['batches'])} batches")

    # --- geometry --------------------------------------------------------------
    def _bay_rect(self, i: int) -> QRectF:
        n = len(self.buckets)
        width = (self.width() - self.GAP * (n - 1)) / n
        return QRectF(i * (width + self.GAP), self.BAND_H, width, self.BAY_H)

    def _index_at(self, x: float, y: float) -> int:
        for i in range(len(self.buckets)):
            r = self._bay_rect(i)
            if r.left() <= x <= r.right() and y <= self.height():
                return i
        return -1

    # --- painting --------------------------------------------------------------
    def paintEvent(self, event):
        if not self.buckets:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        warn = [i for i, b in enumerate(self.buckets) if b["status"] == logic.BATCH_EXPIRING]
        if warn:
            left, right = self._bay_rect(warn[0]).left(), self._bay_rect(warn[-1]).right()
            p.setPen(QColor(theme.AMBER_TEXT))
            p.setFont(_font(self, 13, QFont.Bold))
            p.drawText(QRectF(left, 0, right - left, self.BAND_H - 8),
                       Qt.AlignLeft | Qt.AlignVCenter, f"Next {logic.EXPIRY_WARNING_DAYS} days")
            p.fillRect(QRectF(left, self.BAND_H - 8, right - left, 2), QColor(theme.AMBER))

        count_font = _font(self, 18, QFont.ExtraBold)
        for i, bucket in enumerate(self.buckets):
            r = self._bay_rect(i)
            selected = i == self.selected
            if selected:
                bg = QColor(theme.SURFACE)
            elif bucket["status"] == logic.BATCH_EXPIRING:
                bg = QColor(theme.AMBER_TINT)
            else:
                bg = QColor(0, 0, 0, 0)
            if i == self.hovered and not selected:
                bg = QColor(theme.SURFACE) if bg.alpha() == 0 else bg.darker(103)
            path = QPainterPath()
            path.addRoundedRect(r.adjusted(0, 0, 0, 10), 8, 8)
            p.save()
            p.setClipRect(r)
            p.fillPath(path, bg)
            if selected:
                p.setPen(QPen(QColor(theme.TEXT), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(1, 1, -1, 10), 8, 8)
            p.restore()
            if selected and self.hasFocus():
                p.setPen(QPen(QColor(theme.AMBER), 3))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), 10, 10)

            # One block per batch, stacked from the shelf upwards.
            n = len(bucket["batches"])
            room = self.BAY_H - 16 - 30
            block_h, gap = 8.0, 3.0
            if n * (block_h + gap) > room:
                gap = 2.0
                block_h = max(2.0, (room - gap * (n - 1)) / max(n, 1))
            block_w = min(46.0, r.width() - 12)
            x = r.center().x() - block_w / 2
            y = r.bottom() - 6
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(STATUS_FILL[bucket["status"]]))
            for _ in range(n):
                y -= block_h
                p.drawRoundedRect(QRectF(x, y, block_w, block_h), 3, 3)
                y -= gap
            p.setPen(QColor(STATUS_TEXT[bucket["status"]]))
            p.setFont(count_font)
            p.drawText(QRectF(r.left(), y - 28, r.width(), 26), Qt.AlignCenter, str(n))

        plank_top = self.BAND_H + self.BAY_H
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.TEXT))
        p.drawRoundedRect(QRectF(0, plank_top, self.width(), self.PLANK_H), 2, 2)

        for i, bucket in enumerate(self.buckets):
            r = self._bay_rect(i)
            top = plank_top + self.PLANK_H + 6
            p.setPen(QColor(theme.TEXT))
            p.setFont(_font(self, 14, QFont.ExtraBold if i == self.selected else QFont.Medium))
            p.drawText(QRectF(r.left() - 3, top, r.width() + 6, 18), Qt.AlignCenter,
                       bucket["label"])
            if bucket["year"]:
                p.setPen(QColor(theme.TEXT_MUTED))
                p.setFont(_font(self, 12))
                p.drawText(QRectF(r.left(), top + 18, r.width(), 16), Qt.AlignCenter,
                           bucket["year"])

    # --- interaction -----------------------------------------------------------
    def mouseMoveEvent(self, event):
        index = self._index_at(event.position().x(), event.position().y())
        if index != self.hovered:
            self.hovered = index
            self.update()
        if index >= 0:
            n = len(self.buckets[index]["batches"])
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{self.bucket_name(index)}: {n} batch{'es' if n != 1 else ''}", self)

    def leaveEvent(self, event):
        self.hovered = -1
        self.update()

    def mousePressEvent(self, event):
        index = self._index_at(event.position().x(), event.position().y())
        if index >= 0:
            self.select(index)

    def keyPressEvent(self, event):
        step = {Qt.Key_Left: -1, Qt.Key_Right: 1}.get(event.key())
        if step:
            self.select(self.selected + step)
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event):
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.update()
        super().focusOutEvent(event)


# --------------------------------------------------------------------------
# Small charts
# --------------------------------------------------------------------------

class LevelBars(QWidget):
    """Rows of stock against reorder level: a bar, a line at the reorder level, 'stock / level'."""

    ROW_H = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict] = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_rows(self, rows: list[dict]) -> None:
        self.rows = rows
        self.setFixedHeight(max(1, len(rows)) * self.ROW_H)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        name_w, label_w = w * 0.38, 86
        track_x = name_w + 12
        track_w = max(40, w - track_x - label_w - 12)
        name_font, label_font = _font(self, 14, QFont.Medium), _font(self, 14, QFont.Bold)
        metrics = QFontMetrics(name_font)
        for i, m in enumerate(self.rows):
            top = i * self.ROW_H
            mid = top + self.ROW_H / 2
            p.setFont(name_font)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(0, top, name_w, self.ROW_H), Qt.AlignLeft | Qt.AlignVCenter,
                       metrics.elidedText(m["name"], Qt.ElideRight, int(name_w)))
            scale = max(m["reorder_level"] * 1.6, m["stock"] * 1.05)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.RULE))
            p.drawRoundedRect(QRectF(track_x, mid - 7, track_w, 14), 4, 4)
            p.setBrush(QColor(STATUS_FILL[m["status"]]))
            p.drawRoundedRect(QRectF(track_x, mid - 7, track_w * m["stock"] / scale, 14), 4, 4)
            mark = track_x + track_w * m["reorder_level"] / scale
            p.fillRect(QRectF(mark - 1, mid - 11, 2, 22), QColor(theme.TEXT))
            p.setFont(label_font)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(w - label_w, top, label_w, self.ROW_H), Qt.AlignRight | Qt.AlignVCenter,
                       f"{m['stock']:,} / {m['reorder_level']:,}")


class HealthBars(QWidget):
    """For each group, a stacked bar of its parts and a legend with the counts."""

    GROUP_H = 76

    def __init__(self, parent=None):
        super().__init__(parent)
        self.groups: list[tuple[str, list[tuple[str, int, str]]]] = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_groups(self, groups) -> None:
        self.groups = groups
        self.setFixedHeight(len(groups) * self.GROUP_H + (len(groups) - 1) * 16)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        for g, (title, parts) in enumerate(self.groups):
            top = g * (self.GROUP_H + 16)
            total = sum(n for _, n, _ in parts)
            p.setPen(QColor(theme.TEXT))
            p.setFont(_font(self, 14, QFont.Bold))
            p.drawText(QRectF(0, top, w, 20), Qt.AlignLeft | Qt.AlignVCenter, title)
            p.setPen(QColor(theme.TEXT_MUTED))
            p.setFont(_font(self, 14))
            p.drawText(QRectF(0, top, w, 20), Qt.AlignRight | Qt.AlignVCenter, f"{total:,}")

            bar = QRectF(0, top + 26, w, 18)
            clip = QPainterPath()
            clip.addRoundedRect(bar, 4, 4)
            p.save()
            p.setClipPath(clip)
            p.fillRect(bar, QColor(theme.RULE))
            x = 0.0
            shown = [(n, c) for _, n, c in parts if n]
            for k, (n, colour) in enumerate(shown):
                width = w * n / total if total else 0
                gap = 2 if k < len(shown) - 1 else 0
                p.fillRect(QRectF(x, bar.top(), max(width - gap, 1), bar.height()), QColor(colour))
                x += width
            p.restore()

            x = 0.0
            legend_y = top + 52
            for label, n, colour in parts:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(colour))
                p.drawRoundedRect(QRectF(x, legend_y + 5, 10, 10), 2, 2)
                p.setPen(QColor(theme.TEXT))
                p.setFont(_font(self, 14))
                text = f"{label} "
                p.drawText(QRectF(x + 16, legend_y, 200, 20), Qt.AlignLeft | Qt.AlignVCenter, text)
                x += 16 + QFontMetrics(_font(self, 14)).horizontalAdvance(text)
                bold = _font(self, 14, QFont.Bold)
                p.setFont(bold)
                p.drawText(QRectF(x, legend_y, 200, 20), Qt.AlignLeft | Qt.AlignVCenter, f"{n:,}")
                x += QFontMetrics(bold).horizontalAdvance(f"{n:,}") + 18


class TopList(QWidget):
    """Most dispensed medicines: name with a bar underneath, quantity on the right."""

    ROW_H = 46

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[tuple[str, int]] = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_rows(self, rows) -> None:
        self.rows = rows
        self.setFixedHeight(max(1, len(rows)) * self.ROW_H)
        self.update()

    def paintEvent(self, event):
        if not self.rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        top_qty = self.rows[0][1] or 1
        name_font, qty_font = _font(self, 14, QFont.Medium), _font(self, 14, QFont.Bold)
        metrics = QFontMetrics(name_font)
        for i, (name, qty) in enumerate(self.rows):
            top = i * self.ROW_H
            p.fillRect(QRectF(0, top, w, 1), QColor(theme.RULE))
            p.setPen(QColor(theme.TEXT))
            p.setFont(name_font)
            p.drawText(QRectF(0, top + 6, w - 80, 20), Qt.AlignLeft | Qt.AlignVCenter,
                       metrics.elidedText(name, Qt.ElideRight, w - 80))
            p.setFont(qty_font)
            p.drawText(QRectF(w - 72, top, 72, self.ROW_H), Qt.AlignRight | Qt.AlignVCenter,
                       f"{qty:,}")
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.TEXT))
            p.drawRoundedRect(QRectF(0, top + 31, (w - 80) * qty / top_qty, 6), 3, 3)


class DailyBars(QWidget):
    """Quantity dispensed per day across the whole month; days still to come are grey stubs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.daily: list[tuple[date, int]] = []
        self.setFixedHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_days(self, daily) -> None:
        self.daily = daily
        self.update()

    def paintEvent(self, event):
        if not self.daily:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        first = self.daily[0][0]
        days_in_month = calendar.monthrange(first.year, first.month)[1]
        chart_h = self.height() - 28
        w = self.width()
        gap = 3
        slot = (w - gap * (days_in_month - 1)) / days_in_month
        peak = max((q for _, q in self.daily), default=0) or 1
        values = {d.day: q for d, q in self.daily}
        for day in range(1, days_in_month + 1):
            x = (day - 1) * (slot + gap)
            if day in values:
                h = max(2.0, (chart_h - 8) * values[day] / peak)
                colour = theme.TEXT
            else:
                h, colour = 2.0, theme.SHELF
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(colour))
            p.drawRoundedRect(QRectF(x, chart_h - h, slot, h + 2), 2, 2)
        p.fillRect(QRectF(0, chart_h, w, 2), QColor(theme.TEXT))
        p.setPen(QColor(theme.TEXT_MUTED))
        p.setFont(_font(self, 12))
        label_rect = QRectF(0, chart_h + 6, w, 18)
        p.drawText(label_rect, Qt.AlignLeft, first.strftime("1 %b"))
        p.drawText(label_rect, Qt.AlignRight, f"{days_in_month} {first:%b}")
        today_x = (len(self.daily) - 0.5) * (slot + gap)
        if 40 < today_x < w - 60:
            p.drawText(QRectF(today_x - 40, chart_h + 6, 80, 18), Qt.AlignCenter, "Today")
