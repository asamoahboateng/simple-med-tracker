"""
ui/theme.py - The MedTracker look: colour palette and one global Qt stylesheet.

Widgets opt into styles with setObjectName(...) or a "kind" property, e.g.
    button.setProperty("kind", "primary")
so page code stays free of colour details.
"""

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from config import resource_path

# --- palette -------------------------------------------------------------
BG = "#f3f5fa"            # window background
SURFACE = "#ffffff"       # cards, tables, inputs
BORDER = "#e3e8f0"
BORDER_STRONG = "#d3dae6"
TEXT = "#14213d"
TEXT_MUTED = "#6b7a90"
NAVY = "#0f2139"          # sidebar
NAVY_HOVER = "#1a3354"
PRIMARY = "#1f8a78"       # teal - main action colour
PRIMARY_HOVER = "#18705f"
BLUE = "#3867d6"
BLUE_HOVER = "#2c55b8"
AMBER = "#e09f1f"
RED = "#d64545"
PURPLE = "#7c5cd6"
GREEN = "#2f9e5b"


def tint(hex_colour: str, alpha: float) -> str:
    """rgba() string of a colour at the given opacity (for soft backgrounds)."""
    c = QColor(hex_colour)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {int(alpha * 255)})"


def _stylesheet() -> str:
    down = resource_path("resources/chevron-down.svg").as_posix()
    up = resource_path("resources/chevron-up.svg").as_posix()
    check = resource_path("resources/check.svg").as_posix()
    return f"""
    QWidget {{ color: {TEXT}; }}
    QMainWindow, QWidget#page, QWidget#pageContent, QScrollArea, QScrollArea > QWidget > QWidget
        {{ background: {BG}; }}
    QDialog {{ background: {BG}; }}

    /* ---------- sidebar ---------- */
    QWidget#sidebar {{ background: {NAVY}; }}
    QWidget#sidebar QLabel {{ background: transparent; }}
    QLabel#brandTitle {{ color: white; font-size: 19px; font-weight: 700; }}
    QLabel#brandSub {{ color: #8ea3bf; font-size: 11px; }}
    QLabel#navCaption {{ color: #6f85a3; font-size: 10px; font-weight: 700;
                         letter-spacing: 1px; padding-left: 18px; }}
    QListWidget#nav {{ background: transparent; border: none; outline: 0;
                       color: #c6d2e3; font-size: 14px; }}
    QListWidget#nav::item {{ padding: 10px 12px; margin: 2px 10px; border-radius: 8px; }}
    QListWidget#nav::item:hover {{ background: {NAVY_HOVER}; color: white; }}
    QListWidget#nav::item:selected {{ background: {PRIMARY}; color: white; font-weight: 600; }}
    QPushButton#sideAction {{ background: {NAVY_HOVER}; color: white; border: 1px solid #28476f;
                              border-radius: 8px; padding: 9px 12px; text-align: left;
                              font-weight: 600; margin: 0 10px; }}
    QPushButton#sideAction:hover {{ background: #22406a; border-color: #3a5d8c; }}
    QLabel#demoBadge {{ background: {tint(AMBER, 0.18)}; color: #f3c56b; border-radius: 6px;
                        padding: 6px 8px; font-size: 11px; font-weight: 700; margin: 0 10px; }}
    QLabel#versionLabel {{ color: #5d7392; font-size: 11px; padding-left: 18px; }}

    /* ---------- headings ---------- */
    QLabel#pageTitle {{ font-size: 26px; font-weight: 700; color: {TEXT}; }}
    QLabel#pageSubtitle {{ font-size: 13px; color: {TEXT_MUTED}; }}
    QLabel#sectionTitle {{ font-size: 15px; font-weight: 700; color: {TEXT}; }}
    QLabel#hint {{ color: {TEXT_MUTED}; font-size: 12px; }}
    QFrame#card QLabel#countBadge {{ background: {tint(RED, 0.12)}; color: {RED}; border-radius: 9px;
                         padding: 1px 8px; font-size: 11px; font-weight: 700; }}

    /* ---------- cards ---------- */
    QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
    QFrame#card QLabel {{ background: transparent; }}
    QLabel#cardTitle {{ color: {TEXT_MUTED}; font-size: 12px; font-weight: 600; }}
    QLabel#cardValue {{ color: {TEXT}; font-size: 30px; font-weight: 700; }}
    QLabel#cardNote {{ color: {TEXT_MUTED}; font-size: 11px; }}

    /* ---------- buttons ---------- */
    QPushButton {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER_STRONG};
                   border-radius: 8px; padding: 7px 16px; font-weight: 600; }}
    QPushButton:hover {{ background: #eef3fb; border-color: #b8c5da; }}
    QPushButton:pressed {{ background: #e2eaf6; }}
    QPushButton:default {{ border-color: {PRIMARY}; }}
    QPushButton[kind="primary"] {{ background: {PRIMARY}; color: white; border: none; }}
    QPushButton[kind="primary"]:hover {{ background: {PRIMARY_HOVER}; }}
    QPushButton[kind="blue"] {{ background: {BLUE}; color: white; border: none; }}
    QPushButton[kind="blue"]:hover {{ background: {BLUE_HOVER}; }}
    QPushButton[kind="danger"] {{ color: {RED}; border-color: {tint(RED, 0.35)}; }}
    QPushButton[kind="danger"]:hover {{ background: {tint(RED, 0.08)}; }}
    QPushButton[size="large"] {{ padding: 11px 22px; font-size: 14px; border-radius: 10px; }}

    /* ---------- inputs ---------- */
    QLineEdit, QComboBox, QSpinBox, QDateEdit {{
        background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
        padding: 6px 10px; min-height: 20px; selection-background-color: {tint(PRIMARY, 0.3)};
        selection-color: {TEXT}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus
        {{ border: 1.5px solid {PRIMARY}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDateEdit:disabled
        {{ background: #f0f2f6; color: #9aa5b5; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url("{down}"); width: 12px; height: 12px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ border: none; width: 20px; background: transparent; }}
    QSpinBox::up-arrow {{ image: url("{up}"); width: 10px; height: 10px; }}
    QSpinBox::down-arrow {{ image: url("{down}"); width: 10px; height: 10px; }}
    QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER};
        selection-background-color: {tint(PRIMARY, 0.15)}; selection-color: {TEXT}; outline: 0; }}

    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
                            border: 1px solid {BORDER_STRONG}; background: {SURFACE}; }}
    QCheckBox::indicator:checked {{ background: {PRIMARY}; border-color: {PRIMARY};
                                    image: url("{check}"); }}

    QGroupBox {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
                 margin-top: 16px; padding: 14px 10px 8px 10px; font-weight: 700; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {PRIMARY}; }}

    /* ---------- tables ---------- */
    QTableView {{ background: {SURFACE}; alternate-background-color: #f9fafd;
                  border: 1px solid {BORDER}; border-radius: 12px; gridline-color: transparent;
                  selection-background-color: {tint(PRIMARY, 0.14)}; selection-color: {TEXT}; }}
    QTableView::item {{ padding: 0 8px; border-bottom: 1px solid #f0f2f7; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{ background: #f6f8fc; color: #52607a; font-weight: 700; font-size: 12px;
                            border: none; border-bottom: 1px solid {BORDER}; padding: 9px 8px; }}
    QHeaderView::section:first {{ border-top-left-radius: 12px; }}
    QHeaderView::section:last {{ border-top-right-radius: 12px; }}
    QTableCornerButton::section {{ background: #f6f8fc; border: none; }}


    /* ---------- misc ---------- */
    QSplitter::handle {{ background: transparent; height: 10px; }}
    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #c9d2df; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: #aab6c8; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: #c9d2df; border-radius: 4px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {TEXT_MUTED}; }}
    QStatusBar QLabel {{ color: {TEXT_MUTED}; padding: 2px 6px; }}
    QMenuBar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
    QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
    QMenuBar::item:selected {{ background: {tint(PRIMARY, 0.12)}; border-radius: 4px; }}
    QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px; }}
    QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {tint(PRIMARY, 0.12)}; color: {TEXT}; }}
    QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
    QToolTip {{ background: {NAVY}; color: white; border: none; padding: 6px 8px; border-radius: 4px; }}
    QMessageBox {{ background: {SURFACE}; }}
    QCalendarWidget QWidget {{ alternate-background-color: #f6f8fc; }}
    QCalendarWidget QToolButton {{ color: {TEXT}; background: transparent; font-weight: 600; }}
    """


def apply_theme(app: QApplication) -> None:
    """Apply the light MedTracker theme (same look on every OS, even in dark mode)."""
    app.setStyle("Fusion")
    palette = QPalette()
    for role, colour in {
        QPalette.Window: BG, QPalette.WindowText: TEXT, QPalette.Base: SURFACE,
        QPalette.AlternateBase: "#f9fafd", QPalette.Text: TEXT, QPalette.Button: SURFACE,
        QPalette.ButtonText: TEXT, QPalette.Highlight: PRIMARY, QPalette.HighlightedText: "#ffffff",
        QPalette.ToolTipBase: NAVY, QPalette.ToolTipText: "#ffffff",
        QPalette.PlaceholderText: "#9aa5b5", QPalette.Mid: BORDER_STRONG, QPalette.Link: BLUE,
    }.items():
        palette.setColor(role, QColor(colour))
    app.setPalette(palette)
    font = app.font()
    font.setPointSizeF(max(font.pointSizeF(), 10.0))
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)
    app.setStyleSheet(_stylesheet())
