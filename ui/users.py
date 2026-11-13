"""ui/users.py - Users: approve new accounts, revoke or restore access, roles and passwords."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
    QWidget,
)

import auth
from ui.models import Column, RecordTableModel, TableProxy, make_table, use_pills
from ui.widgets import (
    Card, ask_yes_no, hint_label, make_button, page_header, page_layout, show_error, show_info,
    style_dialog_buttons,
)

USER_COLUMNS = [
    Column("full_name", "Name"),
    Column("username", "Username"),
    Column("role_name", "Role"),
    Column("status_name", "Status", "center"),
    Column("pin_text", "Sign-in code", "center"),
    Column("created_at", "Registered"),
    Column("decided_by", "Approved / revoked by"),
    Column("decided_at", "On"),
]

FILTERS = [("Everyone", None), ("Awaiting approval", auth.PENDING), ("Active", auth.ACTIVE),
           ("Revoked", auth.REVOKED)]


class PasswordDialog(QDialog):
    """Ask for a new password (or 6-digit code) twice, optionally with the current password."""

    def __init__(self, title: str, intro: str, parent=None, ask_current: bool = False,
                 code: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.current = QLineEdit()
        self.password = QLineEdit()
        self.confirm = QLineEdit()
        for edit in (self.current, self.password, self.confirm):
            edit.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText(f"{auth.PIN_LENGTH} digits, or leave empty to remove"
                                         if code else f"At least {auth.MIN_PASSWORD} characters")
        if code:
            for edit in (self.password, self.confirm):
                edit.setMaxLength(auth.PIN_LENGTH)
        form = QFormLayout()
        if ask_current:
            form.addRow("Your password:" if code else "Current password:", self.current)
        form.addRow("New code:" if code else "New password:", self.password)
        form.addRow("Confirm:", self.confirm)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        style_dialog_buttons(buttons)
        layout = QVBoxLayout(self)
        text = QLabel(intro)
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addLayout(form)
        layout.addWidget(buttons)


class UsersPage(QWidget):
    data_changed = Signal()

    def __init__(self, conn, user: auth.User, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.user = user

        self.model = RecordTableModel(USER_COLUMNS)
        self.proxy = TableProxy()
        self.filter = QComboBox()
        for label, status in FILTERS:
            self.filter.addItem(label, status)
        self.proxy.filter_fn = lambda row: (self.filter.currentData() is None
                                            or row["status"] == self.filter.currentData())
        self.filter.currentIndexChanged.connect(self._refilter)
        self.view = make_table(self.model, self.proxy)
        use_pills(self.view, USER_COLUMNS, "status_name")
        self.view.selectionModel().selectionChanged.connect(self._update_buttons)
        self.view.doubleClicked.connect(lambda _index: self.approve())

        self.approve_btn = make_button("Approve", "primary")
        self.revoke_btn = make_button("Revoke access", "danger")
        self.role_btn = make_button("Make user admin")
        self.password_btn = make_button("Set new password")
        self.pin_btn = make_button("Remove sign-in code")
        self.pin_btn.setToolTip("Use this if someone else may know their 6-digit code. "
                                "They can still sign in with their password.")
        self.pin_btn.clicked.connect(self.remove_pin)
        self.approve_btn.clicked.connect(self.approve)
        self.revoke_btn.clicked.connect(self.revoke)
        self.role_btn.clicked.connect(self.toggle_role)
        self.password_btn.clicked.connect(self.set_password)
        self.role_btn.setVisible(user.role == auth.SUPERADMIN)

        card = Card("Accounts")
        if user.role == auth.USERADMIN:
            note = hint_label("   As a user admin you can manage regular users. "
                              "Only the superadmin can change administrators.")
            note.setWordWrap(False)
            card.header.insertWidget(1, note)
        card.header.addWidget(self.filter)
        card.body.addWidget(self.view)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 4, 0, 0)
        for button in (self.approve_btn, self.revoke_btn, self.role_btn, self.password_btn,
                       self.pin_btn):
            bar.addWidget(button)
        bar.addStretch()
        card.body.addLayout(bar)

        self.header = page_header("Users", "")
        layout = page_layout(self)
        layout.addWidget(self.header)
        layout.addWidget(card, 1)
        self._update_buttons()

    # --- data ------------------------------------------------------------------
    def refresh(self):
        rows = auth.user_rows(self.conn)
        self.model.set_rows(rows)
        pending = sum(r["status"] == auth.PENDING for r in rows)
        self.header.subtitle_label.setText(
            (f"{pending} account{'s' if pending != 1 else ''} awaiting approval. "
             if pending else "") + "Approve new accounts and manage who can use MedTracker.")
        self._update_buttons()

    def _refilter(self):
        self.proxy.refilter()
        self._update_buttons()

    def _selected(self) -> dict | None:
        rows = self.view.selectionModel().selectedRows()
        if not rows:
            return None
        return self.model.row_dict(self.proxy.mapToSource(rows[0]).row())

    def _update_buttons(self, *_):
        row = self._selected()
        manageable = row is not None and auth.can_manage(self.user, row)
        status = row["status"] if row else None
        self.approve_btn.setText("Restore access" if status == auth.REVOKED else "Approve")
        self.approve_btn.setEnabled(manageable and status in (auth.PENDING, auth.REVOKED))
        self.revoke_btn.setEnabled(manageable and status in (auth.PENDING, auth.ACTIVE))
        self.password_btn.setEnabled(manageable)
        self.pin_btn.setEnabled(manageable and row["has_pin"])
        self.role_btn.setEnabled(manageable and status == auth.ACTIVE)
        self.role_btn.setText("Make regular user" if row and row["role"] == auth.USERADMIN
                              else "Make user admin")

    def _done(self):
        self.refresh()
        self.data_changed.emit()

    # --- actions ---------------------------------------------------------------
    def approve(self):
        row = self._selected()
        if row is None or row["status"] == auth.ACTIVE or not auth.can_manage(self.user, row):
            return
        try:
            auth.approve(self.conn, self.user, row["id"])
        except auth.AuthError as exc:
            show_error(self, str(exc))
            return
        self._done()

    def revoke(self):
        row = self._selected()
        if row is None:
            return
        if not ask_yes_no(self, f"Revoke access for {row['full_name']} ({row['username']})?\n\n"
                                f"They won't be able to sign in until access is restored. "
                                f"Their past entries are kept.",
                          title="Revoke access", yes_text="Revoke access", no_text="Cancel"):
            return
        try:
            auth.revoke(self.conn, self.user, row["id"])
        except auth.AuthError as exc:
            show_error(self, str(exc))
            return
        self._done()

    def toggle_role(self):
        row = self._selected()
        if row is None:
            return
        new_role = auth.USER if row["role"] == auth.USERADMIN else auth.USERADMIN
        try:
            auth.set_role(self.conn, self.user, row["id"], new_role)
        except auth.AuthError as exc:
            show_error(self, str(exc))
            return
        self._done()

    def remove_pin(self):
        row = self._selected()
        if row is None or not ask_yes_no(
                self, f"Remove the 6-digit sign-in code for {row['full_name']}?\n\n"
                      f"They can still sign in with their password and set a new code.",
                title="Remove sign-in code", yes_text="Remove code", no_text="Cancel"):
            return
        try:
            auth.remove_pin(self.conn, self.user, row["id"])
        except auth.AuthError as exc:
            show_error(self, str(exc))
            return
        self._done()

    def set_password(self):
        row = self._selected()
        if row is None:
            return
        dialog = PasswordDialog("Set new password",
                                f"Choose a new password for {row['full_name']} and tell them "
                                f"what it is. They can change it after signing in.", self)
        while dialog.exec():
            try:
                auth.set_password(self.conn, self.user, row["id"], dialog.password.text(),
                                  dialog.confirm.text())
            except auth.AuthError as exc:
                show_error(self, str(exc))
                continue
            show_info(self, f"The password for {row['full_name']} was changed.",
                      title="Password changed")
            return
