"""
ui/report_widgets.py - Charts for the report page, drawn with QPainter.

Every chart takes its colours from the theme when it paints, so it follows the
colour preset. Charts that respond to the mouse emit `hovered(text)` with a
one-line readout, or "" when the mouse leaves; the page shows it as a caption.

* FigureCell  - label, big value, note (one cell of the figures strip)
* DayCalendar - Monday-first calendar of the period, days shaded by quantity
* PaceChart   - cumulative units, this period against the one before (dashed)
* ColumnChart - one column per category (weekdays, hours)
* BarList     - labelled horizontal bars (top medicines, days of stock left)
* ShareBar    - one 100% stacked bar with a legend row per part
* ShareDelegate - draws a table cell's percentage as a bar
"""

import calendar
from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QLabel, QSizePolicy, QStyle, QStyledItemDelegate, QToolTip, QVBoxLayout, QWidget,
)

from ui import theme

# Categorical colours for prescribers, checked as a set for colour-blind separation
# (blue, aqua, violet, magenta). They are never red, amber or green, which mean status.
SERIES = ["#2a78d6", "#1baf7a", "#6250d6", "#e87ba4"]
NEUTRAL = "#aebab6"          # "not recorded" and similar catch-all parts


def _font(widget: QWidget, px: int, weight=QFont.Normal) -> QFont:
    font = QFont(widget.font())
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


def mix(colour: str, other: str, t: float) -> QColor:
    """`colour` blended towards `other` by t (0 = colour, 1 = other)."""
    a, b = QColor(colour), QColor(other)
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def soft() -> QColor:
    """The lighter tone of the brand colour used for columns that aren't highlighted."""
    return mix(theme.TEXT, "#ffffff", 0.55)


def _empty(painter: QPainter, widget: QWidget, text: str) -> None:
    painter.setPen(QColor(theme.TEXT_MUTED))
    painter.setFont(_font(widget, 14))
    painter.drawText(QRectF(widget.rect()), Qt.AlignCenter, text)


