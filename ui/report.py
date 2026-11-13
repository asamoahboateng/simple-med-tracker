"""
ui/report.py - Report for a month or any date range, with Excel and PDF export.

Month mode steps through calendar months and compares with the month before.
Date range mode takes any From/To dates (or a quick pick) and compares with the
same number of days just before. Every chart follows the chosen period.
"""

import calendar
from datetime import date, timedelta

from PySide6.QtCore import QBuffer, QByteArray, QDate, QIODevice, QMarginsF, QSizeF, Qt, QUrl
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

import db
import exports
import logic
from config import APP_NAME, EXPIRY_WARNING_DAYS
from ui import theme
from ui.dashboard_widgets import DividedPanel, Panel
from ui.models import Column, RecordTableModel, TableProxy, int_fmt, make_table, use_pills
from ui.report_widgets import (
    NEUTRAL, SERIES, BarList, ColumnChart, DayCalendar, FigureCell, PaceChart, ShareBar,
    ShareDelegate,
)
from ui.responsive import FlowGrid
from ui.widgets import (
    make_button, make_date_edit, page_header, page_layout, scrolling_page, show_error, show_info,
    to_py_date, to_qdate,
)

RANK_COLUMNS = [
    Column("rank", "Rank", "right"),
    Column("medicine", "Medicine"),
    Column("dispensed", "Dispensed", "right", int_fmt),
    Column("percent", "Share"),
    Column("received", "Received", "right", lambda v: f"{v:,}" if v else "None"),
    Column("stock", "Stock now", "right", int_fmt),
    Column("status", "Status", "center"),
]
PRESETS = [(7, "Last 7 days"), (30, "Last 30 days"), (90, "Last 90 days")]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
FIRST_HOUR, LAST_HOUR = 7, 18          # the time-of-day chart covers 07:00 to 18:59
TABLE_LIMIT = 100                      # rows in the ranked table; exports include every medicine


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def _short(d: date) -> str:
    return f"{d.day} {calendar.month_abbr[d.month]}"


def _long(d: date) -> str:
    return f"{d:%A} {d.day} {d:%B}"


class ChartPanel(Panel):
    """A panel with a title, a one-line description, the chart and a caption that shows
    the hover readout (or the default summary when nothing is hovered)."""

    def __init__(self, title: str, description: str, chart, parent=None):
        super().__init__(title, description, parent)
        self.chart = chart
        self.body.addWidget(chart)
        self.caption = QLabel()
        self.caption.setObjectName("caption")
        self.caption.setWordWrap(True)
        self.caption.setMinimumHeight(22)
        self.body.addWidget(self.caption)
        self.body.addStretch()
        self.default_caption = ""
        if hasattr(chart, "hovered"):
            chart.hovered.connect(lambda text: self.caption.setText(text or self.default_caption))

    def set_caption(self, text: str) -> None:
        self.default_caption = text
        self.caption.setText(text)


