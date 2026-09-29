"""ui/main_window.py - Main window: sidebar, pages, menu bar, backup/restore."""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

import config
import db
from ui.add_stock import AddStockDialog
from ui.dashboard import DashboardPage
from ui.dispense import DispenseDialog
from ui.log import LogPage
from ui.medicine import NewMedicineDialog
from ui.report import ReportPage
from ui.stock import StockPage
from ui.widgets import ask_yes_no, show_error, show_info


class MainWindow(QMainWindow):
    def __init__(self, conn, db_path: Path, demo: bool = False):
        super().__init__()
        self.conn = conn
        self.db_path = Path(db_path)
        self.demo = demo
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
            ("\U0001F3E0   Dashboard", self.dashboard),
            ("\U0001F4CB   Dispensing Log", self.log_page),
            ("\U0001F4E6   Stock & Batches", self.stock_page),
            ("\U0001F4CA   Monthly Report", self.report_page),
        ]
        self.dirty = {id(page) for _, page in self.pages}   # pages needing a refresh

        self.stack = QStackedWidget()
        for _, page in self.pages:
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
        self.log_page.data_changed.connect(self.data_changed)
        self.stock_page.data_changed.connect(self.data_changed)
        self.stock_page.new_medicine_requested.connect(self.open_new_medicine)

        self._build_menu()
        self.statusBar().addWidget(QLabel(f"Database: {self.db_path}"))

        self.sidebar.setCurrentRow(0)

    def _build_sidebar(self) -> QWidget:
        """Dark navigation panel: logo, page list, quick actions, version."""
        side = QWidget()
        side.setObjectName("sidebar")
        side.setAttribute(Qt.WA_StyledBackground, True)
        side.setFixedWidth(232)
        self.side = side
        self.compact = False
        self.wide_only = []          # widgets hidden when the sidebar is compact
        self.side_buttons = []       # (button, full text, icon only)
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

        caption = QLabel("MENU")
        caption.setObjectName("navCaption")
        col.addWidget(caption)
        self.wide_only.append(caption)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("nav")
        self.sidebar.setCursor(Qt.PointingHandCursor)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for label, _ in self.pages:
            self.sidebar.addItem(QListWidgetItem(label))
        self.sidebar.setFixedHeight(len(self.pages) * 48 + 8)
        self.sidebar.currentRowChanged.connect(self.show_page)
        col.addWidget(self.sidebar)

        col.addSpacing(10)
        caption = QLabel("QUICK ACTIONS")
        caption.setObjectName("navCaption")
        col.addWidget(caption)
        self.wide_only.append(caption)
        for text, slot in (("+   Add Stock", self.open_add_stock),
                           ("\U0001F48A   Record Dispensed", self.open_dispense),
                           ("\U0001F9F4   New Medicine", self.open_new_medicine)):
            button = QPushButton(text)
            button.setObjectName("sideAction")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(slot)
            button.setToolTip(text.split("   ", 1)[1])
            col.addWidget(button)
            self.side_buttons.append((button, text, text.split("   ", 1)[0]))

        col.addStretch()
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
        for i, (label, _) in enumerate(self.pages):
            item = self.sidebar.item(i)
            icon, name = label.split("   ", 1)
            item.setText(icon if compact else label)
            item.setToolTip(name if compact else "")
            item.setTextAlignment(Qt.AlignCenter if compact else Qt.AlignLeft | Qt.AlignVCenter)
        for button, full, icon in self.side_buttons:
            button.setText(icon if compact else full)
            button.setStyleSheet("text-align: center; padding: 8px 0; font-size: 17px;"
                                 if compact else "")

    def resizeEvent(self, event):
        self.set_compact_sidebar(event.size().width() < 1100)
        super().resizeEvent(event)

    # --- navigation and refreshing ------------------------------------------
    def show_page(self, row: int):
        self.stack.setCurrentIndex(row)
        page = self.pages[row][1]
        if id(page) in self.dirty:
            page.refresh()
            self.dirty.discard(id(page))

    def data_changed(self):
        """Something was saved: refresh the visible page now, the others when shown."""
        self.dirty = {id(page) for _, page in self.pages}
        self.show_page(self.stack.currentIndex())

    def open_add_stock(self):
        if AddStockDialog(self.conn, self).exec():
            self.data_changed()

    def open_new_medicine(self):
        if NewMedicineDialog(self.conn, self).exec():
            self.data_changed()

    def open_dispense(self):
        if not db.list_medicines(self.conn):
            show_info(self, "There are no medicines yet. Use 'Add Stock' first.", title="No stock")
            return
        if DispenseDialog(self.conn, self).exec():
            self.data_changed()

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
        self._action(file_menu, "Restore from backup...", self.restore_database)
        file_menu.addSeparator()
        self._action(file_menu, "Open data folder", self.open_data_folder)
        file_menu.addSeparator()
        exit_action = self._action(file_menu, "Exit", self.close, QKeySequence.Quit)
        exit_action.setMenuRole(QAction.QuitRole)

        entries = bar.addMenu("&Entries")
        self._action(entries, "New Medicine...", self.open_new_medicine, "Ctrl+M")
        self._action(entries, "Add Stock...", self.open_add_stock, "Ctrl+N")
        self._action(entries, "Record Dispensed...", self.open_dispense, "Ctrl+D")

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
        try:
            self.conn.close()
        finally:
            super().closeEvent(event)
