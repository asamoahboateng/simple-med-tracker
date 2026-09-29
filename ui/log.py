"""ui/log.py - Dispensing Log: every transaction, with filters, undo and export."""

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QWidget,
)

import exports
import logic
from ui.models import Column, RecordTableModel, TableProxy, int_fmt, make_table, use_pills
from ui.responsive import FlowLayout
from ui.widgets import (
    Card, ask_yes_no, hint_label, make_button, make_date_edit, page_header, page_layout,
    show_error, show_info, to_py_date,
)

LOG_COLUMNS = [
    Column("date", "Date"),
    Column("medicine", "Medicine"),
    Column("type", "Type", "center"),
    Column("quantity", "Quantity", "right", int_fmt),
    Column("batch_no", "Batch No"),
    Column("expiry", "Expiry"),
    Column("patient_id", "Patient ID"),
    Column("prescriber", "Prescriber"),
    Column("balance_after", "Balance After", "right", int_fmt),
    Column("entered_at", "Entered At"),
]


class LogPage(QWidget):
    data_changed = Signal()

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn

        self.model = RecordTableModel(LOG_COLUMNS)
        self.proxy = TableProxy()
        self.proxy.filter_fn = self._row_matches
        self.view = make_table(self.model, self.proxy)
        self.view.sortByColumn(0, Qt.DescendingOrder)
        use_pills(self.view, LOG_COLUMNS, "type")

        # --- filters ---
        self.use_dates = QCheckBox("Dates from")
        first_of_month = date.today().replace(day=1)
        self.from_date = make_date_edit(first_of_month)
        self.to_date = make_date_edit()
        self.medicine_filter = QComboBox()
        self.medicine_filter.setMinimumWidth(180)
        self.type_filter = QComboBox()
        self.type_filter.addItem("All types", None)
        self.type_filter.addItem("Stock in", logic.STOCK_IN)
        self.type_filter.addItem("Dispensed", logic.DISPENSED)
        self.search = QLineEdit()
        self.search.setPlaceholderText("\U0001F50D  Search patient ID or prescriber")
        self.search.setClearButtonEnabled(True)
        clear_btn = make_button("Clear")

        filter_card = Card()
        filter_card.body.setContentsMargins(14, 12, 14, 12)
        filter_area = QWidget()
        filters = FlowLayout(filter_area, spacing=10)   # wraps onto more lines when narrow
        filter_card.body.addWidget(filter_area)
        dates = QWidget()
        dates_row = QHBoxLayout(dates)
        dates_row.setContentsMargins(0, 0, 0, 0)
        dates_row.addWidget(self.use_dates)
        dates_row.addWidget(self.from_date)
        dates_row.addWidget(QLabel("to"))
        dates_row.addWidget(self.to_date)
        self.search.setMinimumWidth(220)
        self.search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for widget in (dates, self.medicine_filter, self.type_filter, self.search, clear_btn):
            filters.addWidget(widget)

        # --- actions ---
        undo_btn = make_button("Undo last entry", "danger", icon_text="\u21b6")
        excel_btn = make_button("Export Excel", icon_text="\U0001F4C4")
        csv_btn = make_button("Export CSV", icon_text="\U0001F4C4")
        self.count_label = hint_label("")
        self.count_label.setWordWrap(False)
        actions = QHBoxLayout()
        actions.addWidget(self.count_label)
        actions.addStretch()
        actions.addWidget(undo_btn)

        layout = page_layout(self)
        layout.addWidget(page_header("Dispensing Log", "Every stock movement, newest first",
                                     excel_btn, csv_btn))
        layout.addWidget(filter_card)
        layout.addWidget(self.view, 1)
        layout.addLayout(actions)

        for widget_signal in (self.use_dates.toggled, self.from_date.dateChanged,
                              self.to_date.dateChanged, self.medicine_filter.currentIndexChanged,
                              self.type_filter.currentIndexChanged, self.search.textChanged):
            widget_signal.connect(self._apply_filters)
        self.use_dates.toggled.connect(self._update_date_enabled)
        clear_btn.clicked.connect(self._clear_filters)
        undo_btn.clicked.connect(self.undo_last)
        excel_btn.clicked.connect(lambda: self.export("xlsx"))
        csv_btn.clicked.connect(lambda: self.export("csv"))
        self._update_date_enabled()

    # --- data ---------------------------------------------------------------
    def refresh(self):
        self.model.set_rows(logic.log_rows(self.conn))
        chosen = self.medicine_filter.currentData()
        self.medicine_filter.blockSignals(True)
        self.medicine_filter.clear()
        self.medicine_filter.addItem("All medicines", None)
        for name in sorted({r["medicine"] for r in self.model.rows}, key=str.casefold):
            self.medicine_filter.addItem(name, name)
        index = self.medicine_filter.findData(chosen)
        self.medicine_filter.setCurrentIndex(max(index, 0))
        self.medicine_filter.blockSignals(False)
        self._apply_filters()

    # --- filtering ----------------------------------------------------------
    def _update_date_enabled(self):
        self.from_date.setEnabled(self.use_dates.isChecked())
        self.to_date.setEnabled(self.use_dates.isChecked())

    def _row_matches(self, row: dict) -> bool:
        if self.use_dates.isChecked():
            start = to_py_date(self.from_date.date()).isoformat()
            end = to_py_date(self.to_date.date()).isoformat()
            if not (start <= row["date"] <= end):
                return False
        medicine = self.medicine_filter.currentData()
        if medicine and row["medicine"] != medicine:
            return False
        tx_type = self.type_filter.currentData()
        if tx_type and row["type"] != tx_type:
            return False
        text = self.search.text().strip().casefold()
        if text and text not in row["patient_id"].casefold() \
                and text not in row["prescriber"].casefold():
            return False
        return True

    def _apply_filters(self, *_):
        self.proxy.refilter()
        self.count_label.setText(
            f"Showing {self.proxy.rowCount():,} of {self.model.rowCount():,} entries")

    def _clear_filters(self):
        self.use_dates.setChecked(False)
        self.medicine_filter.setCurrentIndex(0)
        self.type_filter.setCurrentIndex(0)
        self.search.clear()

    # --- undo ---------------------------------------------------------------
    def undo_last(self):
        rows = logic.last_entry(self.conn)
        if not rows:
            show_info(self, "There is nothing to undo.", title="Undo")
            return
        first = rows[0]
        details = "\n".join(
            f"  - {r['type']}: {r['quantity']:,} {r['unit']} of {r['medicine']}, "
            f"batch {r['batch_no']}" for r in rows)
        extra = (f"\nPatient: {first['patient_id'] or '-'}   Prescriber: {first['prescriber'] or '-'}"
                 if first["type"] == logic.DISPENSED else "")
        if not ask_yes_no(
                self,
                f"The most recent entry (saved {first['entered_at']}, dated {first['date']}):\n\n"
                f"{details}{extra}\n\nDelete this entry permanently?",
                title="Undo last entry", yes_text="Delete entry", no_text="Cancel"):
            return
        try:
            logic.undo_last_entry(self.conn, expected_group=first["entry_group"])
        except logic.ValidationError as exc:
            show_error(self, str(exc))
            return
        show_info(self, "The entry was deleted.", title="Undone")
        self.data_changed.emit()

    # --- export -------------------------------------------------------------
    def export(self, kind: str):
        rows = self.proxy.visible_rows()
        if not rows:
            show_info(self, "There are no rows to export with the current filters.", "Export")
            return
        suggested = f"medtracker_log_{date.today().isoformat()}.{kind}"
        file_filter = "Excel workbook (*.xlsx)" if kind == "xlsx" else "CSV file (*.csv)"
        path, _ = QFileDialog.getSaveFileName(self, "Export log", suggested, file_filter)
        if not path:
            return
        if not path.lower().endswith(f".{kind}"):
            path += f".{kind}"
        columns = [(c.key, c.header) for c in LOG_COLUMNS]
        try:
            saved = exports.export_table(rows, columns, path)
        except PermissionError:
            show_error(self, "Could not save the file. Is it open in Excel? Close it and try again.")
            return
        show_info(self, f"Exported {len(rows):,} rows to:\n{saved}", title="Export complete")
