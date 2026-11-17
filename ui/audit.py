"""ui/audit.py - Audit Log: every edit, delete and undo of a log entry (read-only)."""

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QWidget

import exports
import logic
from ui.models import Column, RecordTableModel, TableProxy, make_table, use_pills
from ui.widgets import (
    Card, hint_label, make_button, page_header, page_layout, show_error, show_info,
)

AUDIT_COLUMNS = [
    Column("changed_at", "When"),
    Column("changed_by", "Changed by"),
    Column("action", "Action", "center"),
    Column("medicine", "Medicine"),
    Column("tx_type", "Entry type", "center"),
    Column("change", "Quantity", "right"),
    Column("unit", "Unit"),
    Column("reason", "Reason"),
    Column("tx_date", "Entry date"),
    Column("batch_no", "Batch No"),
    Column("patient_id", "Patient ID"),
    Column("prescriber", "Prescriber"),
    Column("entered_at", "Originally entered"),
    Column("entered_by", "Entered by"),
]


class AuditPage(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn

        self.model = RecordTableModel(AUDIT_COLUMNS)
        self.proxy = TableProxy()
        self.proxy.filter_fn = self._row_matches
        self.view = make_table(self.model, self.proxy)
        self.view.setEditTriggers(self.view.EditTrigger.NoEditTriggers)
        use_pills(self.view, AUDIT_COLUMNS, "action", "tx_type")

        self.action_filter = QComboBox()
        self.action_filter.addItem("All changes", None)
        self.action_filter.addItem("Edited", logic.AUDIT_EDITED)
        self.action_filter.addItem("Deleted", logic.AUDIT_DELETED)
        self.action_filter.addItem("Undone", logic.AUDIT_UNDONE)
        self.search = QLineEdit()
        self.search.setPlaceholderText("\U0001F50D  Search medicine, person, reason...")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(260)
        self.count_label = hint_label("")
        self.count_label.setWordWrap(False)

        card = Card()
        filters = QHBoxLayout()
        filters.addWidget(self.action_filter)
        filters.addWidget(self.search, 1)
        card.body.addLayout(filters)
        card.body.addWidget(self.view, 1)
        card.body.addWidget(self.count_label)

        excel_btn = make_button("Export Excel", icon_text="\U0001F4C4")
        csv_btn = make_button("Export CSV", icon_text="\U0001F4C4")
        layout = page_layout(self)
        layout.addWidget(page_header(
            "Audit Log", "Every edit, delete and undo of a log entry, newest first",
            excel_btn, csv_btn))
        layout.addWidget(card, 1)

        self.action_filter.currentIndexChanged.connect(self._apply_filters)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.search.textChanged.connect(self._apply_filters)
        excel_btn.clicked.connect(lambda: self.export("xlsx"))
        csv_btn.clicked.connect(lambda: self.export("csv"))

    def refresh(self):
        self.model.set_rows(logic.audit_rows(self.conn))
        self._apply_filters()

    def _row_matches(self, row: dict) -> bool:
        action = self.action_filter.currentData()
        return not action or row["action"] == action

    def _apply_filters(self, *_):
        self.proxy.refilter()
        self.count_label.setText(
            f"Showing {self.proxy.rowCount():,} of {self.model.rowCount():,} changes")

    def export(self, kind: str):
        rows = self.proxy.visible_rows()
        if not rows:
            show_info(self, "There are no rows to export with the current filters.", "Export")
            return
        suggested = f"medtracker_audit_{date.today().isoformat()}.{kind}"
        file_filter = "Excel workbook (*.xlsx)" if kind == "xlsx" else "CSV file (*.csv)"
        path, _ = QFileDialog.getSaveFileName(self, "Export audit log", suggested, file_filter)
        if not path:
            return
        if not path.lower().endswith(f".{kind}"):
            path += f".{kind}"
        columns = [(c.key, c.header) for c in AUDIT_COLUMNS]
        try:
            saved = exports.export_table(rows, columns, path)
        except PermissionError:
            show_error(self, "Could not save the file. Is it open in Excel? Close it and try again.")
            return
        show_info(self, f"Exported {len(rows):,} rows to:\n{saved}", title="Export complete")
