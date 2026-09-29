"""ui/add_stock.py - The "Add Stock" dialog (stock received)."""

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QCompleter, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel, QLineEdit,
    QSpinBox, QVBoxLayout,
)

import db
import logic
from config import COMMON_UNITS
from ui import theme
from ui.widgets import (
    dialog_header, style_dialog_buttons,
    OptionalDateEdit, SearchComboBox, ask_yes_no, make_date_edit, show_error, show_info,
    to_py_date, to_qdate,
)

MAX_QTY = 10_000_000


class AddStockDialog(QDialog):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Add Stock")
        self.setMinimumWidth(560)

        self.date_edit = make_date_edit(max_today=True)

        self.medicine_combo = SearchComboBox("Choose a medicine or type a new name")
        self.medicine_combo.set_items(db.medicine_names(conn), keep_text=False)

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, MAX_QTY)
        self.qty_spin.setGroupSeparatorShown(True)
        self.unit_label = QLabel("")

        self.batch_edit = QLineEdit()
        self.batch_edit.setPlaceholderText("Required, e.g. 00123A")
        self.batch_hint = QLabel("")
        self.batch_hint.setStyleSheet("color: #7a4500;")
        self.batch_hint.setWordWrap(True)

        self.expiry_edit = OptionalDateEdit()

        # Extra fields shown only when the medicine is new.
        self.new_box = QGroupBox("New medicine - please also enter:")
        new_form = QFormLayout(self.new_box)
        self.unit_combo = QComboBox()
        self.unit_combo.setEditable(True)
        self.unit_combo.addItems(COMMON_UNITS)
        self.reorder_spin = QSpinBox()
        self.reorder_spin.setRange(0, MAX_QTY)
        self.reorder_spin.setValue(10)
        self.reorder_spin.setToolTip("Show a LOW STOCK warning when stock falls to this level")
        new_form.addRow("Unit:", self.unit_combo)
        new_form.addRow("Reorder level:", self.reorder_spin)

        self.form = form = QFormLayout()
        form.addRow("Date received:", self.date_edit)
        form.addRow("Medicine:", self.medicine_combo)
        form.addRow("", self.new_box)
        form.addRow("Quantity:", self.qty_spin)
        form.addRow("", self.unit_label)
        form.addRow("Batch number:", self.batch_edit)
        form.addRow("", self.batch_hint)
        form.addRow("Expiry date:", self.expiry_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        style_dialog_buttons(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(dialog_header("Add Stock", "Record a delivery of medicine received", "+",
                                       theme.PRIMARY))
        layout.addLayout(form)
        form.setRowVisible(self.new_box, False)
        form.setRowVisible(self.unit_label, False)
        form.setRowVisible(self.batch_hint, False)
        layout.addWidget(buttons)

        self.medicine_combo.editTextChanged.connect(self._medicine_changed)
        self.batch_edit.textChanged.connect(self._batch_changed)

    # --- live hints ---------------------------------------------------------
    def _current_medicine(self):
        name = self.medicine_combo.text()
        return db.find_medicine(self.conn, name) if name else None

    def _medicine_changed(self, _text=None):
        med = self._current_medicine()
        is_new = med is None and bool(self.medicine_combo.text())
        self.form.setRowVisible(self.new_box, is_new)
        if med:
            stock = db.medicine_stock(self.conn, med["id"])
            self.unit_label.setText(f"Current stock: {stock:,} {med['unit']}")
        self.form.setRowVisible(self.unit_label, med is not None)
        # Offer existing batch numbers of this medicine as suggestions.
        batches = db.batch_numbers(self.conn, med["id"]) if med else []
        completer = QCompleter(batches, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.batch_edit.setCompleter(completer)
        self._batch_changed()
        self.adjustSize()

    def _batch_changed(self, _text=None):
        med = self._current_medicine()
        batch_no = self.batch_edit.text().strip()
        batch = db.find_batch(self.conn, med["id"], batch_no) if med and batch_no else None
        if batch:
            self.batch_hint.setText(
                f"Existing batch - expiry {batch['expiry_date']} "
                f"(the original expiry date is always kept).")
            self.expiry_edit.setDate(to_qdate(logic.to_date(batch["expiry_date"])))
        self.form.setRowVisible(self.batch_hint, batch is not None)

    # --- save ---------------------------------------------------------------
    def save(self):
        try:
            name = logic.require_text(self.medicine_combo.text(), "Medicine")
            batch_no = logic.require_text(self.batch_edit.text(), "Batch number")
            expiry = self.expiry_edit.value()
            if expiry is None:
                raise logic.ValidationError("Expiry date is required.")
            stock_date: date = to_py_date(self.date_edit.date())
            check = logic.check_add_stock(self.conn, stock_date, name, batch_no, expiry)

            if check.expiry_conflict:
                if not ask_yes_no(
                        self,
                        f"Batch '{batch_no}' already exists for this medicine with expiry "
                        f"date {check.existing_expiry.isoformat()}.\n\n"
                        f"The expiry date you entered ({expiry.isoformat()}) will be IGNORED "
                        f"and the original expiry date will be kept.\n\nContinue?",
                        title="Different expiry date", yes_text="Continue", no_text="Go back"):
                    return
            if check.already_expired:
                if not ask_yes_no(
                        self,
                        f"This batch expires on {check.effective_expiry.isoformat()}, which is "
                        f"on or before the date received ({stock_date.isoformat()}).\n\n"
                        f"The batch is ALREADY EXPIRED. Save it anyway?",
                        title="Expired batch", yes_text="Save anyway", no_text="Go back"):
                    return

            result = logic.add_stock(
                self.conn, stock_date, name, self.qty_spin.value(), batch_no, expiry,
                unit=self.unit_combo.currentText(), reorder_level=self.reorder_spin.value())
        except logic.ValidationError as exc:
            show_error(self, str(exc))
            return

        lines = [f"Added {result.quantity:,} {result.unit} of {result.medicine_name}",
                 f"Batch {result.batch_no} (expiry {result.expiry.isoformat()})", "",
                 f"New stock level: {result.new_stock:,} {result.unit}"]
        if result.created_medicine:
            lines.insert(0, "New medicine created.\n")
        show_info(self, "\n".join(lines), title="Stock added")
        self.accept()
