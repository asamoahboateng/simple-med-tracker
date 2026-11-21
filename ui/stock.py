"""ui/stock.py - Stock & Batches: medicine stock levels and every batch."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QLineEdit, QSplitter, QWidget,
)

import logic
from ui.edit_batch import EditBatchDialog
from ui.medicine import EditMedicineDialog
from ui.models import (
    STATUS_COLOURS, Column, RecordTableModel, TableProxy, int_fmt, make_table, use_pills,
)
from ui.widgets import Card, focus_key, hint_label, leads_into, make_button, page_header, page_layout

MEDICINE_COLUMNS = [
    Column("name", "Medicine"),
    Column("unit", "Unit"),
    Column("reorder_level", "Reorder level", "right", int_fmt),
    Column("received", "Total received", "right", int_fmt),
    Column("dispensed", "Total dispensed", "right", int_fmt),
    Column("removed", "Total removed", "right", int_fmt),
    Column("stock", "Current stock", "right", int_fmt),
    Column("status", "Status", "center"),
    Column("nearest_expiry", "Nearest expiry", fmt=logic.expiry_label),
    Column("note", "Note"),
]

BATCH_COLUMNS = [
    Column("medicine", "Medicine"),
    Column("batch_no", "Batch No"),
    Column("expiry", "Expiry", fmt=logic.expiry_label),
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


def _search_box(placeholder: str, proxy: TableProxy, view) -> QLineEdit:
    box = QLineEdit()
    box.setPlaceholderText(placeholder)
    box.setClearButtonEnabled(True)
    box.setMinimumWidth(240)
    box.textChanged.connect(proxy.setFilterFixedString)
    leads_into(box, view)
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
        self.med_proxy = TableProxy()
        self.med_view = make_table(self.med_model, self.med_proxy)
        self.med_view.sortByColumn(0, Qt.AscendingOrder)
        use_pills(self.med_view, MEDICINE_COLUMNS, "status")
        self.med_view.setEditTriggers(self.med_view.EditTrigger.NoEditTriggers)
        self.med_view.doubleClicked.connect(self._edit_medicine)

        med_card = Card("Medicines")
        edit_hint = hint_label("   Double-click or press Enter to edit a medicine \u00b7 Alt+M")
        edit_hint.setWordWrap(False)
        med_card.header.insertWidget(1, edit_hint)
        self.med_search = _search_box("\U0001F50D  Search medicines", self.med_proxy, self.med_view)
        med_card.header.addWidget(self.med_search)
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
        batch_hint = hint_label("   Double-click or press Enter to edit a batch \u00b7 Alt+B")
        batch_hint.setWordWrap(False)
        batch_card.header.insertWidget(1, batch_hint)
        batch_card.header.addWidget(self.hide_used)
        batch_card.header.addSpacing(8)
        batch_card.header.addWidget(self.expiry_filter)
        batch_card.header.addSpacing(8)
        self.batch_search = _search_box("\U0001F50D  Search batches", self.batch_proxy, self.batch_view)
        batch_card.header.addWidget(self.batch_search)
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

        # Keyboard: Tab goes search -> medicines -> batch filters -> batch search -> batches.
        self.med_view.setAccessibleName("Medicines")
        self.batch_view.setAccessibleName("Batches")
        for widget_a, widget_b in ((self.med_search, self.med_view), (self.med_view, self.hide_used),
                                   (self.hide_used, self.expiry_filter),
                                   (self.expiry_filter, self.batch_search),
                                   (self.batch_search, self.batch_view)):
            QWidget.setTabOrder(widget_a, widget_b)
        focus_key(self, "Alt+M", self.med_view)
        focus_key(self, "Alt+B", self.batch_view)
        focus_key(self, "Alt+S", self.med_search)

    def refresh(self):
        self.med_model.set_rows(logic.medicine_rows(self.conn))
        self.batch_model.set_rows(logic.batch_rows(self.conn))

    def _batch_visible(self, row: dict) -> bool:
        if self.hide_used.isChecked() and row["status"] == logic.BATCH_USED_UP:
            return False
        test = self.expiry_filter.currentData()
        days = row["days_to_expiry"]          # None = never expires: only under "Any expiry"
        return test is None or (days is not None and test(days))

    @staticmethod
    def _batch_colour(row: dict, key: str):
        """Highlight the days-to-expiry number of expired / expiring batches."""
        if key == "days_to_expiry" and row["status"] in (logic.BATCH_EXPIRED,
                                                         logic.BATCH_EXPIRING):
            return STATUS_COLOURS.get(row["status"])
        return None

    def _edit_medicine(self, index):
        """Double-clicking a medicine opens the Edit Medicine pop-up."""
        row = self.med_model.row_dict(self.med_proxy.mapToSource(index).row())
        if EditMedicineDialog(self.conn, row, self).exec():
            self.data_changed.emit()

    def _edit_batch(self, index):
        """Double-clicking a batch opens the Edit Batch pop-up."""
        row = self.batch_model.row_dict(self.batch_proxy.mapToSource(index).row())
        if EditBatchDialog(self.conn, row, self, changed_by=self.user_name).exec():
            self.data_changed.emit()
