"""
ui/dashboard.py - The start page, ordered by urgency: summary figures, what needs
attention, the expiry shelf, stock levels, then this month's dispensing.
"""

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

import logic
from config import EXPIRY_WARNING_DAYS
from ui import theme
from ui.dashboard_widgets import (
    AttentionGroup, ColumnList, DailyBars, DividedPanel, ExpiryShelf, HealthBars, LevelBars, Panel,
    StatCell, TopList,
)
from ui.responsive import FlowGrid
from ui.widgets import make_button, page_header, page_layout, scrolling_page


def _section(title: str, description: str = "") -> QWidget:
    box = QWidget()
    col = QVBoxLayout(box)
    col.setContentsMargins(0, 8, 0, 0)
    col.setSpacing(4)
    heading = QLabel(title)
    heading.setObjectName("sectionHeading")
    col.addWidget(heading)
    if description:
        text = QLabel(description)
        text.setObjectName("muted")
        text.setWordWrap(True)
        col.addWidget(text)
    return box


def _empty_state(text: str, button_text: str, slot) -> QWidget:
    box = QWidget()
    col = QVBoxLayout(box)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(14)
    label = QLabel(text)
    label.setWordWrap(True)
    button = make_button(button_text, "outline")
    button.setCursor(Qt.PointingHandCursor)
    button.clicked.connect(slot)
    col.addWidget(label)
    col.addWidget(button, 0, Qt.AlignLeft)
    return box


