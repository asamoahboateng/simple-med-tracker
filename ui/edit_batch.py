"""ui/edit_batch.py - The "Edit Batch" dialog (batch number, expiry and quantity received)."""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout,
)

import logic
from ui import theme
from ui.edit_entry import reason_edit
from ui.widgets import (
    dialog_header, make_date_edit, show_error, style_dialog_buttons, to_py_date,
)


class EditBatchDialog(QDialog):
    def __init__(self, conn, batch: dict, parent=None, changed_by: str = ""):
        super().__init__(parent)
        self.conn = conn
        self.batch = batch
        self.changed_by = changed_by
        self.setWindowTitle("Edit Batch")
        self.setMinimumWidth(520)
        unit = batch["unit"]
        out = int(batch["dispensed"]) + int(batch["removed"])

        self.batch_edit = QLineEdit(batch["batch_no"])
        self.expiry_edit = make_date_edit(logic.to_date(batch["expiry"]))

        # The received quantity is one delivery's entry, so it can only be
        # changed here when the batch came in a single delivery.
        self.single_delivery = int(batch["deliveries"]) == 1
        self.received_spin = QSpinBox()
        self.received_spin.setRange(1, 10_000_000)
        self.received_spin.setGroupSeparatorShown(True)
        self.received_spin.setSuffix(f"  {unit}")
        self.received_spin.setValue(int(batch["received"]))
        self.received_spin.setEnabled(self.single_delivery)
        self.remaining_label = QLabel()
        self.remaining_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Medicine:", QLabel(batch["medicine"]))
        form.addRow("Batch number:", self.batch_edit)
        form.addRow("Expiry date:", self.expiry_edit)
        form.addRow("Quantity received:", self.received_spin)
        if not self.single_delivery:
            note = QLabel(f"Received in {batch['deliveries']} deliveries. To change a quantity, "
                          f"double-click that delivery in the log.")
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            form.addRow("", note)
        form.addRow("Dispensed / removed:",
                    QLabel(f"{int(batch['dispensed']):,} / {int(batch['removed']):,} {unit}"))
        form.addRow("", self.remaining_label)
        self.reason_edit = reason_edit()
        self.reason_edit.setToolTip("Saved in the audit log if the quantity received changes")
        form.addRow("Reason:", self.reason_edit)
        self.out = out

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        style_dialog_buttons(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(dialog_header("Edit Batch", "Correct the batch number, expiry or quantity received",
                                       "✎", theme.PRIMARY))
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.received_spin.valueChanged.connect(self._update_remaining)
        self._update_remaining()

    def _update_remaining(self, *_):
        remaining = self.received_spin.value() - self.out
        colour = theme.RED if remaining < 0 else theme.PRIMARY
        self.remaining_label.setText(f"Remaining in this batch: {remaining:,} {self.batch['unit']}")
        self.remaining_label.setStyleSheet(
            f"background: {theme.tint(colour, 0.12)}; color: {colour}; font-weight: 700;"
            f" border-radius: 8px; padding: 8px 10px;")

    def save(self):
        received = self.received_spin.value()
        changed_received = self.single_delivery and received != int(self.batch["received"])
        try:
            logic.edit_batch(
                self.conn, self.batch["id"], self.batch_edit.text(),
                to_py_date(self.expiry_edit.date()),
                received=received if changed_received else None,
                changed_by=self.changed_by, reason=self.reason_edit.text())
        except logic.ValidationError as exc:
            show_error(self, str(exc))
            return
        self.accept()
