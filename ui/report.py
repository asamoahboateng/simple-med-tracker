"""ui/report.py - Monthly Report with Excel and PDF export."""

import calendar
from datetime import date

from PySide6.QtCore import QMarginsF, QSizeF, QUrl, Qt
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QSpinBox, QVBoxLayout, QWidget,
)

import exports
import logic
from config import APP_NAME
from ui import theme
from ui.charts import BLUE, ChartCard
from ui.models import Column, RecordTableModel, TableProxy, int_fmt, make_table, use_pills
from ui.responsive import FlowGrid
from ui.widgets import (
    Card, SummaryCard, make_button, page_header, page_layout, scrolling_page, show_error,
    show_info,
)

RANK_COLUMNS = [
    Column("rank", "Rank", "right"),
    Column("medicine", "Medicine"),
    Column("dispensed", "Qty dispensed", "right", int_fmt),
    Column("percent", "% of total", "right", lambda v: f"{v:.1f}%"),
    Column("received", "Qty received", "right", int_fmt),
    Column("stock", "Current stock", "right", int_fmt),
    Column("status", "Status", "center"),
]
DAY_COLUMNS = [Column("date", "Date"), Column("qty", "Quantity", "right", int_fmt)]
PRESCRIBER_COLUMNS = [
    Column("prescriber", "Prescriber"),
    Column("qty", "Total quantity", "right", int_fmt),
    Column("entries", "Entries", "right", int_fmt),
]


def _section(title: str, widget) -> Card:
    card = Card(title)
    card.body.addWidget(widget)
    return card


class ReportPage(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.report: logic.MonthlyReport | None = None

        # --- month / year selectors and export buttons ---
        today = date.today()
        self.month_combo = QComboBox()
        for m in range(1, 13):
            self.month_combo.addItem(calendar.month_name[m], m)
        self.month_combo.setCurrentIndex(today.month - 1)
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(today.year)
        excel_btn = make_button("Export Excel", icon_text="\U0001F4C4")
        pdf_btn = make_button("Export PDF", "primary", icon_text="\U0001F5A8\uFE0F")

        picker = QWidget()
        pick = QHBoxLayout(picker)
        pick.setContentsMargins(0, 0, 12, 0)
        pick.addWidget(self.month_combo)
        pick.addWidget(self.year_spin)
        self.month_combo.setMinimumWidth(140)

        # --- summary cards ---
        self.cards = {
            "total_dispensed": SummaryCard("Total dispensed", theme.BLUE, "\U0001F48A"),
            "total_received": SummaryCard("Stock received", theme.PRIMARY, "\U0001F4E6"),
            "entry_count": SummaryCard("Dispensing entries", theme.PURPLE, "\U0001F4DD"),
            "medicines_dispensed": SummaryCard("Medicines dispensed", theme.AMBER, "\U0001F9F4"),
            "avg_per_day": SummaryCard("Average per day", theme.RED, "\U0001F4C8"),
        }
        cards = FlowGrid(list(self.cards.values()), min_item_width=190, max_columns=5)

        # --- tables and chart ---
        self.rank_model = RecordTableModel(RANK_COLUMNS)
        self.rank_view = make_table(self.rank_model, TableProxy())
        self.rank_view.setMinimumHeight(380)
        use_pills(self.rank_view, RANK_COLUMNS, "status")

        self.day_model = RecordTableModel(DAY_COLUMNS)
        self.day_view = make_table(self.day_model, TableProxy())
        self.day_view.setFixedHeight(5 * 36 + 44)

        self.prescriber_model = RecordTableModel(PRESCRIBER_COLUMNS)
        self.prescriber_view = make_table(self.prescriber_model, TableProxy())
        self.prescriber_view.setMinimumHeight(5 * 36 + 44)

        chart_card = ChartCard("Top 10 medicines", "By quantity dispensed this month")
        self.chart = chart_card.chart

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(16)
        side_layout.addWidget(_section("Top 5 busiest days", self.day_view))
        side_layout.addWidget(_section("By prescriber", self.prescriber_view))
        # Chart and the two small tables side by side, or stacked on narrow windows.
        grid = FlowGrid([chart_card, side], min_item_width=420, max_columns=2)
        rank_card = _section("Medicines ranked by quantity dispensed", self.rank_view)

        content = QWidget()
        layout = page_layout(content)
        self.header = page_header("Monthly Report", "", picker, excel_btn, pdf_btn)
        layout.addWidget(self.header)
        layout.addWidget(cards)
        layout.addWidget(grid)
        layout.addWidget(rank_card)
        layout.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolling_page(content))

        self.month_combo.currentIndexChanged.connect(self.refresh)
        self.year_spin.valueChanged.connect(self.refresh)
        excel_btn.clicked.connect(self.export_excel)
        pdf_btn.clicked.connect(self.export_pdf)

    def refresh(self, *_):
        self.report = r = logic.monthly_report(
            self.conn, self.year_spin.value(), self.month_combo.currentData())
        for key, card in self.cards.items():
            card.set_value(getattr(r, key))
        self.cards["avg_per_day"].set_value(r.avg_per_day, f"over {r.days_counted} days")
        self.cards["total_dispensed"].set_value(r.total_dispensed, "units")
        self.header.subtitle_label.setText(f"Dispensing summary for {r.title}")

        self.rank_model.set_rows(r.medicines)
        self.rank_view.sortByColumn(0, Qt.AscendingOrder)
        self.day_model.set_rows(exports.top_day_rows(r))
        self.prescriber_model.set_rows(r.prescribers)

        top10 = [m for m in r.medicines if m["dispensed"] > 0][:10]
        self.chart.plot_barh([m["medicine"] for m in top10], [m["dispensed"] for m in top10],
                             colour=BLUE, empty_message=f"Nothing dispensed in {r.title}")

    # --- exports ------------------------------------------------------------
    def _ask_path(self, extension: str, description: str) -> str | None:
        r = self.report
        suggested = f"medtracker_report_{r.year}-{r.month:02d}.{extension}"
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
        document = QTextDocument()
        document.addResource(QTextDocument.ImageResource, QUrl("chart.png"),
                             QImage.fromData(self.chart.png_bytes()))
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
