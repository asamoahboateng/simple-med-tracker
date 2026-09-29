"""ui/stock.py - Stock & Batches: medicine stock levels and every batch."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QLineEdit, QSplitter, QWidget,
)

import logic
from ui.models import (
    STATUS_COLOURS, Column, RecordTableModel, TableProxy, int_fmt, make_table, use_pills,
)
from ui.widgets import Card, hint_label, make_button, page_header, page_layout, show_error

MEDICINE_COLUMNS = [
    Column("name", "Medicine"),
    Column("unit", "Unit", editable=True),
    Column("reorder_level", "Reorder level", "right", int_fmt, editable=True),
    Column("received", "Total received", "right", int_fmt),
    Column("dispensed", "Total dispensed", "right", int_fmt),
    Column("stock", "Current stock", "right", int_fmt),
    Column("status", "Status", "center"),
    Column("nearest_expiry", "Nearest expiry"),
]

BATCH_COLUMNS = [
    Column("medicine", "Medicine"),
    Column("batch_no", "Batch No"),
    Column("expiry", "Expiry"),
    Column("received", "Received", "right", int_fmt),
    Column("dispensed", "Dispensed", "right", int_fmt),
    Column("remaining", "Remaining", "right", int_fmt),
    Column("days_to_expiry", "Days to expiry", "right"),
    Column("status", "Status", "center"),
]


def _search_box(placeholder: str, proxy: TableProxy) -> QLineEdit:
    box = QLineEdit()
    box.setPlaceholderText(placeholder)
    box.setClearButtonEnabled(True)
    box.setMinimumWidth(240)
    box.textChanged.connect(proxy.setFilterFixedString)
    return box


class StockPage(QWidget):
    data_changed = Signal()
    new_medicine_requested = Signal()

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn

        # --- medicines ---
        self.med_model = RecordTableModel(MEDICINE_COLUMNS)
        self.med_model.edit_fn = self._save_edit
        self.med_proxy = TableProxy()
        self.med_view = make_table(self.med_model, self.med_proxy)
        self.med_view.sortByColumn(0, Qt.AscendingOrder)
        use_pills(self.med_view, MEDICINE_COLUMNS, "status")

        med_card = Card("Medicines")
        edit_hint = hint_label("   Double-click Unit or Reorder level to edit")
        edit_hint.setWordWrap(False)
        med_card.header.insertWidget(1, edit_hint)
        med_card.header.addWidget(_search_box("\U0001F50D  Search medicines", self.med_proxy))
        med_card.body.addWidget(self.med_view)

        # --- batches ---
        self.batch_model = RecordTableModel(BATCH_COLUMNS)
        self.batch_model.colour_fn = self._batch_colour
        self.batch_proxy = TableProxy()
        self.hide_used = QCheckBox("Hide used-up batches")
        self.hide_used.setChecked(True)
        self.batch_proxy.filter_fn = (
            lambda row: not (self.hide_used.isChecked() and row["status"] == logic.BATCH_USED_UP))
        self.hide_used.toggled.connect(self.batch_proxy.refilter)
        self.batch_view = make_table(self.batch_model, self.batch_proxy)
        self.batch_view.sortByColumn(2, Qt.AscendingOrder)
        use_pills(self.batch_view, BATCH_COLUMNS, "status")

        batch_card = Card("Batches")
        batch_card.header.addWidget(self.hide_used)
        batch_card.header.addSpacing(8)
        batch_card.header.addWidget(_search_box("\U0001F50D  Search batches", self.batch_proxy))
        batch_card.body.addWidget(self.batch_view)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(med_card)
        splitter.addWidget(batch_card)

        new_btn = make_button("New Medicine", "primary", icon_text="+")
        new_btn.clicked.connect(self.new_medicine_requested.emit)
        layout = page_layout(self)
        layout.addWidget(page_header(
            "Stock & Batches", "Stock levels are calculated from the log (received \u2212 dispensed)",
            new_btn))
        layout.addWidget(splitter, 1)

    def refresh(self):
        self.med_model.set_rows(logic.medicine_rows(self.conn))
        self.batch_model.set_rows(logic.batch_rows(self.conn))

    @staticmethod
    def _batch_colour(row: dict, key: str):
        """Highlight the days-to-expiry number of expired / expiring batches."""
        if key == "days_to_expiry" and row["status"] in (logic.BATCH_EXPIRED,
                                                         logic.BATCH_EXPIRING):
            return STATUS_COLOURS.get(row["status"])
        return None

    def _save_edit(self, row: dict, key: str, value) -> bool:
        """Called when the user edits Unit or Reorder level in the table."""
        try:
            if key == "unit":
                logic.update_medicine_settings(self.conn, row["id"], unit=value)
            elif key == "reorder_level":
                logic.update_medicine_settings(self.conn, row["id"], reorder_level=value)
            else:
                return False
        except logic.ValidationError as exc:
            show_error(self, str(exc))
            return False
        # Refresh everything after the editor has closed (not in the middle of editing).
        QTimer.singleShot(0, self.data_changed.emit)
        return True
