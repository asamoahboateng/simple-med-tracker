"""ui/edit_entry.py - The "Correct Entry" and "Delete Entry" dialogs for one log row."""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout,
)

import db
import logic
from ui import theme
from ui.widgets import dialog_header, show_error, style_dialog_buttons

DELETE_WORD = "DELETE"


def entry_details(row: dict) -> QFormLayout:
    """Read-only form describing one log row."""
    form = QFormLayout()
    form.addRow("Medicine:", QLabel(row["medicine"]))
    form.addRow("Type:", QLabel(logic.TYPE_NAMES[row["type"]]))
    form.addRow("Date:", QLabel(row["date"]))
    form.addRow("Batch:", QLabel(f"{row['batch_no']}  (expires {row['expiry']})"))
    if row["type"] == logic.DISPENSED:
        form.addRow("Patient ID:", QLabel(row["patient_id"] or "-"))
        form.addRow("Prescriber:", QLabel(row["prescriber"] or "-"))
    if row["type"] == logic.REMOVED:
        form.addRow("Reason removed:", QLabel(row["reason"] or "-"))
    form.addRow("Entered:", QLabel(f"{row['entered_at']} by {row['entered_by'] or '-'}"))
    form.addRow("Recorded quantity:", QLabel(f"{int(row['quantity']):,} {row['unit']}"))
    return form


def reason_edit() -> QLineEdit:
    edit = QLineEdit()
    edit.setPlaceholderText("Optional, e.g. Wrong quantity typed")
    edit.setMaxLength(200)
    edit.setToolTip("Saved in the audit log with this change")
    return edit


def _info_style(colour: str) -> str:
    return (f"background: {theme.tint(colour, 0.12)}; color: {colour}; font-weight: 700;"
            f" border-radius: 8px; padding: 8px 10px;")


class EditEntryDialog(QDialog):
    def __init__(self, conn, row: dict, parent=None, changed_by: str = ""):
        super().__init__(parent)
        self.conn = conn
        self.row = row
        self.changed_by = changed_by
        self.stock_in = row["type"] == logic.STOCK_IN
        self.stock_now = db.medicine_stock(conn, row["medicine_id"])
        self.setWindowTitle("Correct Entry")
        self.setMinimumWidth(520)

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 10_000_000)
        self.qty_spin.setGroupSeparatorShown(True)
        self.qty_spin.setValue(int(row["quantity"]))
        self.qty_spin.setSuffix(f"  {row['unit']}")

        self.stock_label = QLabel()
        self.stock_label.setWordWrap(True)

        form = entry_details(row)
        form.addRow("Correct quantity:", self.qty_spin)
        form.addRow("", self.stock_label)
        self.reason_edit = reason_edit()
        form.addRow("Reason:", self.reason_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        style_dialog_buttons(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(dialog_header("Correct Entry", "Fix the quantity of a logged entry",
                                       "✎", theme.PRIMARY))
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.qty_spin.valueChanged.connect(self._update_stock_label)
        self._update_stock_label()
        self.qty_spin.selectAll()

    def stock_after(self) -> int:
        change = self.qty_spin.value() - int(self.row["quantity"])
        return self.stock_now + (change if self.stock_in else -change)

    def _update_stock_label(self, *_):
        unit = self.row["unit"]
        after = self.stock_after()
        if after == self.stock_now:
            text, colour = f"Current stock: {self.stock_now:,} {unit} (no change)", theme.TEXT_MUTED
        else:
            text = f"Current stock will go from {self.stock_now:,} to {after:,} {unit}"
            colour = theme.RED if after < 0 else theme.PRIMARY
        self.stock_label.setText(text)
        self.stock_label.setStyleSheet(_info_style(colour))

    def save(self):
        if self.qty_spin.value() == int(self.row["quantity"]):
            self.reject()
            return
        try:
            logic.edit_quantity(self.conn, self.row["id"], self.qty_spin.value(),
                                changed_by=self.changed_by, reason=self.reason_edit.text())
        except logic.ValidationError as exc:
            show_error(self, str(exc))
            return
        self.accept()


class DeleteEntryDialog(QDialog):
    """Permanently deletes one log row once the user types DELETE."""

    def __init__(self, conn, row: dict, parent=None, changed_by: str = ""):
        super().__init__(parent)
        self.conn = conn
        self.row = row
        self.changed_by = changed_by
        self.setWindowTitle("Delete Entry")
        self.setMinimumWidth(520)

        quantity = int(row["quantity"])
        stock_now = db.medicine_stock(conn, row["medicine_id"])
        stock_after = stock_now + (-quantity if row["type"] == logic.STOCK_IN else quantity)
        effect = QLabel(f"Current stock will go from {stock_now:,} to {stock_after:,} {row['unit']}."
                        f"\nThis can't be undone.")
        effect.setWordWrap(True)
        effect.setStyleSheet(_info_style(theme.RED))

        self.confirm_edit = QLineEdit()
        self.confirm_edit.setPlaceholderText(DELETE_WORD)

        form = entry_details(row)
        form.addRow("", effect)
        self.reason_edit = reason_edit()
        form.addRow("Reason:", self.reason_edit)
        form.addRow(f"Type {DELETE_WORD} to confirm:", self.confirm_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.delete_btn = buttons.addButton("Delete entry", QDialogButtonBox.DestructiveRole)
        self.delete_btn.setProperty("kind", "danger")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self.delete)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(dialog_header("Delete Entry", "Remove this entry from the log for good",
                                       "\u2716", theme.RED))
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.confirm_edit.textChanged.connect(
            lambda text: self.delete_btn.setEnabled(self._confirmed()))
        self.confirm_edit.setFocus()

    def _confirmed(self) -> bool:
        return self.confirm_edit.text().strip().upper() == DELETE_WORD

    def delete(self):
        if not self._confirmed():
            return
        try:
            logic.delete_entry(self.conn, self.row["id"], changed_by=self.changed_by,
                               reason=self.reason_edit.text())
        except logic.ValidationError as exc:
            show_error(self, str(exc))
            return
        self.accept()
