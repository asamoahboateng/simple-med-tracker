"""ui/medicine.py - The "New Medicine" dialog (adds a medicine with no stock yet)."""

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout,
)

import logic
from config import COMMON_UNITS
from ui import theme
from ui.widgets import dialog_header, show_error, show_info, style_dialog_buttons


class NewMedicineDialog(QDialog):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("New Medicine")
        self.setMinimumWidth(520)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Paracetamol 500mg")
        self.unit_combo = QComboBox()
        self.unit_combo.setEditable(True)
        self.unit_combo.addItems(COMMON_UNITS)
        self.reorder_spin = QSpinBox()
        self.reorder_spin.setRange(0, 10_000_000)
        self.reorder_spin.setValue(10)
        self.reorder_spin.setToolTip("Show a LOW STOCK warning when stock falls to this level")

        note = QLabel("The medicine starts with no stock. Use Add Stock to record deliveries.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888;")

        form = QFormLayout()
        form.addRow("Medicine name:", self.name_edit)
        form.addRow("Unit:", self.unit_combo)
        form.addRow("Reorder level:", self.reorder_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        style_dialog_buttons(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(dialog_header("New Medicine", "Add a medicine to your catalogue", "\U0001F9F4", theme.PRIMARY))
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def save(self):
        try:
            logic.create_medicine(self.conn, self.name_edit.text(), self.unit_combo.currentText(),
                                  self.reorder_spin.value())
        except logic.ValidationError as exc:
            show_error(self, str(exc))
            return
        show_info(self, f"'{self.name_edit.text().strip()}' was added.", title="Medicine added")
        self.accept()
