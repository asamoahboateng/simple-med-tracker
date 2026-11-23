"""ui/medicine.py - The "New Medicine" and "Edit Medicine" dialogs (edit can also delete)."""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout,
)

import logic
from ui import theme
from ui.units import unit_picker
from ui.widgets import (
    ask_yes_no, dialog_header, make_button, show_error, show_info, style_dialog_buttons,
)


class NewMedicineDialog(QDialog):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("New Medicine")
        self.setMinimumWidth(520)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Paracetamol 500mg")
        unit_box, self.unit_combo = unit_picker(conn, self)
        self.reorder_spin = QSpinBox()
        self.reorder_spin.setRange(0, 10_000_000)
        self.reorder_spin.setValue(10)
        self.reorder_spin.setToolTip("Show a LOW STOCK warning when stock falls to this level")
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Optional, e.g. Store below 25\u00b0C")
        self.note_edit.setMaxLength(500)

        note = QLabel("The medicine starts with no stock. Use Add Stock to record deliveries.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888;")

        form = QFormLayout()
        form.addRow("Medicine name:", self.name_edit)
        form.addRow("Unit:", unit_box)
        form.addRow("Reorder level:", self.reorder_spin)
        form.addRow("Note:", self.note_edit)

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
                                  self.reorder_spin.value(), self.note_edit.text())
        except logic.ValidationError as exc:
            show_error(self, str(exc))
            return
        show_info(self, f"'{self.name_edit.text().strip()}' was added.", title="Medicine added")
        self.accept()


class EditMedicineDialog(QDialog):
    """Edit a medicine's name, unit, reorder level and note."""

    def __init__(self, conn, medicine: dict, parent=None, can_delete=lambda: False):
        super().__init__(parent)
        self.conn = conn
        self.medicine = medicine
        self.can_delete = can_delete   # whether the signed-in user may delete medicines (asked fresh)
        self.setWindowTitle("Edit Medicine")
        self.setMinimumWidth(520)

        self.name_edit = QLineEdit(medicine["name"])
        unit_box, self.unit_combo = unit_picker(conn, self)
        self.unit_combo.setCurrentText(medicine["unit"])
        self.reorder_spin = QSpinBox()
        self.reorder_spin.setRange(0, 10_000_000)
        self.reorder_spin.setGroupSeparatorShown(True)
        self.reorder_spin.setValue(int(medicine["reorder_level"]))
        self.reorder_spin.setToolTip("Show a LOW STOCK warning when stock falls to this level")
        self.note_edit = QLineEdit(medicine["note"] or "")
        self.note_edit.setPlaceholderText("Optional, e.g. Store below 25°C")
        self.note_edit.setMaxLength(500)

        form = QFormLayout()
        form.addRow("Medicine name:", self.name_edit)
        form.addRow("Unit:", unit_box)
        form.addRow("Reorder level:", self.reorder_spin)
        form.addRow("Note:", self.note_edit)
        form.addRow("Current stock:", QLabel(f"{int(medicine['stock']):,} {medicine['unit']}"))

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        # Only a medicine with no stock and nothing in the log can go (e.g. added by mistake).
        self.delete_button = make_button("Delete medicine", "danger")
        self.delete_button.clicked.connect(self.delete_medicine)
        if logic.can_delete_medicine(conn, medicine["id"]):
            self.delete_button.setToolTip("Delete this medicine (it has no stock and nothing in the log)")
        else:
            self.delete_button.setEnabled(False)
            self.delete_button.setToolTip("A medicine can only be deleted when it has no stock and "
                                          "nothing in the log.")
        self.delete_button.setVisible(can_delete())   # only for those with the permission
        button_row = QHBoxLayout()                 # Delete on its own at the left, away from Save
        button_row.addWidget(self.delete_button)
        button_row.addStretch(1)
        button_row.addWidget(buttons)

        style_dialog_buttons(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(dialog_header("Edit Medicine", "Change the name, unit, reorder level or note",
                                       "✎", theme.PRIMARY))
        layout.addLayout(form)
        layout.addLayout(button_row)

    def save(self):
        try:
            logic.edit_medicine(self.conn, self.medicine["id"], self.name_edit.text(),
                                self.unit_combo.currentText(), self.reorder_spin.value(),
                                self.note_edit.text())
        except logic.ValidationError as exc:
            show_error(self, str(exc))
            return
        self.accept()

    def delete_medicine(self):
        name = self.medicine["name"]
        if not self.can_delete():
            show_error(self, "You no longer have permission to delete medicines.")
            return
        if not ask_yes_no(self, f"Delete '{name}'?\n\nIt has no stock and nothing in the log. "
                          f"This cannot be undone.", title="Delete medicine",
                          yes_text="Delete", no_text="Cancel"):
            return
        try:
            logic.delete_medicine(self.conn, self.medicine["id"])
        except logic.ValidationError as exc:
            show_error(self, str(exc))
            return
        show_info(self, f"'{name}' was deleted.", title="Medicine deleted")
        self.accept()
