"""ui/units.py - Units: the list of choices shown in every Unit drop-down."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

import db
import logic
from ui import theme
from ui.widgets import ask_yes_no, dialog_header, make_button, show_error, style_dialog_buttons


def _count(n: int) -> str:
    return f"{n:,} medicine" if n == 1 else f"{n:,} medicines"


class UnitsDialog(QDialog):
    """Add units to the list, or take ones you don't use off it."""

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.changed = False
        self.setWindowTitle("Units")
        self.setMinimumSize(440, 520)

        self.new_edit = QLineEdit()
        self.new_edit.setPlaceholderText("e.g. strips, boxes of 100, rolls")
        self.new_edit.setMaxLength(logic.MAX_UNIT_LENGTH)
        self.new_edit.returnPressed.connect(self.add)
        add_btn = make_button("Add unit", "primary")
        add_btn.clicked.connect(self.add)
        add_row = QHBoxLayout()
        add_row.addWidget(self.new_edit, 1)
        add_row.addWidget(add_btn)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.currentRowChanged.connect(self._update_buttons)
        self.remove_btn = make_button("Remove from list", "danger")
        self.remove_btn.clicked.connect(self.remove)
        note = QLabel("A unit that any medicine uses can't be removed. Units in use are "
                      "marked in the list.")
        note.setObjectName("muted")
        note.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        style_dialog_buttons(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(dialog_header("Units", "The choices in every Unit drop-down",
                                       "\U0001F4CF", theme.PRIMARY))
        layout.addLayout(add_row)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.remove_btn, 0, Qt.AlignLeft)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self._load()
        self.new_edit.setFocus()

    def _load(self, select: str | None = None):
        self.list.clear()
        names = logic.unit_names(self.conn)
        for name in names:
            in_use = db.medicines_using_unit(self.conn, name)
            item = QListWidgetItem(f"{name}    ({_count(in_use)})" if in_use else name)
            item.setData(Qt.UserRole, name)
            item.setData(Qt.UserRole + 1, in_use)
            self.list.addItem(item)
        if select in names:
            self.list.setCurrentRow(names.index(select))
        self._update_buttons()

    def _update_buttons(self, *_):
        item = self.list.currentItem()
        in_use = item.data(Qt.UserRole + 1) if item else 0
        self.remove_btn.setEnabled(item is not None and not in_use)
        self.remove_btn.setToolTip(
            f"Used by {_count(in_use)}, so it can't be removed" if in_use else "")

    def add(self):
        try:
            name = logic.add_unit(self.conn, self.new_edit.text())
        except logic.ValidationError as exc:
            show_error(self, str(exc))
            return
        self.changed = True
        self.new_edit.clear()
        self._load(select=name)

    def remove(self):
        item = self.list.currentItem()
        if item is None:
            return
        name = item.data(Qt.UserRole)
        if not ask_yes_no(self, f"Remove '{name}' from the list?", title="Remove unit",
                          yes_text="Remove", no_text="Cancel"):
            return
        try:
            logic.remove_unit(self.conn, name)
        except logic.ValidationError as exc:      # e.g. a medicine was given it meanwhile
            show_error(self, str(exc))
            self._load(select=name)
            return
        self.changed = True
        self._load()


def fill_unit_combo(combo: QComboBox, conn, keep: str | None = None) -> None:
    """Load the unit list into an editable drop-down, keeping the current choice if possible."""
    keep = keep if keep is not None else combo.currentText()
    names = logic.unit_names(conn)
    combo.clear()
    combo.addItems(names)
    if keep:
        combo.setCurrentText(keep)
    elif "tablets" in names:
        combo.setCurrentText("tablets")


def unit_picker(conn, parent: QWidget) -> tuple[QWidget, QComboBox]:
    """An editable Unit drop-down with a "Manage units" link beside it."""
    combo = QComboBox()
    combo.setEditable(True)
    combo.setMinimumWidth(180)
    fill_unit_combo(combo, conn, keep="")
    manage = QPushButton("Manage units")
    manage.setProperty("kind", "link")
    manage.setCursor(Qt.PointingHandCursor)
    manage.setToolTip("Add or remove units in this list")

    def open_units():
        dialog = UnitsDialog(conn, parent)
        dialog.exec()
        if dialog.changed:
            fill_unit_combo(combo, conn)

    manage.clicked.connect(open_units)
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    row.addWidget(combo, 1)
    row.addWidget(manage)
    return box, combo