class ReportPage(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.report: logic.PeriodReport | None = None
        today = date.today()
        self.month = date(today.year, today.month, 1)
        self.range_from, self.range_to = today - timedelta(days=29), today
        self.selected_day: date | None = None

        # --- period controls ---
        segment = QFrame()
        segment.setObjectName("segmentBox")
        seg = QHBoxLayout(segment)
        seg.setContentsMargins(3, 3, 3, 3)
        seg.setSpacing(2)
        self.month_btn = QPushButton("Month")
        self.range_btn = QPushButton("Date range")
        self.mode_group = QButtonGroup(self)
        for button in (self.month_btn, self.range_btn):
            button.setProperty("kind", "segment")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            self.mode_group.addButton(button)
            seg.addWidget(button)
        self.month_btn.setChecked(True)
        self.mode_group.buttonClicked.connect(lambda _b: self.refresh())

        self.stepper = QFrame()
        self.stepper.setObjectName("segmentBox")
        step = QHBoxLayout(self.stepper)
        step.setContentsMargins(2, 2, 2, 2)
        self.prev_btn = QPushButton("‹")
        self.next_btn = QPushButton("›")
        self.month_label = QLabel()
        self.month_label.setAlignment(Qt.AlignCenter)
        self.month_label.setMinimumWidth(150)
        self.month_label.setStyleSheet("font-weight: 800; font-size: 15px; background: transparent;")
        for button, delta, name in ((self.prev_btn, -1, "Previous month"),
                                    (self.next_btn, 1, "Next month")):
            button.setProperty("kind", "stepper")
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName(name)
            button.setToolTip(name)
            button.clicked.connect(lambda _c=False, d=delta: self.step_month(d))
        step.addWidget(self.prev_btn)
        step.addWidget(self.month_label)
        step.addWidget(self.next_btn)

        excel_btn = make_button("Export Excel", "outline")
        pdf_btn = make_button("Export PDF", "primary")
        excel_btn.clicked.connect(self.export_excel)
        pdf_btn.clicked.connect(self.export_pdf)
        self.header = page_header("Report", "", segment, self.stepper, excel_btn, pdf_btn)

        # --- date range bar ---
        self.range_bar = QFrame()
        self.range_bar.setObjectName("panel")
        bar = QVBoxLayout(self.range_bar)
        bar.setContentsMargins(20, 14, 20, 14)
        bar.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.from_edit = make_date_edit(self.range_from, max_today=True)
        self.to_edit = make_date_edit(self.range_to, max_today=True)
        for label, edit in (("From", self.from_edit), ("To", self.to_edit)):
            text = QLabel(label)
            text.setObjectName("statLabel")
            row.addWidget(text)
            row.addWidget(edit)
            edit.dateChanged.connect(self._dates_edited)
        row.addSpacing(8)
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(False)
        self.preset_buttons = {}
        for days, label in PRESETS:
            button = QPushButton(label)
            button.setProperty("kind", "chip")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _c=False, n=days: self.apply_preset(n))
            self.preset_buttons[days] = button
            row.addWidget(button)
        row.addStretch()
        self.first_record = QLabel()
        self.first_record.setObjectName("muted")
        row.addWidget(self.first_record)
        bar.addLayout(row)
        self.range_error = QLabel()
        self.range_error.setObjectName("errorText")
        self.range_error.setWordWrap(True)
        self.range_error.setVisible(False)
        bar.addWidget(self.range_error)

        # --- figures ---
        self.fig_dispensed = FigureCell("Dispensed")
        self.fig_per_day = FigureCell("Per day")
        self.fig_entries = FigureCell("Dispensing entries")
        self.fig_medicines = FigureCell("Medicines dispensed")
        self.fig_received = FigureCell("Stock received")
        figures = DividedPanel([self.fig_dispensed, self.fig_per_day, self.fig_entries,
                                self.fig_medicines, self.fig_received],
                               min_item_width=190, max_columns=5)

        # --- calendar, busiest days, prescriber share ---
        self.calendar = DayCalendar()
        self.calendar.day_selected.connect(self._day_selected)
        self.calendar_panel = Panel("Day by day")
        self.calendar_panel.body.addWidget(self.calendar)
        self.day_line = QLabel()
        self.day_line.setObjectName("caption")
        self.day_line.setWordWrap(True)
        self.calendar_panel.body.addWidget(self.day_line)
        self.calendar_panel.body.addStretch()

        self.busiest = BarList(label_share=0.5, value_width=80)
        busiest_panel = Panel("Busiest days")
        busiest_panel.body.addWidget(self.busiest)
        busiest_panel.body.addStretch()
        self.share = ShareBar()
        self.share_panel = ChartPanel("Prescriber share", "", self.share)
        side = QWidget()
        side_col = QVBoxLayout(side)
        side_col.setContentsMargins(0, 0, 0, 0)
        side_col.setSpacing(24)
        side_col.addWidget(busiest_panel)
        side_col.addWidget(self.share_panel)
        side_col.addStretch()
        middle = FlowGrid([self.calendar_panel, side], min_item_width=380, max_columns=2,
                          spacing=24, stretches=(7, 4))

        # --- charts ---
        self.top = ChartPanel("Top 10 medicines", "", BarList(label_share=0.42, value_width=60))
        self.pace = ChartPanel("Pace", "", PaceChart())
        self.weekdays = ChartPanel("By day of the week",
                                   "Average units per day. Today is left out until it ends.",
                                   ColumnChart(gap=10, max_width=44))
        self.hours = ChartPanel("Time of day", "Dispensing entries by the hour they were recorded",
                                ColumnChart(gap=4, max_width=40))
        self.cover = ChartPanel(
            "Days of stock left",
            f"How long current stock lasts at this period's rate. Shortest first. The amber "
            f"line marks {EXPIRY_WARNING_DAYS} days.",
            BarList(label_share=0.32, value_width=96))
        row1 = FlowGrid([self.top, self.pace], min_item_width=420, max_columns=2, spacing=24)
        row2 = FlowGrid([self.weekdays, self.hours], min_item_width=420, max_columns=2, spacing=24)

        # --- ranked table ---
        self.rank_model = RecordTableModel(RANK_COLUMNS)
        self.rank_view = make_table(self.rank_model, TableProxy())
        use_pills(self.rank_view, RANK_COLUMNS, "status")
        self.share_delegate = ShareDelegate(parent=self.rank_view)
        self.rank_view.setItemDelegateForColumn(3, self.share_delegate)
        self.rank_panel = Panel("Medicines dispensed")
        self.rank_note = QLabel()
        self.rank_note.setObjectName("muted")
        self.rank_note.setWordWrap(True)
        self.rank_panel.body.addWidget(self.rank_note)
        self.rank_panel.body.addWidget(self.rank_view)

        content = QWidget()
        layout = page_layout(content)
        layout.setSpacing(20)
        layout.addWidget(self.header)
        layout.addWidget(self.range_bar)
        layout.addWidget(figures)
        layout.addWidget(middle)
        layout.addWidget(row1)
        layout.addWidget(row2)
        layout.addWidget(self.cover)
        layout.addWidget(self.rank_panel)
        layout.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolling_page(content))

    # --- period selection ---------------------------------------------------------
    @property
    def is_month(self) -> bool:
        return self.month_btn.isChecked()

    def step_month(self, delta: int) -> None:
        y, m = divmod(self.month.month - 1 + delta, 12)
        candidate = date(self.month.year + y, m + 1, 1)
        if self._first_month() <= candidate <= date.today().replace(day=1):
            self.month = candidate
            self.selected_day = None
            self.refresh()

    def apply_preset(self, days: int) -> None:
        today = date.today()
        self._set_range(max(today - timedelta(days=days - 1), self._first_date()), today)
        self.refresh()

    def _set_range(self, start: date, end: date) -> None:
        for edit, d in ((self.from_edit, start), (self.to_edit, end)):
            edit.blockSignals(True)
            edit.setDate(to_qdate(d))
            edit.blockSignals(False)
        self.range_from, self.range_to = start, end
        self.selected_day = None

    def _dates_edited(self, *_):
        start, end = to_py_date(self.from_edit.date()), to_py_date(self.to_edit.date())
        if start > end:
            self.range_error.setText("The start date is after the end date. "
                                     "Choose an earlier start date.")
            self.range_error.setVisible(True)
            return
        self.range_error.setVisible(False)
        self.range_from, self.range_to = start, end
        self.selected_day = None
        self.refresh()

    def _first_date(self) -> date:
        first = db.first_transaction_date(self.conn)
        return logic.to_date(first) if first else date.today()

    def _first_month(self) -> date:
        return self._first_date().replace(day=1)

    def _day_selected(self, d: date) -> None:
        self.selected_day = d
        self._update_day_line()

    # --- refresh ---------------------------------------------------------------------
    def refresh(self, *_):
        today = date.today()
        first = self._first_date()
        self.stepper.setVisible(self.is_month)
        self.range_bar.setVisible(not self.is_month)
        for edit in (self.from_edit, self.to_edit):
            edit.setMinimumDate(QDate(first.year, first.month, first.day))
        self.first_record.setText(f"Records start {first.day} {first:%B %Y}")

        if self.is_month:
            self.month = max(min(self.month, today.replace(day=1)), first.replace(day=1))
            last = date(self.month.year, self.month.month,
                        calendar.monthrange(self.month.year, self.month.month)[1])
            r = logic.period_report(self.conn, self.month, last, today, is_month=True)
            self.month_label.setText(r.title)
            self.prev_btn.setEnabled(self.month > first.replace(day=1))
            self.next_btn.setEnabled(self.month < today.replace(day=1))
        else:
            if self.range_from < first:
                self._set_range(first, max(self.range_to, first))
            r = logic.period_report(self.conn, self.range_from, self.range_to, today)
            for days, button in self.preset_buttons.items():
                button.setChecked(self.range_to == today and
                                  self.range_from == max(today - timedelta(days=days - 1), first))
        self.report = r
        running = r.end == today
        if r.is_month:
            noun = "this month" if running and r.calendar_end > r.end else f"in {r.start:%B}"
            line = (f"Dispensing from 1 to {r.end.day} {r.end:%B %Y}. The month is still in progress."
                    if r.calendar_end > r.end else f"Dispensing for the whole of {r.title}.")
        else:
            noun = "in this period"
            line = (f"Dispensing on {r.start.day} {r.start:%B %Y}." if r.start == r.end else
                    f"Dispensing from {r.title}, {r.days_counted} days.")
        self.noun = noun
        self.header.subtitle_label.setText(line)

        self._update_figures(r)
        if self.selected_day is None or not (r.start <= self.selected_day <= r.end):
            self.selected_day = r.top_days[0][0] if r.top_days else r.end
        self.calendar.set_period(r.daily, r.start, r.end, r.calendar_end, today, self.selected_day)
        self._update_day_line()
        self._update_busiest(r)
        self._update_share(r)
        self._update_top(r)
        self._update_pace(r, running)
        self._update_weekdays(r)
        self._update_hours(r)
        self._update_cover(r)
        self._update_table(r)

    def _update_figures(self, r: logic.PeriodReport) -> None:
        self.fig_dispensed.set_value(f"{r.total_dispensed:,}",
                                     f"units in {_plural(r.days_counted, 'day')}")
        if r.change_vs_prev is None:
            note = "No earlier records to compare with"
        elif r.change_vs_prev == 0:
            note = f"Level with {r.prev_title} ({r.prev_avg_per_day})"
        else:
            word = "Up" if r.change_vs_prev > 0 else "Down"
            note = f"{word} {abs(r.change_vs_prev)}% on {r.prev_title} ({r.prev_avg_per_day})"
        self.fig_per_day.set_value(f"{r.avg_per_day:.1f}", note, strong_note=True)
        self.fig_entries.set_value(
            f"{r.entry_count:,}",
            f"about {round(r.total_dispensed / r.entry_count)} units each" if r.entry_count
            else "none recorded")
        catalogue = len(db.list_medicines(self.conn))
        self.fig_medicines.set_value(f"{r.medicines_dispensed:,}", f"of {catalogue:,} in the catalogue")
        self.fig_received.set_value(
            f"{r.total_received:,}",
            f"units in {_plural(r.deliveries, 'delivery', 'deliveries')}" if r.deliveries
            else "nothing received")

    def _update_day_line(self) -> None:
        r, d = self.report, self.selected_day
        if not r.total_dispensed:
            self.day_line.setText(f"Nothing was dispensed {self.noun}.")
            return
        q = dict(r.daily).get(d, 0)
        if not q:
            self.day_line.setText(f"{_long(d)}: nothing dispensed.")
            return
        diff = round(100 * (q - r.avg_per_day) / r.avg_per_day)
        rank = next((i + 1 for i, (day, _q) in enumerate(r.top_days) if day == d), None)
        self.day_line.setText(
            f"{_long(d)}: {q:,} units, {abs(diff)}% {'above' if diff >= 0 else 'below'} the daily "
            f"average of {r.avg_per_day:.1f}." + (f" Busiest day number {rank}." if rank else ""))

    def _update_busiest(self, r: logic.PeriodReport) -> None:
        self.busiest.set_rows(
            [{"label": _long(d), "value": q, "text": f"{q:,} units"} for d, q in r.top_days],
            empty=f"Nothing dispensed {self.noun}.")

    def _update_share(self, r: logic.PeriodReport) -> None:
        parts, slot = [], 0
        for p in r.prescribers:
            none = p["prescriber"] == "(not recorded)"
            colour = NEUTRAL if none or slot >= len(SERIES) else SERIES[slot]
            if not none and slot < len(SERIES):
                slot += 1
            name = "No prescriber recorded" if none else p["prescriber"]
            parts.append({
                "label": name, "value": p["qty"], "colour": colour,
                "detail": f"{p['qty']:,} units in {_plural(p['entries'], 'entry', 'entries')}",
                "caption": f"{name}: {p['qty']:,} units in {_plural(p['entries'], 'entry', 'entries')}.",
            })
        # More prescribers than colours: the rest share the neutral colour as "Others".
        named = [x for x in parts if x["colour"] != NEUTRAL]
        others = [x for x in parts if x["colour"] == NEUTRAL and x["label"] != "No prescriber recorded"]
        if others:
            qty = sum(x["value"] for x in others)
            named.append({"label": f"Others ({len(others)})", "value": qty, "colour": NEUTRAL,
                          "detail": f"{qty:,} units",
                          "caption": "Others: " + ", ".join(x["label"] for x in others) + "."})
        named += [x for x in parts if x["label"] == "No prescriber recorded"]
        self.share.set_parts(named, empty=f"Nothing dispensed {self.noun}.")

    def _update_top(self, r: logic.PeriodReport) -> None:
        top = [m for m in r.medicines if m["dispensed"] > 0][:10]
        self.top.chart.set_rows([{
            "label": m["medicine"], "value": m["dispensed"], "text": f"{m['dispensed']:,}",
            "caption": f"{m['medicine']}: {m['dispensed']:,} units, {m['percent']:.1f}% of the "
                       f"period. {m['stock']:,} left in stock.",
        } for m in top], empty=f"Nothing dispensed {self.noun}.")
        share = sum(m["dispensed"] for m in top)
        self.top.set_caption(
            f"These {len(top)} make up {round(100 * share / r.total_dispensed)}% of everything "
            f"dispensed {self.noun}." if top else "")

    def _update_pace(self, r: logic.PeriodReport, running: bool) -> None:
        self.pace.title_label.setText("Pace this month" if r.is_month else "Pace over the period")
        if r.is_month:
            cur_label = f"{r.start:%B}"
            prev_label = prev_name = r.prev_title
        else:
            cur_label = "This period"
            prev_label = r.prev_title[:1].upper() + r.prev_title[1:] if r.prev_title else ""
            prev_name = r.prev_title
        domain = (r.calendar_end - r.start).days + 1
        self.pace.chart.set_data(r.daily, r.prev_daily, domain, cur_label, prev_label, prev_name,
                                 running and r.calendar_end > r.end)
        total = r.total_dispensed
        if r.prev_daily:
            n = min(r.days_counted, len(r.prev_daily))
            prev_same = sum(q for _, q in r.prev_daily[:n])
            if prev_same:
                pct = round(100 * (total - prev_same) / prev_same)
                text = (f"After {_plural(r.days_counted, 'day')}, {total:,} units against "
                        f"{prev_same:,} at the same point in {prev_name}, {abs(pct)}% "
                        f"{'ahead' if pct >= 0 else 'behind'}.")
            else:
                text = f"{total:,} units. Nothing was dispensed at the same point in {prev_name}."
        else:
            text = f"{total:,} units over {_plural(r.days_counted, 'day')}. There are no earlier records to compare with."
        self.pace.set_caption(text)

    def _update_weekdays(self, r: logic.PeriodReport) -> None:
        avgs = r.weekday_avg
        captions = [f"{WEEKDAYS[i]}: {round(avgs[i]):,} units on average over "
                    f"{_plural(r.weekday_days[i], 'day')}." if r.weekday_days[i]
                    else f"{WEEKDAYS[i]}: no finished {WEEKDAYS[i]}s in this period."
                    for i in range(7)]
        self.weekdays.chart.set_data([w[:3] for w in WEEKDAYS], avgs,
                                     [f"{round(v):,}" for v in avgs], captions,
                                     empty="Not enough finished days yet.")
        peak = max(avgs)
        if peak:
            text = f"{WEEKDAYS[avgs.index(peak)]}s are busiest, averaging {round(peak):,} units."
            if r.weekday_days[6] and not avgs[6]:
                text += " Sundays have no dispensing."
        else:
            text = ""
        self.weekdays.set_caption(text)

    def _update_hours(self, r: logic.PeriodReport) -> None:
        hours = list(range(FIRST_HOUR, LAST_HOUR + 1))
        counts = [r.hourly.get(h, 0) for h in hours]
        outside = sum(n for h, n in r.hourly.items() if h < FIRST_HOUR or h > LAST_HOUR)
        captions = [f"{h:02d}:00 to {h + 1:02d}:00: {_plural(n, 'entry', 'entries')}."
                    for h, n in zip(hours, counts)]
        self.hours.chart.set_data([str(h) for h in hours], counts, [str(n) for n in counts],
                                  captions, empty=f"No entries recorded {self.noun}.")
        if any(counts):
            h = hours[counts.index(max(counts))]
            text = f"Busiest between {h:02d}:00 and {h + 1:02d}:00, with {_plural(max(counts), 'entry', 'entries')}."
            if outside:
                text += f" {_plural(outside, 'entry', 'entries')} fell outside these hours."
        else:
            text = ""
        self.hours.set_caption(text)

    def _update_cover(self, r: logic.PeriodReport) -> None:
        cap, warn = logic.COVER_CAP_DAYS, EXPIRY_WARNING_DAYS
        rows = []
        for c in r.stock_cover[:10]:
            days = round(c["days"])
            colour = theme.RED if days < 30 else theme.AMBER if days < warn else theme.GREEN
            rows.append({
                "label": c["medicine"], "value": min(days, cap), "colour": colour,
                "text": "Over a year" if days > cap else _plural(days, "day"),
                "caption": f"{c['medicine']}: {c['stock']:,} in stock, dispensing about "
                           f"{c['per_day']:.1f} a day, so roughly {_plural(days, 'day')} left.",
            })
        self.cover.chart.set_rows(rows, scale=cap, marker=warn / cap, track=True,
                                  empty="Nothing was dispensed, so there is no rate to measure.")
        short = sum(1 for c in r.stock_cover if c["days"] < warn)
        if not r.stock_cover:
            text = ""
        elif short:
            text = (f"{_plural(short, 'medicine')} {'has' if short == 1 else 'have'} less than "
                    f"{warn} days of stock at this rate.")
        else:
            first = r.stock_cover[0]
            text = (f"Every medicine dispensed {self.noun} has more than {warn} days of stock. "
                    f"The shortest is {first['medicine']} at {_plural(round(first['days']), 'day')}.")
        self.cover.set_caption(text)

    def _update_table(self, r: logic.PeriodReport) -> None:
        self.rank_model.set_rows(r.medicines[:TABLE_LIMIT])
        self.share_delegate.largest = max((m["percent"] for m in r.medicines), default=0) or 100
        self.rank_view.sortByColumn(0, Qt.AscendingOrder)
        self.rank_view.setColumnWidth(3, 220)       # room for the share bar
        rows = min(len(r.medicines), TABLE_LIMIT)
        self.rank_view.setFixedHeight(44 + max(rows, 1) * 36 + 4)
        note = (f"Ranked by units dispensed {self.noun}. Share is each medicine's part of the "
                f"{r.total_dispensed:,} units. Medicines that were only received are listed last.")
        if len(r.medicines) > TABLE_LIMIT:
            note += (f" Showing the top {TABLE_LIMIT} of {len(r.medicines):,}; the Excel and PDF "
                     f"exports include all of them.")
        self.rank_note.setText(note)

    # --- exports ---------------------------------------------------------------------
    def _ask_path(self, extension: str, description: str) -> str | None:
        suggested = f"medtracker_report_{self.report.file_stem}.{extension}"
        path, _ = QFileDialog.getSaveFileName(self, "Export report", suggested,
                                              f"{description} (*.{extension})")
        if not path:
            return None
        return path if path.lower().endswith(f".{extension}") else f"{path}.{extension}"

    def export_excel(self):
        path = self._ask_path("xlsx", "Excel workbook")
        if not path:
            return
        try:
            saved = exports.export_report_excel(self.report, path)
        except PermissionError:
            show_error(self, "Could not save the file. Is it open in Excel? Close it and try again.")
            return
        show_info(self, f"Report saved to:\n{saved}", title="Export complete")

    def export_pdf(self):
        path = self._ask_path("pdf", "PDF document")
        if not path:
            return
        # The Top 10 chart goes into the PDF as an image of the on-screen chart.
        image = self.top.chart.grab().toImage()
        buffer = QBuffer(QByteArray())
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        document = QTextDocument()
        document.addResource(QTextDocument.ImageResource, QUrl("chart.png"),
                             QImage.fromData(buffer.data()))
        document.setHtml(exports.report_html(self.report, APP_NAME, chart_src="chart.png"))

        writer = QPdfWriter(path)
        writer.setTitle(f"{APP_NAME} report {self.report.title}")
        writer.setPageSize(QPageSize(QPageSize.A4))
        writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
        writer.setResolution(96)  # lay the document out at screen resolution
        document.setPageSize(QSizeF(writer.width(), writer.height()))  # use the full page width
        document.print_(writer)
        del writer  # finishes writing the file
        show_info(self, f"PDF saved to:\n{path}", title="Export complete")
