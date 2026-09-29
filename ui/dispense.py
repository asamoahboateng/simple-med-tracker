"""ui/dispense.py - The "Record Dispensed" dialog."""

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox,
    QSpinBox, QVBoxLayout,
)

import db
import logic
from ui import theme
from ui.widgets import (
    SearchComboBox, ask_yes_no, dialog_header, make_date_edit, show_error, style_dialog_buttons,
    to_py_date,
)

AUTOMATIC = "Automatic (earliest expiry first)"


class DispenseDialog(QDialog):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Record Dispensed")
        self.setMinimumWidth(580)

        self.date_edit = make_date_edit(max_today=True)
        self.medicine_combo = SearchComboBox("Choose a medicine")
        self.medicine_combo.set_items(db.medicine_names(conn), keep_text=False)

        self.stock_label = QLabel("Select a medicine to see available stock.")
        self.stock_label.setWordWrap(True)
        self.stock_label.setStyleSheet(self._info_style(theme.TEXT_MUTED))

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 10_000_000)
        self.qty_spin.setGroupSeparatorShown(True)

        self.batch_combo = QComboBox()
        self.batch_combo.addItem(AUTOMATIC, None)

        self.patient_edit = QLineEdit()
        self.patient_edit.setPlaceholderText("e.g. P00123")
        self.prescriber_combo = SearchComboBox("Name of prescriber")
        self.prescriber_combo.set_items(db.prescribers(conn), keep_text=False)

        form = QFormLayout()
        form.addRow("Date dispensed:", self.date_edit)
        form.addRow("Medicine:", self.medicine_combo)
        form.addRow("", self.stock_label)
        form.addRow("Quantity:", self.qty_spin)
        form.addRow("Batch:", self.batch_combo)
        form.addRow("Patient ID:", self.patient_edit)
        form.addRow("Prescriber:", self.prescriber_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        style_dialog_buttons(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(dialog_header("Record Dispensed", "Medicine given to a patient", "\U0001F48A", theme.BLUE))
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.medicine_combo.editTextChanged.connect(self._refresh_medicine)
        self.date_edit.dateChanged.connect(self._refresh_medicine)

    def _refresh_medicine(self, *_):
        """Show the stock for the selected medicine and list usable batches."""
        name = self.medicine_combo.text()
        med = db.find_medicine(self.conn, name) if name else None

        self.batch_combo.clear()
        self.batch_combo.addItem(AUTOMATIC, None)
        if med is None:
            self.stock_label.setText(
                "Select a medicine to see available stock." if not name
                else "Unknown medicine - add stock for it first.")
            self.stock_label.setStyleSheet(self._info_style(theme.TEXT_MUTED))
            return

        on_date = to_py_date(self.date_edit.date())
        stock = db.medicine_stock(self.conn, med["id"])
        usable = logic.dispensable_batches(self.conn, med["name"], on_date)
        usable_total = sum(b.remaining for b in usable)
        for b in usable:
            self.batch_combo.addItem(
                f"{b.batch_no}  -  expires {b.expiry.isoformat()}  -  {b.remaining:,} left",
                b.batch_no)

        text = f"Available stock: {stock:,} {med['unit']}"
        if usable_total != stock:
            text += f"  (usable, not expired: {usable_total:,})"
        text += f"   |   Reorder level: {med['reorder_level']:,}"
        status = logic.stock_status(usable_total, med["reorder_level"])
        colour = {"OK": theme.GREEN, "LOW": theme.AMBER, "OUT OF STOCK": theme.RED}[status]
        self.stock_label.setText(text)
        self.stock_label.setStyleSheet(self._info_style(colour))

    @staticmethod
    def _info_style(colour: str) -> str:
        """Soft coloured box for the available-stock line."""
        return (f"background: {theme.tint(colour, 0.12)}; color: {colour}; font-weight: 700;"
                f" border-radius: 8px; padding: 8px 10px;")

    def save(self):
        patient = self.patient_edit.text().strip()
        prescriber = self.prescriber_combo.text()
        missing = [label for label, value in (("Patient ID", patient), ("Prescriber", prescriber))
                   if not value]
        if missing and not ask_yes_no(
                self, f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} blank.\n\n"
                      f"Save this entry anyway?",
                title="Missing details", yes_text="Save anyway", no_text="Go back"):
            return

        try:
            result = logic.dispense(
                self.conn, to_py_date(self.date_edit.date()), self.medicine_combo.text(),
                self.qty_spin.value(), batch_no=self.batch_combo.currentData(),
                patient_id=patient, prescriber=prescriber)
        except logic.ValidationError as exc:
            show_error(self, str(exc), title="Cannot save")
            return

        used = "\n".join(f"  - Batch {a.batch_no} (exp {a.expiry.isoformat()}): {a.quantity:,}"
                         for a in result.allocations)
        message = (f"Dispensed {result.quantity:,} {result.unit} of {result.medicine_name}.\n\n"
                   f"Batches used:\n{used}\n\n"
                   f"Remaining stock: {result.remaining_stock:,} {result.unit}")
        if result.low_stock:
            level = "OUT OF STOCK" if result.remaining_stock <= 0 else "LOW STOCK"
            QMessageBox.warning(
                self, level,
                f"{message}\n\n⚠ {level}: {result.medicine_name} is at or below its "
                f"reorder level ({result.reorder_level:,}). Please reorder.")
        else:
            QMessageBox.information(self, "Saved", message)
        self.accept()
