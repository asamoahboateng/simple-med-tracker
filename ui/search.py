"""ui/search.py - Search: find a medicine, then see its details, batches and log."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

import logic
from ui import theme
from ui.edit_entry import DeleteEntryDialog, EditEntryDialog
from ui.log import LOG_COLUMNS
from ui.models import STATUS_COLOURS, Column, RecordTableModel, TableProxy, int_fmt, make_table, use_pills
from ui.responsive import FlowGrid
from ui.stock import BATCH_COLUMNS
from ui.widgets import (
    Card, SummaryCard, hint_label, make_button, page_header, page_layout, show_info,
)

RESULT_COLUMNS = [
    Column("name", "Medicine"),
    Column("stock", "Stock", "right", int_fmt),
    Column("status", "Status", "center"),
]
# The detail tables don't need a Medicine column, and are read-only here.
DETAIL_LOG_COLUMNS = [Column(c.key, c.header, c.align, c.fmt) for c in LOG_COLUMNS
                      if c.key != "medicine"]
DETAIL_BATCH_COLUMNS = [Column(c.key, c.header, c.align, c.fmt) for c in BATCH_COLUMNS
                        if c.key != "medicine"]


class SearchPage(QWidget):
    data_changed = Signal()

    def __init__(self, conn, parent=None, user_name: str = ""):
        super().__init__(parent)
        self.conn = conn
        self.user_name = user_name   # recorded in the audit log for edits and deletes
        self.medicine_id = None

        # --- left: search box and results ---
        self.search = QLineEdit()
        self.search.setPlaceholderText("\U0001F50D  Search medicine name or note")
        self.search.setClearButtonEnabled(True)
        self.result_model = RecordTableModel(RESULT_COLUMNS)
        self.result_proxy = TableProxy()
        self.result_view = make_table(self.result_model, self.result_proxy)
        self.result_view.setEditTriggers(self.result_view.EditTrigger.NoEditTriggers)
        use_pills(self.result_view, RESULT_COLUMNS, "status")
        self.result_count = hint_label("")

        results_card = Card("Medicines")
        results_card.body.addWidget(self.search)
        results_card.body.addWidget(self.result_view, 1)
        results_card.body.addWidget(self.result_count)
        results_card.setMinimumWidth(260)

        # --- right: details of the chosen medicine ---
        self.empty = QLabel("Search for a medicine and click it to see its details and log.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 15px;")

        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self._build_details())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(results_card)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([300, 900])

        layout = page_layout(self)
        layout.addWidget(page_header("Search", "Find a medicine to see its stock, batches and log"))
        layout.addWidget(splitter, 1)

        self.search.textChanged.connect(self._load_results)
        self.result_view.selectionModel().currentRowChanged.connect(self._result_chosen)

    def _build_details(self) -> QWidget:
        self.name_label = QLabel()
        self.name_label.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {theme.TEXT};")
        self.status_label = QLabel()
        self.facts_label = QLabel()
        self.facts_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self.facts_label.setWordWrap(True)
        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        self.note_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        title_row = QHBoxLayout()
        title_row.addWidget(self.name_label)
        title_row.addSpacing(10)
        title_row.addWidget(self.status_label)
        title_row.addStretch()

        self.stock_card = SummaryCard("Current stock", theme.PRIMARY)
        self.received_card = SummaryCard("Total received", theme.GREEN)
        self.dispensed_card = SummaryCard("Total dispensed", theme.BLUE)
        self.expiry_card = SummaryCard("Nearest expiry", theme.AMBER)
        tiles = FlowGrid([self.stock_card, self.received_card, self.dispensed_card,
                          self.expiry_card], min_item_width=160)

        self.log_model = RecordTableModel(DETAIL_LOG_COLUMNS)
        self.log_view = make_table(self.log_model, TableProxy())
        self.log_view.setEditTriggers(self.log_view.EditTrigger.NoEditTriggers)
        use_pills(self.log_view, DETAIL_LOG_COLUMNS, "type")
        self.log_view.doubleClicked.connect(self._edit_entry)
        self.log_card = Card("Log")
        log_hint = hint_label("   Double-click an entry to correct its quantity")
        log_hint.setWordWrap(False)
        self.log_card.header.insertWidget(1, log_hint)
        delete_btn = make_button("Delete entry", "danger", icon_text="\u2716")
        delete_btn.clicked.connect(self._delete_entry)
        self.log_card.header.addWidget(delete_btn)
        self.log_card.body.addWidget(self.log_view)

        self.batch_model = RecordTableModel(DETAIL_BATCH_COLUMNS)
        self.batch_view = make_table(self.batch_model, TableProxy())
        self.batch_view.setEditTriggers(self.batch_view.EditTrigger.NoEditTriggers)
        use_pills(self.batch_view, DETAIL_BATCH_COLUMNS, "status")
        self.batch_card = Card("Batches")
        self.batch_card.body.addWidget(self.batch_view)

        tables = QSplitter(Qt.Vertical)
        tables.setChildrenCollapsible(False)
        tables.addWidget(self.log_card)
        tables.addWidget(self.batch_card)
        tables.setSizes([500, 250])

        details = QWidget()
        col = QVBoxLayout(details)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        col.addLayout(title_row)
        col.addWidget(self.facts_label)
        col.addWidget(self.note_label)
        col.addWidget(tiles)
        col.addWidget(tables, 1)
        return details

    # --- data ---------------------------------------------------------------
    def refresh(self):
        self._load_results()

    def _load_results(self, *_):
        chosen = self.medicine_id
        self.result_model.set_rows(logic.search_medicines(self.conn, self.search.text()))
        count = self.result_model.rowCount()
        self.result_count.setText(f"{count:,} medicine{'s' if count != 1 else ''} found")
        # Keep showing the chosen medicine if it is still in the results.
        for r in range(self.result_proxy.rowCount()):
            index = self.result_proxy.index(r, 0)
            if self.result_model.row_dict(self.result_proxy.mapToSource(index).row())["id"] == chosen:
                self.result_view.setCurrentIndex(index)
                self._show_medicine(chosen)
                return
        self._show_medicine(None)

    def _result_chosen(self, current, _previous):
        if current.isValid():
            row = self.result_model.row_dict(self.result_proxy.mapToSource(current).row())
            self._show_medicine(row["id"])

    def _show_medicine(self, medicine_id):
        self.medicine_id = medicine_id
        med = next((m for m in self.result_model.rows if m["id"] == medicine_id), None)
        if med is None:
            self.medicine_id = None
            self.stack.setCurrentIndex(0)
            return
        unit = med["unit"]
        self.name_label.setText(med["name"])
        background, text = STATUS_COLOURS.get(med["status"], ("#eeeeee", theme.TEXT))
        self.status_label.setText(med["status"])
        self.status_label.setStyleSheet(
            f"background: {background}; color: {text}; font-weight: 700;"
            f" border-radius: 10px; padding: 3px 10px;")
        self.facts_label.setText(f"Unit: {unit}    ·    Reorder level: {med['reorder_level']:,}")
        self.note_label.setText(f"Note: {med['note']}" if med["note"] else "")
        self.note_label.setVisible(bool(med["note"]))

        self.stock_card.set_value(med["stock"], unit)
        self.received_card.set_value(med["received"], unit)
        self.dispensed_card.set_value(med["dispensed"], unit)
        self.expiry_card.set_value(med["nearest_expiry"] or "-",
                                   "" if med["nearest_expiry"] else "No stock left")

        log = logic.medicine_log(self.conn, medicine_id)
        batches = logic.medicine_batches(self.conn, medicine_id)
        self.log_model.set_rows(log)
        self.batch_model.set_rows(batches)
        self.log_card.title_label.setText(f"Log ({len(log):,})")
        self.batch_card.title_label.setText(f"Batches ({len(batches):,})")
        self.stack.setCurrentIndex(1)

    # --- edit ---------------------------------------------------------------
    def _delete_entry(self):
        index = self.log_view.currentIndex()
        if not index.isValid():
            show_info(self, "Select an entry in the log first.", title="Delete entry")
            return
        row = self.log_model.row_dict(self.log_view.model().mapToSource(index).row())
        if DeleteEntryDialog(self.conn, row, self, changed_by=self.user_name).exec():
            show_info(self, "The entry was deleted.", title="Deleted")
            self.data_changed.emit()

    def _edit_entry(self, index):
        row = self.log_model.row_dict(self.log_view.model().mapToSource(index).row())
        if EditEntryDialog(self.conn, row, self, changed_by=self.user_name).exec():
            show_info(self, "The entry was corrected.", title="Saved")
            self.data_changed.emit()
