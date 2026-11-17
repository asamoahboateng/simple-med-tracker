"""ui/remove_stock.py - The "Remove Stock" dialog (expired, recalled, damaged... stock)."""

from datetime import date

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QMessageBox, QSpinBox, QVBoxLayout,
)

import db
import logic
from ui import theme
from ui.widgets import (
    SearchComboBox, dialog_header, make_date_edit, show_error, style_dialog_buttons, to_py_date,
)

AUTOMATIC = "Automatic (earliest expiry first, expired included)"


class RemoveStockDialog(QDialog):
    def __init__(self, conn, parent=None, entered_by: str = ""):
        super().__init__(parent)
        self.conn = conn
        self.entered_by = entered_by
        self.setWindowTitle("Remove Stock")
        self.setMinimumWidth(600)

        self.date_edit = make_date_edit(max_today=True)
        self.medicine_combo = SearchComboBox("Choose a medicine")
        self.medicine_combo.set_items(db.medicine_names(conn), keep_text=False)

        self.stock_label = QLabel("Select a medicine to see its stock and batches.")
        self.stock_label.setWordWrap(True)
        self.stock_label.setStyleSheet(_info_style(theme.TEXT_MUTED))

        self.batch_combo = QComboBox()
        self.batch_combo.addItem(AUTOMATIC, None)
        self.batch_combo.setToolTip("Optional: choose the batch being removed")

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 10_000_000)
        self.qty_spin.setGroupSeparatorShown(True)

        self.reason_combo = SearchComboBox("Why is this stock being removed?")
        self.reason_combo.set_items(logic.REMOVAL_REASONS, keep_text=False)
        self.reason_combo.setEditText(logic.REMOVAL_REASONS[0])

        form = QFormLayout()
        form.addRow("Date removed:", self.date_edit)
        form.addRow("Medicine:", self.medicine_combo)
        form.addRow("", self.stock_label)
        form.addRow("Batch (optional):", self.batch_combo)
        form.addRow("Quantity:", self.qty_spin)
        form.addRow("Reason:", self.reason_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        style_dialog_buttons(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(dialog_header("Remove Stock", "Take out expired, recalled or damaged stock",
                                       "−", theme.RED))
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.medicine_combo.editTextChanged.connect(self._refresh_medicine)
        self.batch_combo.currentIndexChanged.connect(self._batch_chosen)

    def _refresh_medicine(self, *_):
        """Show the medicine's stock and list every batch that still has stock."""
        name = self.medicine_combo.text()
        med = db.find_medicine(self.conn, name) if name else None

        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        self.batch_combo.addItem(AUTOMATIC, None)
        if med is None:
            self.batch_combo.blockSignals(False)
            self.stock_label.setText("Select a medicine to see its stock and batches." if not name
                                     else "Unknown medicine.")
            self.stock_label.setStyleSheet(_info_style(theme.TEXT_MUTED))
            return

        today = date.today()
        batches = logic.batches_with_stock(self.conn, med["name"])
        for b in batches:
            expired = "  -  EXPIRED" if logic.is_expired_on(b.expiry, today) else ""
            self.batch_combo.addItem(
                f"{b.batch_no}  -  expires {b.expiry.isoformat()}  -  {b.remaining:,} left{expired}",
                b.batch_no)
        self.batch_combo.blockSignals(False)

        stock = db.medicine_stock(self.conn, med["id"])
        expired_total = sum(b.remaining for b in batches if logic.is_expired_on(b.expiry, today))
        text = f"In stock: {stock:,} {med['unit']} in {len(batches)} batch{'es' if len(batches) != 1 else ''}"
        if expired_total:
            text += f"   |   Expired: {expired_total:,}"
        self.stock_label.setText(text)
        self.stock_label.setStyleSheet(_info_style(theme.AMBER if expired_total else theme.GREEN))

    def _batch_chosen(self, *_):
        """Choosing a batch fills in everything left in it (the usual case for a recall)."""
        batch_no = self.batch_combo.currentData()
        if batch_no:
            batch = next((b for b in logic.batches_with_stock(self.conn, self.medicine_combo.text())
                          if b.batch_no == batch_no), None)
            if batch is not None:
                self.qty_spin.setValue(batch.remaining)

    def save(self):
        try:
            result = logic.remove_stock(
                self.conn, to_py_date(self.date_edit.date()), self.medicine_combo.text(),
                self.qty_spin.value(), self.reason_combo.text(),
                batch_no=self.batch_combo.currentData(), entered_by=self.entered_by)
        except logic.ValidationError as exc:
            show_error(self, str(exc), title="Cannot save")
            return

        used = "\n".join(f"  - Batch {a.batch_no} (exp {a.expiry.isoformat()}): {a.quantity:,}"
                         for a in result.allocations)
        QMessageBox.information(
            self, "Saved",
            f"Removed {result.quantity:,} {result.unit} of {result.medicine_name} "
            f"({self.reason_combo.text()}).\n\nBatches:\n{used}\n\n"
            f"Remaining stock: {result.remaining_stock:,} {result.unit}")
        self.accept()


def _info_style(colour: str) -> str:
    return (f"background: {theme.tint(colour, 0.12)}; color: {colour}; font-weight: 700;"
            f" border-radius: 8px; padding: 8px 10px;")
