"""ui/stock.py - Stock & Batches: medicine stock levels and every batch."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QLineEdit, QSplitter, QWidget,
)

import logic
from ui.edit_batch import EditBatchDialog
from ui.models import (
    STATUS_COLOURS, Column, RecordTableModel, TableProxy, int_fmt, make_table, use_pills,
)
from ui.widgets import (
    Card, hint_label, make_button, page_header, page_layout, show_error,
)

MEDICINE_COLUMNS = [
    Column("name", "Medicine", editable=True),
    Column("unit", "Unit", editable=True),
    Column("reorder_level", "Reorder level", "right", int_fmt, editable=True),
    Column("received", "Total received", "right", int_fmt),
    Column("dispensed", "Total dispensed", "right", int_fmt),
    Column("removed", "Total removed", "right", int_fmt),
    Column("stock", "Current stock", "right", int_fmt),
    Column("status", "Status", "center"),
    Column("nearest_expiry", "Nearest expiry"),
    Column("note", "Note", editable=True),
]

BATCH_COLUMNS = [
    Column("medicine", "Medicine"),
    Column("batch_no", "Batch No"),
    Column("expiry", "Expiry"),
    Column("received", "Received", "right", int_fmt),
    Column("dispensed", "Dispensed", "right", int_fmt),
    Column("removed", "Removed", "right", int_fmt),
    Column("remaining", "Remaining", "right", int_fmt),
    Column("days_to_expiry", "Days to expiry", "right"),
    Column("status", "Status", "center"),
]


# (label, test on days to expiry); None = no expiry filter
EXPIRY_FILTERS = [
    ("Any expiry", None),
    ("Expired", lambda days: days < 0),
    ("Expiring within 30 days", lambda days: 0 <= days <= 30),
    ("Expiring within 90 days", lambda days: 0 <= days <= 90),
    ("Expiring within 6 months", lambda days: 0 <= days <= 182),
    ("Expiring within 1 year", lambda days: 0 <= days <= 365),
    ("Expired or within 90 days", lambda days: days <= 90),
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
    units_requested = Signal()

    def __init__(self, conn, parent=None, user_name: str = ""):
        super().__init__(parent)
        self.conn = conn
        self.user_name = user_name   # recorded in the audit log if a batch's quantity changes

        # --- medicines ---
        self.med_model = RecordTableModel(MEDICINE_COLUMNS)
        self.med_model.edit_fn = self._save_edit
        self.med_proxy = TableProxy()
        self.med_view = make_table(self.med_model, self.med_proxy)
        self.med_view.sortByColumn(0, Qt.AscendingOrder)
        use_pills(self.med_view, MEDICINE_COLUMNS, "status")

        med_card = Card("Medicines")
        edit_hint = hint_label("   Double-click Medicine, Unit, Reorder level or Note to edit")
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
        self.expiry_filter = QComboBox()
        for label, test in EXPIRY_FILTERS:
            self.expiry_filter.addItem(label, test)
        self.expiry_filter.setToolTip("Show only batches expiring in this period")
        self.batch_proxy.filter_fn = self._batch_visible
        self.hide_used.toggled.connect(self.batch_proxy.refilter)
        self.expiry_filter.currentIndexChanged.connect(self.batch_proxy.refilter)
        self.batch_view = make_table(self.batch_model, self.batch_proxy)
        self.batch_view.sortByColumn(2, Qt.AscendingOrder)
        use_pills(self.batch_view, BATCH_COLUMNS, "status")
        self.batch_view.doubleClicked.connect(self._edit_batch)

        batch_card = Card("Batches")
        batch_hint = hint_label("   Double-click a batch to edit it")
        batch_hint.setWordWrap(False)
        batch_card.header.insertWidget(1, batch_hint)
        batch_card.header.addWidget(self.hide_used)
        batch_card.header.addSpacing(8)
        batch_card.header.addWidget(self.expiry_filter)
        batch_card.header.addSpacing(8)
        batch_card.header.addWidget(_search_box("\U0001F50D  Search batches", self.batch_proxy))
        batch_card.body.addWidget(self.batch_view)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(med_card)
        splitter.addWidget(batch_card)

        new_btn = make_button("New Medicine", "primary", icon_text="+")
        new_btn.clicked.connect(self.new_medicine_requested.emit)
        units_btn = make_button("Units", "outline")
        units_btn.setToolTip("Add or remove the units offered when adding a medicine")
        units_btn.clicked.connect(self.units_requested.emit)
        layout = page_layout(self)
        layout.addWidget(page_header(
            "Stock & Batches", "Stock levels are calculated from the log (received \u2212 dispensed \u2212 removed)",
            units_btn, new_btn))
        layout.addWidget(splitter, 1)

    def refresh(self):
        self.med_model.set_rows(logic.medicine_rows(self.conn))
        self.batch_model.set_rows(logic.batch_rows(self.conn))

    def _batch_visible(self, row: dict) -> bool:
        if self.hide_used.isChecked() and row["status"] == logic.BATCH_USED_UP:
            return False
        test = self.expiry_filter.currentData()
        return test is None or test(row["days_to_expiry"])

    @staticmethod
    def _batch_colour(row: dict, key: str):
        """Highlight the days-to-expiry number of expired / expiring batches."""
        if key == "days_to_expiry" and row["status"] in (logic.BATCH_EXPIRED,
                                                         logic.BATCH_EXPIRING):
            return STATUS_COLOURS.get(row["status"])
        return None

    def _save_edit(self, row: dict, key: str, value) -> bool:
        """Called when the user edits Medicine, Unit, Reorder level or Note in the table."""
        try:
            if key == "name":
                logic.rename_medicine(self.conn, row["id"], value)
            elif key == "unit":
                logic.update_medicine_settings(self.conn, row["id"], unit=value)
            elif key == "reorder_level":
                logic.update_medicine_settings(self.conn, row["id"], reorder_level=value)
            elif key == "note":
                logic.update_medicine_settings(self.conn, row["id"], note=value)
            else:
                return False
        except logic.ValidationError as exc:
            show_error(self, str(exc))
            return False
        # Refresh everything after the editor has closed (not in the middle of editing).
        QTimer.singleShot(0, self.data_changed.emit)
        return True

    def _edit_batch(self, index):
        """Double-clicking a batch opens the Edit Batch pop-up."""
        row = self.batch_model.row_dict(self.batch_proxy.mapToSource(index).row())
        if EditBatchDialog(self.conn, row, self, changed_by=self.user_name).exec():
            self.data_changed.emit()