class FigureCell(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("panelCell")
        self.setMinimumWidth(170)
        col = QVBoxLayout(self)
        col.setContentsMargins(24, 18, 20, 18)
        col.setSpacing(2)
        self.label = QLabel(label)
        self.label.setObjectName("statLabel")
        self.value = QLabel("-")
        self.value.setObjectName("statValue")
        self.note = QLabel("")
        self.note.setObjectName("statNote")
        self.note.setWordWrap(True)
        for widget in (self.label, self.value, self.note):
            widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            col.addWidget(widget)
        col.addStretch()

    def set_value(self, value: str, note: str, strong_note: bool = False) -> None:
        self.value.setText(value)
        self.note.setText(note)
        self.note.setStyleSheet(f"color: {theme.TEXT}; font-weight: 700;" if strong_note else "")


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------

class DayCalendar(QWidget):
    """
    The period as a Monday-first calendar. Each day is shaded by how much was
    dispensed; the five busiest carry their rank; days still to come are hatched.
    Click a day (or use the arrow keys) to select it.
    """

    day_selected = Signal(object)          # a date
    HEADER, GAP = 24, 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.qty: dict[date, int] = {}
        self.start = self.end = self.calendar_end = self.today = date.today()
        self.selected: date | None = None
        self.ranks: dict[date, int] = {}
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(420)

    def set_period(self, daily, start: date, end: date, calendar_end: date, today: date,
                   selected: date | None) -> None:
        self.qty = dict(daily)
        self.start, self.end, self.calendar_end, self.today = start, end, calendar_end, today
        busiest = sorted((d for d, q in daily if q > 0), key=lambda d: (-self.qty[d], d))[:5]
        self.ranks = {d: i + 1 for i, d in enumerate(busiest)}
        self.selected = selected
        self.first = start - timedelta(days=start.weekday())
        last = calendar_end + timedelta(days=6 - calendar_end.weekday())
        self.weeks = ((last - self.first).days + 1) // 7
        self.compact = self.weeks > 6
        self.cell_h = 54 if self.compact else 84
        self.setFixedHeight(self.HEADER + self.weeks * (self.cell_h + self.GAP))
        self.setAccessibleName("Calendar of units dispensed each day")
        self.update()

    def sizeHint(self):
        return QSize(640, self.height())

    def _cell(self, d: date) -> QRectF:
        i = (d - self.first).days
        w = (self.width() - self.GAP * 6) / 7
        return QRectF((i % 7) * (w + self.GAP), self.HEADER + (i // 7) * (self.cell_h + self.GAP),
                      w, self.cell_h)

    def _day_at(self, pos) -> date | None:
        w = (self.width() - self.GAP * 6) / 7
        col = int(pos.x() // (w + self.GAP))
        row = int((pos.y() - self.HEADER) // (self.cell_h + self.GAP))
        if pos.y() < self.HEADER or not (0 <= col < 7 and 0 <= row < self.weeks):
            return None
        d = self.first + timedelta(days=row * 7 + col)
        return d if self.start <= d <= self.end else None

    def _shade(self, q: int, peak: int) -> tuple[QColor, QColor]:
        """Background and text colour: one hue, light to dark (white text on the dark steps)."""
        r = q / peak
        if r < 0.4:
            return mix(theme.TEXT, "#ffffff", 0.88), QColor(theme.TEXT)
        if r < 0.7:
            return mix(theme.TEXT, "#ffffff", 0.72), QColor(theme.TEXT)
        if r < 0.9:
            return mix(theme.TEXT, "#ffffff", 0.22), QColor("#ffffff")
        return QColor(theme.TEXT), QColor("#ffffff")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = (self.width() - self.GAP * 6) / 7
        p.setPen(QColor(theme.TEXT_MUTED))
        p.setFont(_font(self, 13, QFont.Bold))
        for i, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            p.drawText(QRectF(i * (w + self.GAP) + 4, 0, w, self.HEADER - 6),
                       Qt.AlignLeft | Qt.AlignVCenter, name)

        peak = max(self.qty.values(), default=0) or 1
        label_font, qty_font = _font(self, 13, QFont.Bold), _font(self, 15 if self.compact else 22, QFont.ExtraBold)
        for k in range(self.weeks * 7):
            d = self.first + timedelta(days=k)
            r = self._cell(d)
            label = f"{d.day} {calendar.month_abbr[d.month]}" if d.day == 1 or d == self.start else str(d.day)
            if self.end < d <= self.calendar_end:                       # still to come
                p.save()
                path = QPainterPath()
                path.addRoundedRect(r, 8, 8)
                p.setClipPath(path)
                p.fillRect(r, mix(theme.BG, "#ffffff", 0.5))
                p.setPen(QPen(QColor(theme.BORDER), 1))
                x = r.left() - r.height()
                while x < r.right():
                    p.drawLine(QPointF(x, r.bottom()), QPointF(x + r.height(), r.top()))
                    x += 9
                p.restore()
                p.setPen(QColor(theme.TEXT_MUTED))
                p.setFont(label_font)
                p.drawText(r.adjusted(8, 6, -8, -6), Qt.AlignLeft | Qt.AlignTop, label)
                continue
            if not (self.start <= d <= self.end):
                continue
            q = self.qty.get(d, 0)
            if q == 0:
                bg, fg = QColor("#ffffff"), QColor(theme.TEXT_MUTED)
            else:
                bg, fg = self._shade(q, peak)
            p.setPen(QPen(QColor(theme.BORDER_STRONG), 1) if q == 0 else Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            if d == self.selected:
                p.setPen(QPen(QColor(theme.TEXT), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), 10, 10)
                if self.hasFocus():
                    p.setPen(QPen(QColor(theme.AMBER), 2))
                    p.drawRoundedRect(r.adjusted(-6, -6, 6, 6), 12, 12)
            if d == self.today:
                pen = QPen(fg, 1.5, Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(4, 4, -4, -4), 6, 6)
            p.setPen(fg)
            p.setFont(label_font)
            text_r = r.adjusted(8, 6, -8, -6)
            # "today" is spelled out only when it fits beside a rank badge; the dashed
            # outline marks today either way.
            room = r.width() - 16 - (28 if d in self.ranks else 0)
            today_text = label + " today"
            if d == self.today and QFontMetrics(label_font).horizontalAdvance(today_text) <= room:
                label = today_text
            p.drawText(text_r, Qt.AlignLeft | Qt.AlignTop, label)
            p.setFont(qty_font)
            p.drawText(text_r, Qt.AlignLeft | Qt.AlignBottom, f"{q:,}")
            if d in self.ranks:
                badge = QRectF(r.right() - 28, r.top() + 6, 20, 20)
                p.setPen(QPen(QColor(theme.TEXT), 1.5))
                p.setBrush(QColor("#ffffff"))
                p.drawEllipse(badge)
                p.setPen(QColor(theme.TEXT))
                p.setFont(_font(self, 11, QFont.ExtraBold))
                p.drawText(badge, Qt.AlignCenter, str(self.ranks[d]))

    def mouseMoveEvent(self, event):
        d = self._day_at(event.position())
        self.setCursor(Qt.PointingHandCursor if d else Qt.ArrowCursor)
        if d:
            q = self.qty.get(d, 0)
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{d:%A} {d.day} {d:%B}: {q:,} units", self)

    def mousePressEvent(self, event):
        d = self._day_at(event.position())
        if d:
            self._select(d)

    def keyPressEvent(self, event):
        step = {Qt.Key_Left: -1, Qt.Key_Right: 1, Qt.Key_Up: -7, Qt.Key_Down: 7}.get(event.key())
        if step and self.selected:
            d = self.selected + timedelta(days=step)
            if self.start <= d <= self.end:
                self._select(d)
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event):
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.update()
        super().focusOutEvent(event)

    def _select(self, d: date):
        self.selected = d
        self.update()
        self.day_selected.emit(d)


# --------------------------------------------------------------------------
# Pace
# --------------------------------------------------------------------------

def nice_step(top: float) -> int:
    """A round grid step so that four steps cover `top`."""
    for step in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 50000):
        if step * 4 >= top:
            return step
    return 100000


class PaceChart(QWidget):
    """Cumulative units over the period (solid), against the comparison period (dashed)."""

    hovered = Signal(str)
    LEFT, RIGHT, TOP, BOTTOM = 56, 16, 34, 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cur: list[tuple[date, int]] = []
        self.prev: list[tuple[date, int]] = []
        self.domain = 2
        self.hover_i = 0
        self.setMouseTracking(True)
        self.setFixedHeight(280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, cur, prev, domain_days: int, cur_label: str, prev_label: str,
                 prev_name: str, running: bool):
        """prev_label is the legend text ("October"); prev_name is used mid-sentence."""
        self.cur, self.prev = list(cur), list(prev)
        self.cur_cum = self._cum(self.cur)
        self.prev_cum = self._cum(self.prev)
        self.domain = max(domain_days, len(self.prev), 2)
        self.cur_label, self.prev_label, self.prev_name = cur_label, prev_label, prev_name
        self.running = running
        self.step = nice_step(max(self.cur_cum[-1:] + self.prev_cum[-1:] + [1]))
        self.hover_i = 0
        self.update()

    @staticmethod
    def _cum(series):
        out, total = [], 0
        for _, q in series:
            total += q
            out.append(total)
        return out

    def _x(self, i: int) -> float:          # i: 1-based day of the period
        return self.LEFT + (i - 1) / (self.domain - 1) * (self.width() - self.LEFT - self.RIGHT)

    def _y(self, v: float) -> float:
        return self.TOP + (1 - v / (self.step * 4)) * (self.height() - self.TOP - self.BOTTOM)

    def paintEvent(self, event):
        if not self.cur:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        muted = QColor(theme.TEXT_MUTED)
        dashed = mix(theme.TEXT_MUTED, "#ffffff", 0.2)

        # Legend
        p.setFont(_font(self, 13))
        x = self.LEFT
        for label, colour, style in ((self.cur_label, QColor(theme.TEXT), Qt.SolidLine),
                                     (self.prev_label, dashed, Qt.DashLine)):
            if not label:
                continue
            p.setPen(QPen(colour, 2.5 if style == Qt.SolidLine else 2, style))
            p.drawLine(QPointF(x, 10), QPointF(x + 22, 10))
            p.setPen(QColor(theme.TEXT))
            p.drawText(QPointF(x + 28, 15), label)
            x += 40 + QFontMetrics(p.font()).horizontalAdvance(label)

        # Grid and axes
        p.setFont(_font(self, 12))
        for k in range(5):
            y = self._y(k * self.step)
            p.setPen(QPen(QColor(theme.RULE), 1))
            p.drawLine(QPointF(self.LEFT, y), QPointF(self.width() - self.RIGHT, y))
            p.setPen(muted)
            p.drawText(QRectF(0, y - 8, self.LEFT - 8, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"{k * self.step:,}")
        base = self._y(0)
        p.setPen(QPen(QColor(theme.TEXT), 1.5))
        p.drawLine(QPointF(self.LEFT, base), QPointF(self.width() - self.RIGHT, base))
        start = self.cur[0][0]
        p.setPen(muted)
        for k in range(5):
            i = round(1 + k * (self.domain - 1) / 4)
            d = start + timedelta(days=i - 1)
            p.drawText(QRectF(self._x(i) - 40, base + 6, 80, 16), Qt.AlignCenter,
                       f"{d.day} {calendar.month_abbr[d.month]}")

        def line(values, pen):
            path = QPainterPath()
            for i, v in enumerate(values, start=1):
                pt = QPointF(self._x(i), self._y(v))
                path.moveTo(pt) if i == 1 else path.lineTo(pt)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

        if self.prev_cum:
            line(self.prev_cum, QPen(dashed, 2, Qt.DashLine))
            p.setPen(muted)
            p.setFont(_font(self, 13))
            end_x = self._x(len(self.prev_cum))
            p.drawText(QRectF(end_x - 200, self._y(self.prev_cum[-1]) - 22, 200, 16),
                       Qt.AlignRight | Qt.AlignVCenter, f"{self.prev_cum[-1]:,}")
        line(self.cur_cum, QPen(QColor(theme.TEXT), 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        end = QPointF(self._x(len(self.cur_cum)), self._y(self.cur_cum[-1]))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(QColor(theme.TEXT))
        p.drawEllipse(end, 5, 5)
        p.setPen(QColor(theme.TEXT))
        p.setFont(_font(self, 13, QFont.Bold))
        text = f"{self.cur_cum[-1]:,}" + (" so far" if self.running else "")
        metrics = QFontMetrics(p.font())
        tx = min(end.x() + 10, self.width() - self.RIGHT - metrics.horizontalAdvance(text))
        label = QRectF(tx - 4, end.y() - 10 - metrics.ascent() - 2,
                       metrics.horizontalAdvance(text) + 8, metrics.height() + 4)
        p.fillRect(label, QColor(theme.SURFACE))       # keep the label readable over the lines
        p.drawText(QPointF(tx, end.y() - 10), text)

        if self.hover_i:
            x = self._x(self.hover_i)
            p.setPen(QPen(QColor(theme.TEXT), 1, Qt.DotLine))
            p.drawLine(QPointF(x, self.TOP), QPointF(x, base))
            for cum, colour in ((self.prev_cum, dashed), (self.cur_cum, QColor(theme.TEXT))):
                if self.hover_i <= len(cum):
                    p.setPen(QPen(QColor("#ffffff"), 2))
                    p.setBrush(colour)
                    p.drawEllipse(QPointF(x, self._y(cum[self.hover_i - 1])), 4.5, 4.5)

    def mouseMoveEvent(self, event):
        if not self.cur:
            return
        width = self.width() - self.LEFT - self.RIGHT
        i = round((event.position().x() - self.LEFT) / width * (self.domain - 1)) + 1
        i = max(1, min(self.domain, i))
        if i != self.hover_i:
            self.hover_i = i
            self.update()
            d = self.cur[0][0] + timedelta(days=i - 1)
            parts = [f"{d.day} {calendar.month_abbr[d.month]}: "]
            parts.append(f"{self.cur_label} {self.cur_cum[i - 1]:,} units" if i <= len(self.cur_cum)
                         else f"{self.cur_label} still to come")
            if i <= len(self.prev_cum):
                parts.append(f", {self.prev_name} {self.prev_cum[i - 1]:,} units")
            self.hovered.emit("".join(parts) + ".")

    def leaveEvent(self, event):
        self.hover_i = 0
        self.update()
        self.hovered.emit("")


# --------------------------------------------------------------------------
# Columns and bars
# --------------------------------------------------------------------------

class ColumnChart(QWidget):
    """
    One column per category. The tallest is highlighted with its value; hovering a
    column highlights it instead and emits its caption.
    """

    hovered = Signal(str)
    LABEL_H, VALUE_H = 22, 20

    def __init__(self, gap: int = 10, max_width: int = 44, parent=None):
        super().__init__(parent)
        self.gap, self.max_width = gap, max_width
        self.labels: list[str] = []
        self.values: list[float] = []
        self.captions: list[str] = []
        self.texts: list[str] = []
        self.hover = -1
        self.setMouseTracking(True)
        self.setFixedHeight(230)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, labels, values, texts, captions, empty: str = "No data"):
        self.labels, self.values, self.texts, self.captions = labels, values, texts, captions
        self.empty = empty
        self.hover = -1
        self.update()

    def _slot(self, i: int) -> QRectF:
        n = len(self.values)
        w = (self.width() - self.gap * (n - 1)) / n
        return QRectF(i * (w + self.gap), 0, w, self.height())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.values or not max(self.values):
            _empty(p, self, self.empty)
            return
        peak = max(self.values)
        top_i = self.values.index(peak)
        lit = self.hover if self.hover >= 0 else top_i
        base = self.height() - self.LABEL_H
        room = base - self.VALUE_H
        for i, v in enumerate(self.values):
            slot = self._slot(i)
            w = min(self.max_width, slot.width())
            x = slot.center().x() - w / 2
            h = max(3.0 if v else 0.0, room * v / peak)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.TEXT) if i == lit else soft())
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, base - h, w, h + 4), 4, 4)
            p.save()
            p.setClipRect(QRectF(x, 0, w, base))
            p.drawPath(path)
            p.restore()
            if i == lit:
                p.setPen(QColor(theme.TEXT))
                p.setFont(_font(self, 12, QFont.Bold))
                p.drawText(QRectF(slot.left() - 10, base - h - self.VALUE_H, slot.width() + 20,
                                  self.VALUE_H), Qt.AlignCenter, self.texts[i])
            p.setPen(QColor(theme.TEXT if i == top_i else theme.TEXT_MUTED))
            p.setFont(_font(self, 12, QFont.Bold if i == top_i else QFont.Normal))
            p.drawText(QRectF(slot.left() - 6, base + 4, slot.width() + 12, self.LABEL_H - 4),
                       Qt.AlignCenter, self.labels[i])
        p.fillRect(QRectF(0, base, self.width(), 1.5), QColor(theme.TEXT))

    def mouseMoveEvent(self, event):
        if not self.values:
            return
        i = next((k for k in range(len(self.values))
                  if self._slot(k).left() <= event.position().x() <= self._slot(k).right() + self.gap),
                 len(self.values) - 1)
        if i != self.hover:
            self.hover = i
            self.update()
            self.hovered.emit(self.captions[i])

    def leaveEvent(self, event):
        self.hover = -1
        self.update()
        self.hovered.emit("")


class BarList(QWidget):
    """
    Rows of: label, a horizontal bar, and a value. Each row: dict(label, value, text,
    colour (optional), caption). An optional marker draws a reference line on every track.
    """

    hovered = Signal(str)
    ROW_H = 34

    def __init__(self, label_share: float = 0.38, value_width: int = 64, parent=None):
        super().__init__(parent)
        self.label_share, self.value_width = label_share, value_width
        self.rows: list[dict] = []
        self.scale = 1.0
        self.marker: float | None = None
        self.hover = -1
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_rows(self, rows, scale: float | None = None, marker: float | None = None,
                 track: bool = False, empty: str = "No data"):
        self.rows, self.marker, self.track, self.empty = rows, marker, track, empty
        self.scale = scale or max((r["value"] for r in rows), default=1) or 1
        self.hover = -1
        self.setFixedHeight(max(1, len(rows)) * self.ROW_H)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.rows:
            _empty(p, self, self.empty)
            return
        w = self.width()
        label_w = w * self.label_share
        bar_x = label_w + 12
        bar_w = max(40.0, w - bar_x - self.value_width - 12)
        name_font = _font(self, 14, QFont.Medium)
        metrics = QFontMetrics(name_font)
        for i, row in enumerate(self.rows):
            top = i * self.ROW_H
            mid = top + self.ROW_H / 2
            if i == self.hover:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.BG))
                p.drawRoundedRect(QRectF(0, top + 1, w, self.ROW_H - 2), 6, 6)
            p.setPen(QColor(theme.TEXT))
            p.setFont(name_font)
            p.drawText(QRectF(6, top, label_w - 6, self.ROW_H), Qt.AlignLeft | Qt.AlignVCenter,
                       metrics.elidedText(row["label"], Qt.ElideRight, int(label_w - 6)))
            p.setPen(Qt.NoPen)
            if self.track:
                p.setBrush(QColor(theme.RULE))
                p.drawRoundedRect(QRectF(bar_x, mid - 7, bar_w, 14), 3, 3)
            p.setBrush(QColor(row.get("colour") or theme.TEXT))
            length = bar_w * min(row["value"], self.scale) / self.scale
            if length > 0:
                p.drawRoundedRect(QRectF(bar_x, mid - 7, max(length, 3), 14), 3, 3)
            if self.marker is not None:
                mx = bar_x + bar_w * self.marker
                p.fillRect(QRectF(mx - 1, mid - 11, 2, 22), QColor(theme.AMBER))
            p.setPen(QColor(theme.TEXT))
            p.setFont(_font(self, 14, QFont.ExtraBold))
            p.drawText(QRectF(w - self.value_width - 6, top, self.value_width, self.ROW_H),
                       Qt.AlignRight | Qt.AlignVCenter, row["text"])

    def mouseMoveEvent(self, event):
        i = int(event.position().y() // self.ROW_H)
        if 0 <= i < len(self.rows) and i != self.hover:
            self.hover = i
            self.update()
            self.hovered.emit(self.rows[i].get("caption", ""))

    def leaveEvent(self, event):
        self.hover = -1
        self.update()
        self.hovered.emit("")


class ShareBar(QWidget):
    """One 100% stacked bar plus a legend row for every part: swatch, name, share, detail."""

    hovered = Signal(str)
    BAR_H, ROW_H = 28, 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parts: list[dict] = []
        self.hover = -1
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_parts(self, parts, empty: str = "No data"):
        """parts: dict(label, value, colour, detail, caption)."""
        self.parts, self.empty = parts, empty
        self.hover = -1
        self.setFixedHeight(self.BAR_H + 14 + max(1, len(parts)) * self.ROW_H)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        total = sum(part["value"] for part in self.parts)
        if not total:
            _empty(p, self, self.empty)
            return
        w = self.width()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, self.BAR_H), 4, 4)
        p.save()
        p.setClipPath(clip)
        x = 0.0
        shown = [i for i, part in enumerate(self.parts) if part["value"]]
        for k, i in enumerate(shown):
            part = self.parts[i]
            width = w * part["value"] / total
            colour = QColor(part["colour"])
            if self.hover >= 0 and self.hover != i:
                colour.setAlphaF(0.35)
            gap = 2 if k < len(shown) - 1 else 0
            p.fillRect(QRectF(x, 0, max(width - gap, 1), self.BAR_H), colour)
            x += width
        p.restore()

        for i, part in enumerate(self.parts):
            top = self.BAR_H + 14 + i * self.ROW_H
            if i == self.hover:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.BG))
                p.drawRoundedRect(QRectF(0, top + 1, w, self.ROW_H - 2), 6, 6)
            p.fillRect(QRectF(0, top, w, 1), QColor(theme.RULE))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(part["colour"]))
            p.drawRoundedRect(QRectF(6, top + self.ROW_H / 2 - 6, 12, 12), 3, 3)
            share = f"{round(100 * part['value'] / total)}%"
            detail_font, share_font = _font(self, 13), _font(self, 14, QFont.ExtraBold)
            detail_w = QFontMetrics(detail_font).horizontalAdvance(part["detail"])
            share_w = QFontMetrics(share_font).horizontalAdvance(share)
            p.setPen(QColor(theme.TEXT_MUTED))
            p.setFont(detail_font)
            p.drawText(QRectF(w - detail_w - 6, top, detail_w, self.ROW_H),
                       Qt.AlignRight | Qt.AlignVCenter, part["detail"])
            p.setPen(QColor(theme.TEXT))
            p.setFont(share_font)
            p.drawText(QRectF(w - detail_w - share_w - 14, top, share_w, self.ROW_H),
                       Qt.AlignRight | Qt.AlignVCenter, share)
            name_font = _font(self, 14, QFont.Medium)
            room = int(w - detail_w - share_w - 50)
            p.setPen(QColor(theme.TEXT if part["colour"] != NEUTRAL else theme.TEXT_MUTED))
            p.setFont(name_font)
            p.drawText(QRectF(28, top, room, self.ROW_H), Qt.AlignLeft | Qt.AlignVCenter,
                       QFontMetrics(name_font).elidedText(part["label"], Qt.ElideRight, room))

    def _part_at(self, y: float) -> int:
        if y < self.BAR_H + 14:
            return -1
        i = int((y - self.BAR_H - 14) // self.ROW_H)
        return i if 0 <= i < len(self.parts) else -1

    def mouseMoveEvent(self, event):
        pos = event.position()
        i = self._part_at(pos.y())
        if pos.y() <= self.BAR_H:                      # over the bar itself
            total = sum(part["value"] for part in self.parts) or 1
            x = 0.0
            for k, part in enumerate(self.parts):
                x += self.width() * part["value"] / total
                if pos.x() <= x:
                    i = k
                    break
        if i != self.hover:
            self.hover = i
            self.update()
            self.hovered.emit(self.parts[i]["caption"] if i >= 0 else "")

    def leaveEvent(self, event):
        self.hover = -1
        self.update()
        self.hovered.emit("")


class ShareDelegate(QStyledItemDelegate):
    """Shows a percentage cell as a short bar (scaled to the largest share) and the number."""

    def __init__(self, largest: float = 100.0, parent=None):
        super().__init__(parent)
        self.largest = largest

    def paint(self, painter, option, index):
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        value = index.data(Qt.EditRole) or 0.0
        r = QRectF(option.rect).adjusted(10, 0, -10, 0)
        text_w = 52
        track = QRectF(r.left(), r.center().y() - 5, max(10.0, r.width() - text_w - 8), 10)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.RULE))
        painter.drawRoundedRect(track, 3, 3)
        painter.setBrush(QBrush(QColor(theme.TEXT) if index.row() < 3 else soft()))
        if self.largest:
            painter.drawRoundedRect(QRectF(track.left(), track.top(),
                                           max(2.0, track.width() * value / self.largest),
                                           track.height()), 3, 3)
        painter.setPen(QColor(theme.TEXT_MUTED))
        painter.drawText(QRectF(r.right() - text_w, r.top(), text_w, r.height()),
                         Qt.AlignRight | Qt.AlignVCenter, f"{value:.1f}%")
        painter.restore()
