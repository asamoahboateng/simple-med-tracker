"""ui/log.py - Dispensing Log: every transaction (stock in, dispensed, removed), with filters,
quantity edits, deletes, undo and export."""

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QWidget,
)

import exports
import logic
from ui.edit_entry import DeleteEntryDialog, EditEntryDialog
from ui.models import Column, RecordTableModel, TableProxy, int_fmt, make_table, use_pills
from ui.responsive import FlowLayout
from ui.widgets import (
    Card, SearchComboBox, ask_yes_no, hint_label, make_button, make_date_edit, page_header,
    page_layout, show_error, show_info, to_py_date,
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
    Column("reason", "Reason removed"),
    Column("balance_after", "Balance After", "right", int_fmt),
    Column("entered_at", "Entered At"),
    Column("entered_by", "Entered By"),
]


class LogPage(QWidget):
    data_changed = Signal()

    def __init__(self, conn, parent=None, user_name: str = ""):
        super().__init__(parent)
        self.conn = conn
        self.user_name = user_name   # recorded in the audit log for edits and deletes

        self.model = RecordTableModel(LOG_COLUMNS)
        self.proxy = TableProxy()
        self.proxy.filter_fn = self._row_matches
        self.view = make_table(self.model, self.proxy)
        self.view.sortByColumn(0, Qt.DescendingOrder)
        use_pills(self.view, LOG_COLUMNS, "type")
        self.view.doubleClicked.connect(self.edit_entry)

        # --- filters ---
        self.use_dates = QCheckBox("Dates from")
        first_of_month = date.today().replace(day=1)
        self.from_date = make_date_edit(first_of_month)
        self.to_date = make_date_edit()
        # Type to search: the list narrows to medicines containing the text, and the log
        # shows every medicine whose name contains it (empty = all medicines).
        self.medicine_filter = SearchComboBox("All medicines (type to search)")
        self.medicine_filter.setMinimumWidth(240)
        self.type_filter = QComboBox()
        self.type_filter.addItem("All types", None)
        self.type_filter.addItem("Stock in", logic.STOCK_IN)
        self.type_filter.addItem("Dispensed", logic.DISPENSED)
        self.type_filter.addItem("Removed", logic.REMOVED)
        self.search = QLineEdit()
        self.search.setPlaceholderText("\U0001F50D  Search patient ID, prescriber or reason")
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
        edit_btn = make_button("Edit entry", icon_text="\u270E")
        delete_btn = make_button("Delete entry", "danger", icon_text="\u2716")
        undo_btn = make_button("Undo last entry", "danger", icon_text="\u21b6")
        excel_btn = make_button("Export Excel", icon_text="\U0001F4C4")
        csv_btn = make_button("Export CSV", icon_text="\U0001F4C4")
        self.count_label = hint_label("")
        self.count_label.setWordWrap(False)
        actions = QHBoxLayout()
        actions.addWidget(self.count_label)
        edit_hint = hint_label("   Double-click an entry to correct its quantity")
        edit_hint.setWordWrap(False)
        actions.addWidget(edit_hint)
        actions.addStretch()
        actions.addWidget(edit_btn)
        actions.addWidget(delete_btn)
        actions.addWidget(undo_btn)

        layout = page_layout(self)
        layout.addWidget(page_header("Dispensing Log", "Every stock movement, newest first",
                                     excel_btn, csv_btn))
        layout.addWidget(filter_card)
        layout.addWidget(self.view, 1)
        layout.addLayout(actions)

        for widget_signal in (self.use_dates.toggled, self.from_date.dateChanged,
                              self.to_date.dateChanged, self.medicine_filter.editTextChanged,
                              self.type_filter.currentIndexChanged, self.search.textChanged):
            widget_signal.connect(self._apply_filters)
        self.use_dates.toggled.connect(self._update_date_enabled)
        clear_btn.clicked.connect(self._clear_filters)
        edit_btn.clicked.connect(self.edit_entry)
        delete_btn.clicked.connect(self.delete_entry)
        undo_btn.clicked.connect(self.undo_last)
        excel_btn.clicked.connect(lambda: self.export("xlsx"))
        csv_btn.clicked.connect(lambda: self.export("csv"))
        self._update_date_enabled()

    # --- data ---------------------------------------------------------------
    def refresh(self):
        self.model.set_rows(logic.log_rows(self.conn))
        self.medicine_filter.set_items(
            sorted({r["medicine"] for r in self.model.rows}, key=str.casefold))
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
        medicine = self.medicine_filter.text().casefold()
        if medicine and medicine not in row["medicine"].casefold():
            return False
        tx_type = self.type_filter.currentData()
        if tx_type and row["type"] != tx_type:
            return False
        text = self.search.text().strip().casefold()
        if text and not any(text in row[key].casefold()
                            for key in ("patient_id", "prescriber", "reason")):
            return False
        return True

    def _apply_filters(self, *_):
        self.proxy.refilter()
        self.count_label.setText(
            f"Showing {self.proxy.rowCount():,} of {self.model.rowCount():,} entries")

    def _clear_filters(self):
        self.use_dates.setChecked(False)
        self.medicine_filter.setEditText("")
        self.type_filter.setCurrentIndex(0)
        self.search.clear()

    # --- edit ---------------------------------------------------------------
    def _selected_row(self) -> dict | None:
        index = self.view.currentIndex()
        if not index.isValid():
            return None
        return self.model.row_dict(self.proxy.mapToSource(index).row())

    def edit_entry(self, *_):
        row = self._selected_row()
        if row is None:
            show_info(self, "Select an entry in the log first.", title="Edit entry")
            return
        if EditEntryDialog(self.conn, row, self, changed_by=self.user_name).exec():
            show_info(self, "The entry was corrected.", title="Saved")
            self.data_changed.emit()

    def delete_entry(self, *_):
        row = self._selected_row()
        if row is None:
            show_info(self, "Select an entry in the log first.", title="Delete entry")
            return
        if DeleteEntryDialog(self.conn, row, self, changed_by=self.user_name).exec():
            show_info(self, "The entry was deleted.", title="Deleted")
            self.data_changed.emit()

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
                 if first["type"] == logic.DISPENSED
                 else f"\nReason: {first['reason']}" if first["type"] == logic.REMOVED else "")
        if not ask_yes_no(
                self,
                f"The most recent entry (saved {first['entered_at']}, dated {first['date']}):\n\n"
                f"{details}{extra}\n\nDelete this entry permanently?",
                title="Undo last entry", yes_text="Delete entry", no_text="Cancel"):
            return
        try:
            logic.undo_last_entry(self.conn, expected_group=first["entry_group"],
                                  changed_by=self.user_name)
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
