"""ui/dashboard.py - The start page: summary cards, quick buttons, charts and alerts."""

from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

import logic
from config import EXPIRY_WARNING_DAYS
from ui import theme
from ui.charts import BLUE, STATUS_BAR_COLOURS, ChartCard
from ui.models import AMBER, GREEN, RED
from ui.responsive import FlowGrid
from ui.widgets import Card, SummaryCard, make_button, page_header, page_layout, scrolling_page


def _greeting() -> str:
    hour = datetime.now().hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"


class DashboardPage(QWidget):
    add_stock_requested = Signal()
    dispense_requested = Signal()

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn

        # --- header with the two main actions ---
        add_btn = make_button("Add Stock", "primary", large=True, icon_text="+")
        give_btn = make_button("Record Dispensed", "blue", large=True, icon_text="\U0001F48A")
        add_btn.clicked.connect(self.add_stock_requested.emit)
        give_btn.clicked.connect(self.dispense_requested.emit)
        self.header = page_header(_greeting(), "", add_btn, give_btn)

        # --- summary cards ---
        self.card_dispensed = SummaryCard("Dispensed this month", theme.BLUE, "\U0001F48A")
        self.card_medicines = SummaryCard("Medicines", theme.PRIMARY, "\U0001F9F4")
        self.card_low = SummaryCard("Low or out of stock", theme.AMBER, "\U0001F4C9")
        self.card_expiry = SummaryCard("Expired / expiring soon", theme.RED, "⏳")
        # 4 across on wide windows, 2 x 2 on medium, 1 per row on narrow.
        cards = FlowGrid([self.card_dispensed, self.card_medicines, self.card_low,
                          self.card_expiry], min_item_width=200, max_columns=4)

        # --- charts ---
        self.top_card = ChartCard("Most dispensed this month", "Top 10 medicines by quantity")
        self.low_card = ChartCard("Lowest stock", "The 15 medicines with the least stock")
        self.daily_card = ChartCard("Daily dispensing", "Total quantity dispensed each day")

        # --- alerts ---
        self.alerts_card = Card("Alerts")
        self.alert_count = QLabel("0")
        self.alert_count.setObjectName("countBadge")
        self.alerts_card.header.insertWidget(1, self.alert_count)
        alerts_box = QWidget()
        alerts_box.setObjectName("alertsBox")
        self.alerts = QVBoxLayout(alerts_box)
        self.alerts.setContentsMargins(0, 0, 4, 0)
        self.alerts.setSpacing(8)
        self.alerts.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setMinimumHeight(270)
        scroll.setStyleSheet("QScrollArea, QWidget#alertsBox { background: white; }")
        scroll.setWidget(alerts_box)
        self.alerts_card.body.addWidget(scroll)

        # Two panels side by side when there is room, otherwise one per row.
        grid = FlowGrid([self.top_card, self.low_card, self.daily_card, self.alerts_card],
                        min_item_width=420, max_columns=2)

        content = QWidget()
        layout = page_layout(content)
        layout.addWidget(self.header)
        layout.addWidget(cards)
        layout.addWidget(grid)
        layout.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolling_page(content))

    def refresh(self):
        data = logic.dashboard_data(self.conn)
        today = date.today()

        self.header.subtitle_label.setText(
            f"{today:%A, %d %B %Y}  ·  Here's how your pharmacy is doing")

        self.card_dispensed.set_value(data.dispensed_this_month, f"{today:%B %Y}")
        self.card_medicines.set_value(data.medicine_count, "in your catalogue")
        self.card_low.set_value(data.low_or_out_count, "at or below reorder level")
        self.card_expiry.set_value(data.expiry_alert_count,
                                   f"batches within {EXPIRY_WARNING_DAYS} days")

        self.top_card.chart.plot_barh(
            [n for n, _ in data.top_dispensed], [q for _, q in data.top_dispensed],
            colour=BLUE, empty_message="Nothing dispensed yet this month")
        self.low_card.chart.plot_bar(
            [n for n, _, _ in data.lowest_stock], [s for _, s, _ in data.lowest_stock],
            colours=[STATUS_BAR_COLOURS[st] for _, _, st in data.lowest_stock],
            empty_message="No medicines yet")
        self.daily_card.chart.plot_daily([d for d, _ in data.daily], [q for _, q in data.daily])

        while self.alerts.count() > 1:          # remove old rows, keep the final stretch
            self.alerts.takeAt(0).widget().deleteLater()
        for m in data.stock_alerts:
            out = m["status"] == logic.STATUS_OUT
            self._add_alert(
                "⛔" if out else "⚠️",
                f"{m['name']} is {'out of stock' if out else 'running low'}",
                f"{m['stock']:,} {m['unit']} left · reorder level {m['reorder_level']:,}",
                RED if out else AMBER)
        for b in data.expiry_alerts:
            days = logic.days_to_expiry(b["expiry"], today)
            when = (f"expired {-days} days ago" if days < 0
                    else "expires today" if days == 0 else f"expires in {days} days")
            expired = b["status"] == logic.BATCH_EXPIRED
            self._add_alert(
                "\U0001F5D3️",
                f"{b['medicine']} · batch {b['batch_no']} {when}",
                f"Expiry {b['expiry']} · {b['remaining']:,} {b['unit']} still in stock",
                RED if expired else AMBER)

        count = self.alerts.count() - 1
        self.alert_count.setText(str(count))
        self.alert_count.setVisible(count > 0)
        if count == 0:
            self._add_alert("✅", "All good", "No low stock and no expiring batches.", GREEN)

    def _add_alert(self, icon: str, title: str, detail: str, colours):
        """One alert row: tinted background, icon, coloured title and grey detail."""
        background, text = colours
        row = QFrame()
        row.setStyleSheet(f"QFrame {{ background: {background}; border-radius: 10px; }}"
                          f" QLabel {{ background: transparent; border: none; }}")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 9, 12, 9)
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 16px;")
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_label.setStyleSheet(f"color: {text}; font-weight: 700;")
        detail_label = QLabel(detail)
        detail_label.setWordWrap(True)
        detail_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
        texts.addWidget(title_label)
        texts.addWidget(detail_label)
        layout.addWidget(icon_label, 0, Qt.AlignTop)
        layout.addLayout(texts, 1)
        self.alerts.insertWidget(self.alerts.count() - 1, row)
