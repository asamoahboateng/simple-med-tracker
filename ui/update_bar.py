"""ui/update_bar.py - The slim "update available" bar shown above the pages."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

import config
import updater
from ui import theme
from ui.widgets import make_button


class UpdateBar(QFrame):
    """
    "MedTracker X is available." with buttons. It only emits signals; ui/update_flow.py
    does the work. Hidden until show_update() is called.
    """

    whats_new = Signal()
    install_now = Signal()
    install_on_close = Signal()
    download_page = Signal()
    dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("updateBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#updateBar {{ background: {theme.tint(theme.BLUE, 0.10)};"
            f" border-bottom: 1px solid {theme.tint(theme.BLUE, 0.35)}; }}"
            f" #updateBar QLabel {{ background: transparent; color: {theme.TEXT}; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 8, 16, 8)
        row.setSpacing(8)
        self.label = QLabel()
        self.label.setWordWrap(True)
        row.addWidget(self.label, 1)

        self.news_button = make_button("What's new")
        self.install_button = make_button("Install now", "primary")
        self.close_button = make_button("Install when I close")
        self.download_button = make_button("Download", "primary")
        self.later_button = make_button("Later", "link")
        self.news_button.clicked.connect(self.whats_new)
        self.install_button.clicked.connect(self.install_now)
        self.close_button.clicked.connect(self.install_on_close)
        self.download_button.clicked.connect(self.download_page)
        self.later_button.clicked.connect(self._later)
        for button in (self.news_button, self.install_button, self.close_button,
                       self.download_button, self.later_button):
            row.addWidget(button)
        self.hide()

    def _later(self):
        self.hide()
        self.dismissed.emit()

    def show_update(self, manifest, current_version: str = config.APP_VERSION) -> None:
        """Fill the bar for this manifest and show it."""
        manual = updater.needs_manual_install(manifest, current_version)
        can_install = updater.can_self_install() and not manual
        if manual:
            text = (f"MedTracker {manifest.version} is available. This version cannot update "
                    f"itself: please download and install the new version by hand once.")
        elif can_install:
            text = f"MedTracker {manifest.version} is available."
        else:
            text = (f"MedTracker {manifest.version} is available. Download it from the "
                    f"releases page.")
        self.label.setText(text)
        self.news_button.setVisible(bool(manifest.notes))
        self.install_button.setVisible(can_install)
        self.close_button.setVisible(can_install)
        self.download_button.setVisible(not can_install)
        self.show()
