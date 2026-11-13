"""ui/main_window.py - Main window: sidebar, pages, menu bar, backup/restore, sign-out."""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

import auth
import config
import db
from ui.add_stock import AddStockDialog
from ui.dashboard import DashboardPage
from ui.dispense import DispenseDialog
from ui.log import LogPage
from ui.medicine import NewMedicineDialog
from ui.report import ReportPage
from ui import icons, theme
from ui.stock import StockPage
from ui.units import UnitsDialog
from ui.users import PasswordDialog, UsersPage
from ui.widgets import ask_yes_no, show_error, show_info


class MainWindow(QMainWindow):
    # Emitted when the user signs out (or loses access); the message is shown on the
    # sign-in window. The database connection stays open for the next session.
    signed_out = Signal(str)
    # Emitted after the colour theme changed: main.py rebuilds the window in the new colours.
    restyle_requested = Signal()

    def __init__(self, conn, db_path: Path, user: auth.User, demo: bool = False):
        super().__init__()
        self.conn = conn
        self.db_path = Path(db_path)
        self.user = user
        self.demo = demo
        self.signing_out = False
        self.setWindowTitle(f"{config.APP_NAME} {config.APP_VERSION}"
                            + ("  [DEMO - sample data]" if demo else ""))
        self.resize(1280, 820)
        self.setMinimumSize(720, 520)

        # --- pages ---
        self.dashboard = DashboardPage(conn)
        self.log_page = LogPage(conn)
        self.stock_page = StockPage(conn)
        self.report_page = ReportPage(conn)
        self.pages = [
            ("Dashboard", "dashboard", self.dashboard),
            ("Dispensing Log", "log", self.log_page),
            ("Stock & Batches", "stock", self.stock_page),
            ("Reports", "report", self.report_page),
        ]
        self.users_page = None
        if user.is_admin:
            self.users_page = UsersPage(conn, user)
            self.users_page.data_changed.connect(self._update_users_label)
            self.pages.append(("Users", "users", self.users_page))
        self.dirty = {id(page) for *_, page in self.pages}   # pages needing a refresh

        self.stack = QStackedWidget()
        for *_, page in self.pages:
            self.stack.addWidget(page)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # --- wiring ---
        self.dashboard.add_stock_requested.connect(self.open_add_stock)
        self.dashboard.dispense_requested.connect(self.open_dispense)
        self.dashboard.reorder_levels_requested.connect(
            lambda: self.sidebar.setCurrentRow(self.stack.indexOf(self.stock_page)))
        self.log_page.data_changed.connect(self.data_changed)
        self.stock_page.data_changed.connect(self.data_changed)
        self.stock_page.new_medicine_requested.connect(self.open_new_medicine)
        self.stock_page.units_requested.connect(self.open_units)

        self._build_menu()
        self.statusBar().addWidget(QLabel(f"Database: {self.db_path}"))

        self.sidebar.setCurrentRow(0)
        self._update_users_label()

    def _build_sidebar(self) -> QWidget:
        """Dark navigation panel: logo, page list, quick actions, version."""
        side = QWidget()
        side.setObjectName("sidebar")
        side.setAttribute(Qt.WA_StyledBackground, True)
        side.setFixedWidth(232)
        self.side = side
        self.compact = False
        self.wide_only = []          # widgets hidden when the sidebar is compact
        self.side_buttons = []       # (button, text)
        col = QVBoxLayout(side)
        col.setContentsMargins(0, 20, 0, 16)
        col.setSpacing(6)

        brand = QHBoxLayout()
        brand.setContentsMargins(18, 0, 12, 14)
        logo = QLabel()
        icon_file = config.resource_path("resources/icon.png")
        if icon_file.exists():
            pixmap = QPixmap(str(icon_file)).scaled(80, 80, Qt.KeepAspectRatio,
                                                    Qt.SmoothTransformation)
            pixmap.setDevicePixelRatio(2.0)   # 80 px image shown at 40 px: sharp on HiDPI
            logo.setPixmap(pixmap)
        names_box = QWidget()
        names = QVBoxLayout(names_box)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        title = QLabel(config.APP_NAME)
        title.setObjectName("brandTitle")
        sub = QLabel("Pharmacy inventory")
        sub.setObjectName("brandSub")
        names.addWidget(title)
        names.addWidget(sub)
        brand.addWidget(logo)
        brand.addSpacing(8)
        brand.addWidget(names_box, 1)
        col.addLayout(brand)
        self.brand_layout = brand
        self.wide_only.append(names_box)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("nav")
        self.sidebar.setCursor(Qt.PointingHandCursor)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar.setIconSize(QSize(20, 20))
        for label, icon_name, _ in self.pages:
            self.sidebar.addItem(QListWidgetItem(
                icons.icon(icon_name, theme.SIDEBAR_TEXT, selected_colour=theme.TEXT), label))
        self.sidebar.setFixedHeight(len(self.pages) * 48 + 8)
        self.sidebar.currentRowChanged.connect(self.show_page)
        col.addWidget(self.sidebar)

        col.addSpacing(10)
        caption = QLabel("Quick actions")
        caption.setObjectName("navCaption")
        col.addWidget(caption)
        self.wide_only.append(caption)
        for text, icon_name, slot in (("Add stock", "plus", self.open_add_stock),
                                      ("Record dispensed", "tablet", self.open_dispense),
                                      ("New medicine", "bottle", self.open_new_medicine)):
            button = QPushButton(icons.icon(icon_name, "#ffffff", size=18), f"  {text}")
            button.setIconSize(QSize(18, 18))
            button.setObjectName("sideAction")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(slot)
            button.setToolTip(text)
            col.addWidget(button)
            self.side_buttons.append((button, text))

        col.addStretch()

        # --- who is signed in ---
        who = QWidget()
        who_col = QVBoxLayout(who)
        who_col.setContentsMargins(20, 0, 12, 4)
        who_col.setSpacing(0)
        name = QLabel(self.user.full_name)
        name.setObjectName("brandTitle")
        name.setStyleSheet("font-size: 14px;")
        role = QLabel("Signed in with the code" if self.user.id is None
                      else f"{self.user.role_name}, {self.user.username}")
        role.setObjectName("brandSub")
        who_col.addWidget(name)
        who_col.addWidget(role)
        col.addWidget(who)
        self.wide_only.append(who)
        sign_out = QPushButton(icons.icon("signout", "#ffffff", size=18), "  Sign out")
        sign_out.setIconSize(QSize(18, 18))
        sign_out.setObjectName("sideAction")
        sign_out.setCursor(Qt.PointingHandCursor)
        sign_out.setToolTip("Sign out")
        sign_out.clicked.connect(lambda: self.sign_out())
        col.addWidget(sign_out)
        self.side_buttons.append((sign_out, "Sign out"))
        col.addSpacing(10)

        if self.demo:
            badge = QLabel("\u26A0  DEMO MODE \u00b7 sample data")
            badge.setObjectName("demoBadge")
            col.addWidget(badge)
            self.wide_only.append(badge)
        version = QLabel(f"Version {config.APP_VERSION}")
        version.setObjectName("versionLabel")
        col.addWidget(version)
        self.wide_only.append(version)
        return side

    def set_compact_sidebar(self, compact: bool) -> None:
        """Icons-only sidebar for small windows (hover an icon to see its name)."""
        if compact == self.compact:
            return
        self.compact = compact
        self.side.setFixedWidth(76 if compact else 232)
        self.brand_layout.setContentsMargins(18, 0, 12 if not compact else 0, 14)
        for widget in self.wide_only:
            widget.setVisible(not compact)
        self._update_users_label()
        for i, (label, *_) in enumerate(self.pages):
            item = self.sidebar.item(i)
            if self.pages[i][-1] is not self.users_page:
                item.setText("" if compact else label)
            item.setToolTip(label if compact else "")
        for button, text in self.side_buttons:
            button.setText("" if compact else f"  {text}")
            button.setStyleSheet("text-align: center; padding: 10px 0;" if compact else "")

    def resizeEvent(self, event):
        self.set_compact_sidebar(event.size().width() < 1100)
        super().resizeEvent(event)

    # --- navigation and refreshing ------------------------------------------
    def show_page(self, row: int):
        if not self.check_access():
            return
        self.stack.setCurrentIndex(row)
        page = self.pages[row][-1]
        if id(page) in self.dirty:
            page.refresh()
            self.dirty.discard(id(page))

    def data_changed(self):
        """Something was saved: refresh the visible page now, the others when shown."""
        self.dirty = {id(page) for *_, page in self.pages}
        self.show_page(self.stack.currentIndex())
        self._update_users_label()

    def _update_users_label(self):
        """Show how many accounts are waiting, e.g. "Users (2)"."""
        if self.users_page is None:
            return
        pending = db.pending_user_count(self.conn)
        item = self.sidebar.item(self.stack.indexOf(self.users_page))
        if self.compact:
            item.setText(str(pending) if pending else "")
        else:
            item.setText(f"Users ({pending})" if pending else "Users")

    def open_add_stock(self):
        if self.check_access() and AddStockDialog(
                self.conn, self, entered_by=self.user.display_name).exec():
            self.data_changed()

    def open_units(self):
        if self.check_access():
            UnitsDialog(self.conn, self).exec()

    def open_new_medicine(self):
        if self.check_access() and NewMedicineDialog(self.conn, self).exec():
            self.data_changed()

    def open_dispense(self):
        if not self.check_access():
            return
        if not db.list_medicines(self.conn):
            show_info(self, "There are no medicines yet. Use 'Add Stock' first.", title="No stock")
            return
        if DispenseDialog(self.conn, self, entered_by=self.user.display_name).exec():
            self.data_changed()

    # --- signing out --------------------------------------------------------
    def check_access(self) -> bool:
        """Sign out at once if this user's access was revoked or their role changed."""
        if self.signing_out:
            return False
        if not auth.still_allowed(self.conn, self.user):
            QTimer.singleShot(0, lambda: self.sign_out(
                "Your access has been revoked. Ask an administrator if you need it back."))
            return False
        if auth.refreshed(self.conn, self.user).role != self.user.role:
            QTimer.singleShot(0, lambda: self.sign_out(
                "Your role has changed. Please sign in again."))
            return False
        return True

    def sign_out(self, message: str = "") -> None:
        if self.signing_out:
            return
        self.signing_out = True
        self.close()
        self.signed_out.emit(message)

    def change_colours(self, name: str) -> None:
        if name == theme.current_preset:
            return
        theme.save_preset(name)
        theme.apply_theme(QApplication.instance(), name)
        self.restyle_requested.emit()

    def set_sign_in_code(self):
        dialog = PasswordDialog(
            "Set sign-in code",
            f"Choose a {auth.PIN_LENGTH}-digit code to sign in with instead of your password. "
            f"Leave both code boxes empty to remove your code.", self, ask_current=True, code=True)
        while dialog.exec():
            try:
                auth.set_own_pin(self.conn, self.user, dialog.current.text(),
                                 dialog.password.text(), dialog.confirm.text())
            except auth.AuthError as exc:
                show_error(self, str(exc))
                continue
            show_info(self, "Your sign-in code was saved." if dialog.password.text()
                      else "Your sign-in code was removed.", title="Sign-in code")
            return

    def change_password(self):
        dialog = PasswordDialog("Change password", "Choose a new password for your account.",
                                self, ask_current=True)
        while dialog.exec():
            try:
                auth.change_own_password(self.conn, self.user, dialog.current.text(),
                                         dialog.password.text(), dialog.confirm.text())
            except auth.AuthError as exc:
                show_error(self, str(exc))
                continue
            show_info(self, "Your password was changed.", title="Password changed")
            return

    # --- menu ---------------------------------------------------------------
    def _action(self, menu, text, slot, shortcut=None):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _build_menu(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        self._action(file_menu, "Backup database...", self.backup_database, "Ctrl+B")
        if self.user.is_admin:
            # Restoring replaces the user accounts too, so only administrators may do it.
            self._action(file_menu, "Restore from backup...", self.restore_database)
        file_menu.addSeparator()
        self._action(file_menu, "Open data folder", self.open_data_folder)
        file_menu.addSeparator()
        if self.user.role != auth.SUPERADMIN:
            self._action(file_menu, "Change password...", self.change_password)
            self._action(file_menu, "Set sign-in code...", self.set_sign_in_code)
        self._action(file_menu, "Sign out", lambda: self.sign_out(), "Ctrl+Shift+Q")
        file_menu.addSeparator()
        exit_action = self._action(file_menu, "Exit", self.close, QKeySequence.Quit)
        exit_action.setMenuRole(QAction.QuitRole)

        entries = bar.addMenu("&Entries")
        self._action(entries, "New Medicine...", self.open_new_medicine, "Ctrl+M")
        self._action(entries, "Add Stock...", self.open_add_stock, "Ctrl+N")
        self._action(entries, "Record Dispensed...", self.open_dispense, "Ctrl+D")
        entries.addSeparator()
        self._action(entries, "Units...", self.open_units)

        view_menu = bar.addMenu("&View")
        colours = view_menu.addMenu("Colour theme")
        group = QActionGroup(self)
        for name, preset in theme.PRESETS.items():
            swatch = QPixmap(16, 16)
            swatch.fill(QColor(preset["NAVY"]))
            action = QAction(QIcon(swatch), name, self, checkable=True)
            action.setChecked(name == theme.current_preset)
            action.triggered.connect(lambda _checked=False, n=name: self.change_colours(n))
            group.addAction(action)
            colours.addAction(action)

        help_menu = bar.addMenu("&Help")
        about = self._action(help_menu, f"About {config.APP_NAME}", self.show_about)
        about.setMenuRole(QAction.AboutRole)

    def backup_database(self):
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        prefix = "medtracker_demo" if self.demo else "medtracker"
        suggested = str(config.backups_dir() / f"{prefix}_backup_{stamp}.db")
        path, _ = QFileDialog.getSaveFileName(self, "Backup database", suggested,
                                              "Database files (*.db)")
        if not path:
            return
        if not path.lower().endswith(".db"):
            path += ".db"
        if Path(path).resolve() == self.db_path.resolve():
            show_error(self, "Please choose a different file name for the backup.")
            return
        db.backup_to(self.conn, path)
        show_info(self, f"Backup saved to:\n{path}", title="Backup complete")

    def restore_database(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore from backup",
                                              str(config.backups_dir()), "Database files (*.db)")
        if not path:
            return
        if Path(path).resolve() == self.db_path.resolve():
            show_error(self, "That is the database currently in use. Choose a backup file.")
            return
        if not db.is_valid_backup(path):
            show_error(self, "This file is not a valid MedTracker backup.", title="Cannot restore")
            return
        if not ask_yes_no(
                self,
                f"Restore from:\n{path}\n\nALL current data will be REPLACED by the backup.\n"
                f"(A safety copy of the current data will be saved first.)\n\nContinue?",
                title="Restore from backup", yes_text="Restore", no_text="Cancel"):
            return
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        safety = config.backups_dir() / f"before_restore_{stamp}.db"
        db.backup_to(self.conn, safety)
        db.restore_from(self.conn, path)
        self.data_changed()
        if not auth.still_allowed(self.conn, self.user):
            self.sign_out("The restored data does not include your account. "
                          "Sign in with an account from the backup, or the superadmin code.")
            return
        show_info(self, f"Data restored.\n\nYour previous data was saved to:\n{safety}",
                  title="Restore complete")

    def open_data_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.data_dir())))

    def show_about(self):
        QMessageBox.about(
            self, f"About {config.APP_NAME}",
            f"<h3>{config.APP_NAME} {config.APP_VERSION}</h3>"
            f"<p>{config.APP_DESCRIPTION}</p>"
            f"<p>Data folder:<br><code>{config.data_dir()}</code></p>")

    def closeEvent(self, event):
        super().closeEvent(event)
        if not self.signing_out:      # closing the window quits the app
            self.conn.close()
            QApplication.quit()
