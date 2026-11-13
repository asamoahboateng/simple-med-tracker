"""ui/login.py - The sign-in window: sign in, create an account, or use the superadmin code."""

from PySide6.QtCore import QRegularExpression, Qt, QTimer
from PySide6.QtGui import QPixmap, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

import auth
import config
from ui import theme
from ui.widgets import make_button

MAX_ATTEMPTS = 5          # wrong attempts in a row before a pause
PAUSE_SECONDS = 30


def _link(text: str, slot) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("kind", "link")
    button.setCursor(Qt.PointingHandCursor)
    button.clicked.connect(slot)
    return button


def _field(placeholder: str = "", secret: bool = False, digits: int = 0) -> QLineEdit:
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setMinimumHeight(38)
    if secret:
        edit.setEchoMode(QLineEdit.Password)
    if digits:                       # numbers only, at most `digits` of them
        edit.setMaxLength(digits)
        edit.setValidator(QRegularExpressionValidator(QRegularExpression(rf"\d{{0,{digits}}}"), edit))
        edit.setInputMethodHints(Qt.ImhDigitsOnly)
    return edit


class LoginDialog(QDialog):
    """Shown before the main window. On success, `self.user` is the signed-in user."""

    def __init__(self, conn, demo: bool = False, notice: str = "", parent=None):
        super().__init__(parent)
        self.conn = conn
        self.user: auth.User | None = None
        self.failures = 0
        self.pause_left = 0
        self.setWindowTitle(f"{config.APP_NAME} - Sign in" + ("  [DEMO]" if demo else ""))
        self.setMinimumSize(780, 680)

        # --- brand panel ---
        brand = QWidget()
        brand.setObjectName("sidebar")
        brand.setAttribute(Qt.WA_StyledBackground, True)
        brand.setFixedWidth(280)
        bcol = QVBoxLayout(brand)
        bcol.setContentsMargins(32, 40, 32, 32)
        bcol.setSpacing(6)
        logo = QLabel()
        icon_file = config.resource_path("resources/icon.png")
        if icon_file.exists():
            pixmap = QPixmap(str(icon_file)).scaled(112, 112, Qt.KeepAspectRatio,
                                                    Qt.SmoothTransformation)
            pixmap.setDevicePixelRatio(2.0)
            logo.setPixmap(pixmap)
        title = QLabel(config.APP_NAME)
        title.setObjectName("brandTitle")
        title.setStyleSheet("font-size: 26px;")
        sub = QLabel("Pharmacy inventory")
        sub.setObjectName("brandSub")
        sub.setStyleSheet("font-size: 14px;")
        bcol.addWidget(logo)
        bcol.addSpacing(12)
        bcol.addWidget(title)
        bcol.addWidget(sub)
        bcol.addStretch()
        version = QLabel(f"Version {config.APP_VERSION}")
        version.setObjectName("versionLabel")
        version.setStyleSheet("padding-left: 0;")
        bcol.addWidget(version)

        # --- forms ---
        self.stack = QStackedWidget()
        self.stack.addWidget(self._sign_in_page(notice))
        self.stack.addWidget(self._register_page())
        self.stack.addWidget(self._code_page())

        form_side = QWidget()
        fcol = QVBoxLayout(form_side)
        fcol.setContentsMargins(48, 40, 48, 32)
        fcol.addWidget(self.stack)
        fcol.addStretch()

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(brand)
        row.addWidget(form_side, 1)

        self.pause_timer = QTimer(self)
        self.pause_timer.setInterval(1000)
        self.pause_timer.timeout.connect(self._tick_pause)
        self.show_sign_in()

    # --- pages ---------------------------------------------------------------
    def _page(self, heading: str, intro: str = ""):
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)
        title = QLabel(heading)
        title.setObjectName("dashTitle")
        col.addWidget(title)
        if intro:
            text = QLabel(intro)
            text.setObjectName("muted")
            text.setWordWrap(True)
            col.addWidget(text)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.setVerticalSpacing(6)
        col.addSpacing(6)
        col.addLayout(form)
        message = QLabel()
        message.setWordWrap(True)
        message.setVisible(False)
        col.addWidget(message)
        return page, col, form, message

    def _sign_in_page(self, notice: str) -> QWidget:
        page, col, form, self.sign_in_msg = self._page("Sign in")
        self.username_edit = _field("Your username")
        self.password_edit = _field("Password, or your 6-digit code if you set one", secret=True)
        form.addRow("Username", self.username_edit)
        form.addRow("Password or 6-digit code", self.password_edit)
        self.sign_in_btn = make_button("Sign in", "primary", large=True)
        self.sign_in_btn.clicked.connect(self.do_sign_in)
        self.password_edit.returnPressed.connect(self.do_sign_in)
        self.username_edit.returnPressed.connect(self.password_edit.setFocus)
        col.addWidget(self.sign_in_btn)
        links = QHBoxLayout()
        links.addWidget(_link("Create an account", self.show_register))
        links.addStretch()
        links.addWidget(_link("Use the superadmin code", self.show_code))
        col.addLayout(links)
        if notice:
            self._message(self.sign_in_msg, notice, error=False)
        col.addStretch()
        return page

    def _register_page(self) -> QWidget:
        page, col, form, self.register_msg = self._page(
            "Create an account",
            "An administrator approves new accounts before they can sign in.")
        self.reg_name = _field("e.g. Ama Mensah")
        self.reg_username = _field("Letters and numbers, no spaces")
        self.reg_password = _field(f"At least {auth.MIN_PASSWORD} characters", secret=True)
        self.reg_confirm = _field("Type it again", secret=True)
        self.reg_pin = _field("Optional, for quicker sign-in", secret=True, digits=auth.PIN_LENGTH)
        self.reg_pin_confirm = _field("Type it again", secret=True, digits=auth.PIN_LENGTH)
        form.addRow("Full name", self.reg_name)
        form.addRow("Username", self.reg_username)
        form.addRow("Password", self.reg_password)
        form.addRow("Confirm password", self.reg_confirm)
        form.addRow("6-digit sign-in code (optional)", self.reg_pin)
        form.addRow("Confirm code", self.reg_pin_confirm)
        self.reg_pin_confirm.returnPressed.connect(self.do_register)
        button = make_button("Create account", "primary", large=True)
        button.clicked.connect(self.do_register)
        col.addWidget(button)
        col.addWidget(_link("Back to sign in", self.show_sign_in), 0, Qt.AlignLeft)
        col.addStretch()
        return page

    def _code_page(self) -> QWidget:
        page, col, form, self.code_msg = self._page(
            "Superadmin", "Sign in with the superadmin code to manage user accounts.")
        self.code_edit = _field("6-digit code", secret=True, digits=auth.PIN_LENGTH)
        form.addRow("Code", self.code_edit)
        self.code_btn = make_button("Sign in", "primary", large=True)
        self.code_btn.clicked.connect(self.do_code)
        self.code_edit.returnPressed.connect(self.do_code)
        col.addWidget(self.code_btn)
        col.addWidget(_link("Back to sign in", self.show_sign_in), 0, Qt.AlignLeft)
        col.addStretch()
        return page

    # --- navigation ------------------------------------------------------------
    def show_sign_in(self):
        self.stack.setCurrentIndex(0)
        (self.password_edit if self.username_edit.text() else self.username_edit).setFocus()

    def show_register(self):
        self.register_msg.setVisible(False)
        self.stack.setCurrentIndex(1)
        self.reg_name.setFocus()

    def show_code(self):
        self.code_msg.setVisible(False)
        self.stack.setCurrentIndex(2)
        self.code_edit.setFocus()

    # --- actions ---------------------------------------------------------------
    def _message(self, label: QLabel, text: str, error: bool = True):
        colour, bg = (theme.RED, theme.RED_TINT) if error else (theme.GREEN, "#e2efe7")
        label.setStyleSheet(f"color: {colour}; background: {bg}; border-radius: 8px;"
                            f" padding: 10px 12px; font-weight: 600;")
        label.setText(text)
        label.setVisible(True)

    def _busy(self, fn):
        """Run a slow check (password hashing) with a wait cursor."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return fn()
        finally:
            QApplication.restoreOverrideCursor()

    def _failed(self, label: QLabel, text: str):
        self.failures += 1
        if self.failures >= MAX_ATTEMPTS:
            self.failures = 0
            self.pause_left = PAUSE_SECONDS
            self._set_paused(True)
            self.pause_timer.start()
            text += f"\n\nToo many attempts. Try again in {PAUSE_SECONDS} seconds."
        self._message(label, text)

    def _set_paused(self, paused: bool):
        for button in (self.sign_in_btn, self.code_btn):
            button.setEnabled(not paused)

    def _tick_pause(self):
        self.pause_left -= 1
        if self.pause_left <= 0:
            self.pause_timer.stop()
            self._set_paused(False)
            for label in (self.sign_in_msg, self.code_msg):
                label.setVisible(False)

    def _accept(self, user: auth.User):
        self.user = user
        self.accept()

    def do_sign_in(self):
        if self.pause_left > 0:
            return
        try:
            user = self._busy(lambda: auth.sign_in(self.conn, self.username_edit.text(),
                                                   self.password_edit.text()))
        except auth.AuthError as exc:
            self.password_edit.clear()
            # Only wrong credentials count towards the pause, not "awaiting approval".
            if "Wrong username" in str(exc):
                self._failed(self.sign_in_msg, str(exc))
            else:
                self._message(self.sign_in_msg, str(exc))
            return
        self._accept(user)

    def do_code(self):
        if self.pause_left > 0:
            return
        try:
            user = self._busy(lambda: auth.sign_in_with_code(self.code_edit.text()))
        except auth.AuthError as exc:
            self.code_edit.clear()
            self._failed(self.code_msg, str(exc))
            return
        self._accept(user)

    def do_register(self):
        try:
            self._busy(lambda: auth.register(
                self.conn, self.reg_username.text(), self.reg_name.text(),
                self.reg_password.text(), self.reg_confirm.text(),
                self.reg_pin.text(), self.reg_pin_confirm.text()))
        except auth.AuthError as exc:
            self._message(self.register_msg, str(exc))
            return
        username = self.reg_username.text().strip()
        for edit in (self.reg_name, self.reg_username, self.reg_password, self.reg_confirm,
                     self.reg_pin, self.reg_pin_confirm):
            edit.clear()
        self.username_edit.setText(username)
        self.password_edit.clear()
        self._message(self.sign_in_msg,
                      "Account created. You can sign in once an administrator approves it.",
                      error=False)
        self.show_sign_in()