class DashboardPage(QWidget):
    add_stock_requested = Signal()
    dispense_requested = Signal()
    reorder_levels_requested = Signal()

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn

        # --- header with the two main actions ---
        add_btn = make_button("Add stock", "primary", large=True)
        give_btn = make_button("Record dispensed", "outline", large=True)
        add_btn.clicked.connect(self.add_stock_requested.emit)
        give_btn.clicked.connect(self.dispense_requested.emit)
        self.header = page_header("", "", add_btn, give_btn)

        # --- summary figures ---
        self.stat_dispensed = StatCell("Dispensed this month", "tablet", theme.TEXT,
                                       theme.BADGE_BG)
        self.stat_medicines = StatCell("Medicines", "bottle", theme.TEXT, theme.BADGE_BG)
        self.stat_low = StatCell("Low or out of stock", "trend_down", theme.RED, theme.RED_TINT)
        self.stat_expiry = StatCell("Expired or expiring soon", "hourglass", theme.AMBER_TEXT,
                                    theme.AMBER_TINT)
        stats = DividedPanel([self.stat_dispensed, self.stat_medicines, self.stat_low,
                              self.stat_expiry], min_item_width=220, max_columns=4)

        # --- needs attention ---
        self.out_group = AttentionGroup(
            "Out of stock", "Nothing left to dispense. Reorder or remove from the catalogue.",
            theme.RED, theme.RED)
        self.soon_group = AttentionGroup(
            f"Expiring within {EXPIRY_WARNING_DAYS} days",
            "Dispense these first, or arrange a return with the supplier.",
            theme.AMBER, theme.AMBER_TEXT)
        self.expired_group = AttentionGroup(
            "Expired", "Take these off the shelf. They can't be dispensed.",
            theme.RED, theme.RED, diamond=True)
        attention = DividedPanel([self.out_group, self.soon_group, self.expired_group],
                                 min_item_width=300, max_columns=3)

        # --- expiry shelf ---
        self.shelf = ExpiryShelf()
        self.shelf.selected_changed.connect(self._show_bucket)
        self.bucket_panel = Panel("")
        self.bucket_title = self.bucket_panel.title_label
        self.bucket_title.setObjectName("groupHeading")
        self.bucket_count = QLabel()
        self.bucket_count.setObjectName("muted")
        self.bucket_panel.header.addWidget(self.bucket_count)
        self.bucket_list = ColumnList(min_column_width=300, max_columns=3)
        self.bucket_empty = QLabel("No batches expire in this month.")
        self.bucket_empty.setObjectName("muted")
        self.bucket_panel.body.addWidget(self.bucket_list)
        self.bucket_panel.body.addWidget(self.bucket_empty)

        # --- running low + stock health ---
        self.low_panel = Panel("Running low")
        self.low_hint = QLabel("In stock, but closest to the level where you reorder. "
                               "The line marks the reorder level.")
        self.low_hint.setObjectName("muted")
        self.low_hint.setWordWrap(True)
        self.low_bars = LevelBars()
        self.low_none = QLabel("Nothing is close to its reorder level.")
        self.low_none.setObjectName("muted")
        self.low_unset = _empty_state(
            "Reorder levels aren't set yet, so nothing can count as running low. Set one for "
            "each medicine on Stock & Batches and the ones getting close will show here.",
            "Set reorder levels", self.reorder_levels_requested.emit)
        for widget in (self.low_hint, self.low_bars, self.low_none, self.low_unset):
            self.low_panel.body.addWidget(widget)
        self.low_panel.body.addStretch()

        self.health_panel = Panel("Stock health")
        self.health = HealthBars()
        self.health_panel.body.addWidget(self.health)
        self.health_panel.body.addStretch()
        levels = FlowGrid([self.low_panel, self.health_panel], min_item_width=380, max_columns=2,
                          spacing=24, stretches=(8, 5))

        # --- dispensing this month ---
        self.disp_panel = Panel("Dispensing")
        self.disp_heading = self.disp_panel.title_label
        self.top_list = TopList()
        self.daily = DailyBars()
        top_box, daily_box = QWidget(), QWidget()
        for box, title, chart in ((top_box, "Most dispensed", self.top_list),
                                  (daily_box, "Each day", self.daily)):
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(8)
            heading = QLabel(title)
            heading.setObjectName("statLabel")
            col.addWidget(heading)
            col.addWidget(chart)
            col.addStretch()
        self.disp_charts = FlowGrid([top_box, daily_box], min_item_width=340, max_columns=2,
                                    spacing=40, stretches=(5, 6))
        self.disp_empty = _empty_state(
            "Nothing dispensed yet this month. Each dispensing you record adds to this.",
            "Record dispensed", self.dispense_requested.emit)
        self.disp_panel.body.addWidget(self.disp_charts)
        self.disp_panel.body.addWidget(self.disp_empty)

        content = QWidget()
        layout = page_layout(content)
        layout.setSpacing(18)
        layout.addWidget(self.header)
        layout.addWidget(stats)
        layout.addWidget(_section("Needs attention"))
        layout.addWidget(attention)
        layout.addWidget(_section(
            "Expiry shelf", "Every block is one batch in stock, shelved by the month it expires. "
                            "Select a month to see what is on it."))
        layout.addWidget(self.shelf)
        layout.addWidget(self.bucket_panel)
        layout.addSpacing(8)
        layout.addWidget(levels)
        layout.addWidget(self.disp_panel)
        layout.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolling_page(content))

    def refresh(self):
        today = date.today()
        data = logic.dashboard_data(self.conn, today)
        batches_in_stock = sum(data.batch_health.values())

        self.header.title_label.setText(f"{today:%A} {today.day} {today:%B %Y}")
        self.header.subtitle_label.setText(
            f"{data.medicine_count:,} medicines and {batches_in_stock:,} batches in stock")

        # Summary figures
        expired = [b for b in data.expiry_alerts if b["status"] == logic.BATCH_EXPIRED]
        expiring = [b for b in data.expiry_alerts if b["status"] == logic.BATCH_EXPIRING]
        self.stat_dispensed.set_value(data.dispensed_this_month, f"{today:%B %Y}")
        self.stat_medicines.set_value(data.medicine_count, "in your catalogue")
        self.stat_low.set_value(data.low_or_out_count, "at or below reorder level",
                                theme.RED if data.low_or_out_count else theme.TEXT)
        self.stat_expiry.set_value(
            data.expiry_alert_count,
            f"batches, {len(expired)} expired and {len(expiring)} within "
            f"{EXPIRY_WARNING_DAYS} days",
            theme.AMBER_TEXT if data.expiry_alert_count else theme.TEXT)

        # Needs attention
        out = [m for m in data.stock_alerts if m["stock"] <= 0]
        self.out_group.set_rows([(m["name"], "None left") for m in out], theme.TEXT_MUTED,
                                bold_detail=False)
        self.soon_group.set_rows(
            [(b["medicine"], f"in {b['days_to_expiry']} days") for b in expiring], theme.AMBER_TEXT)
        self.expired_group.set_rows(
            [(b["medicine"], f"{-b['days_to_expiry']} days ago") for b in reversed(expired)],
            theme.RED)

        # Expiry shelf
        self.buckets = data.expiry_timeline
        self.shelf.set_buckets(self.buckets)
        self._show_bucket(self.shelf.selected)

        # Running low + stock health
        has_levels = data.reorder_levels_set > 0
        self.low_unset.setVisible(not has_levels)
        self.low_hint.setVisible(has_levels and bool(data.running_low))
        self.low_bars.setVisible(has_levels and bool(data.running_low))
        self.low_none.setVisible(has_levels and not data.running_low)
        self.low_bars.set_rows(data.running_low)
        mh, bh = data.medicine_health, data.batch_health
        self.health.set_groups([
            ("Medicines", [("OK", mh[logic.STATUS_OK], theme.GREEN),
                           ("Low", mh[logic.STATUS_LOW], theme.AMBER),
                           ("Out", mh[logic.STATUS_OUT], theme.RED)]),
            ("Batches in stock", [("OK", bh[logic.BATCH_OK], theme.GREEN),
                                  ("Expiring", bh[logic.BATCH_EXPIRING], theme.AMBER),
                                  ("Expired", bh[logic.BATCH_EXPIRED], theme.RED)]),
        ])

        # Dispensing this month
        self.disp_heading.setText(f"Dispensing in {today:%B}")
        dispensed = data.dispensed_this_month > 0
        self.disp_charts.setVisible(dispensed)
        self.disp_empty.setVisible(not dispensed)
        self.top_list.set_rows(data.top_dispensed[:5])
        self.daily.set_days(data.daily)

    def _show_bucket(self, index: int) -> None:
        bucket = self.buckets[index]
        expired = bucket["status"] == logic.BATCH_EXPIRED and not bucket["year"]
        self.bucket_title.setText("Expired batches still on the shelf" if expired
                                  else f"Expiring in {bucket['label']} {bucket['year']}")
        n = len(bucket["batches"])
        self.bucket_count.setText(f"{n} batch{'es' if n != 1 else ''}")
        verb = "expired" if expired else "expires"
        rows = []
        for b in bucket["batches"]:
            d = logic.to_date(b["expiry"])
            rows.append((b["medicine"], f"{b['remaining']:,} left, {verb} {d.day} {d:%b %Y}"))
        self.bucket_list.set_rows(rows)
        self.bucket_empty.setVisible(not rows)
