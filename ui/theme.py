"""
ui/theme.py - The MedTracker look: colour palette and one global Qt stylesheet.

Widgets opt into styles with setObjectName(...) or a "kind" property, e.g.
    button.setProperty("kind", "primary")
so page code stays free of colour details.
"""

import re

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from config import resource_path

# --- palette -------------------------------------------------------------
# The brand colours (sidebar, buttons, text, background) come from the chosen preset,
# see PRESETS below. Status colours never change, so red, amber and green always mean
# expired / out of stock, expiring soon / low, and OK.
SURFACE = "#ffffff"       # cards, tables, inputs
BLUE = "#3867d6"
BLUE_HOVER = "#2c55b8"
AMBER = "#b86e00"         # expiring soon / low (fills)
AMBER_TEXT = "#8a5200"    # amber that is readable as text on white
AMBER_TINT = "#f7ebd6"
RED = "#b83227"           # expired / out of stock
RED_TINT = "#f8e3e0"
PURPLE = "#7c5cd6"
GREEN = "#3e7a5a"         # OK

# Each preset: an accent, the sidebar and its hover / border / text shades, and main text.
# The page background, hovers, table headers, scrollbars and focus rings are tinted from
# the accent (see set_preset), so a preset recolours the whole window, not just the sidebar.
# Every pair used together has at least 4.5:1 contrast.
PRESETS = {
    "Bottle green": dict(
        ACCENT="#2e7d62", NAVY="#14332c", NAVY_HOVER="#1e463d", SIDEBAR_TEXT="#c9d8d3", SIDEBAR_MUTED="#a9bdb6",
        SIDEBAR_BORDER="#3a5e55", SIDEBAR_ACTIVE="#285a4e", TEXT="#14332c", TEXT_MUTED="#4e635d",
        BORDER="#dde5e2", BORDER_STRONG="#c9d4d0", RULE="#e4eae8", SHELF="#d5dedb",
        BADGE_BG="#e2ebe8"),
    "Navy": dict(
        ACCENT="#2c5aa0", NAVY="#0f2139", NAVY_HOVER="#1a3354", SIDEBAR_TEXT="#c6d2e3", SIDEBAR_MUTED="#8ea3bf",
        SIDEBAR_BORDER="#2b4a73", SIDEBAR_ACTIVE="#22406a", TEXT="#14213d", TEXT_MUTED="#4f5d75",
        BORDER="#dfe5ee", BORDER_STRONG="#cbd4e1", RULE="#e5eaf1", SHELF="#d4dce8",
        BADGE_BG="#e1e8f3"),
    "Ocean blue": dict(
        ACCENT="#2f6fc0", NAVY="#173b6c", NAVY_HOVER="#22508e", SIDEBAR_TEXT="#d3e0f2", SIDEBAR_MUTED="#a7bddd",
        SIDEBAR_BORDER="#3a65a0", SIDEBAR_ACTIVE="#2b5c9e", TEXT="#142c4f", TEXT_MUTED="#4a5d78",
        BORDER="#dce4ef", BORDER_STRONG="#c7d3e3", RULE="#e3e9f2", SHELF="#d1dbe9",
        BADGE_BG="#dfe8f5"),
    "Teal": dict(
        ACCENT="#1d8090", NAVY="#0f3d44", NAVY_HOVER="#17525b", SIDEBAR_TEXT="#cde2e4", SIDEBAR_MUTED="#9cc0c4",
        SIDEBAR_BORDER="#2f6b73", SIDEBAR_ACTIVE="#1f6670", TEXT="#11353b", TEXT_MUTED="#4a6367",
        BORDER="#dbe6e8", BORDER_STRONG="#c5d6d9", RULE="#e2ebec", SHELF="#d0dfe1",
        BADGE_BG="#dcebed"),
    "Plum": dict(
        ACCENT="#8a4a92", NAVY="#3b1f3f", NAVY_HOVER="#4f2c54", SIDEBAR_TEXT="#e2d3e4", SIDEBAR_MUTED="#bfa6c2",
        SIDEBAR_BORDER="#6b4870", SIDEBAR_ACTIVE="#5f3964", TEXT="#2e1a31", TEXT_MUTED="#5f4e63",
        BORDER="#e6dee7", BORDER_STRONG="#d5c8d7", RULE="#ebe4ec", SHELF="#ddd2df",
        BADGE_BG="#ece2ed"),
    "Charcoal": dict(
        ACCENT="#5a6372", NAVY="#23272e", NAVY_HOVER="#333943", SIDEBAR_TEXT="#d3d7de", SIDEBAR_MUTED="#a4aab4",
        SIDEBAR_BORDER="#4a515d", SIDEBAR_ACTIVE="#3f4651", TEXT="#1f2329", TEXT_MUTED="#545b66",
        BORDER="#e0e2e6", BORDER_STRONG="#cdd1d7", RULE="#e6e8eb", SHELF="#d6d9de",
        BADGE_BG="#e4e6ea"),
}
DEFAULT_PRESET = "Bottle green"
current_preset = DEFAULT_PRESET


def set_preset(name: str) -> None:
    """Switch the brand colours. Widgets created afterwards use the new colours."""
    global current_preset
    if name not in PRESETS:
        name = DEFAULT_PRESET
    current_preset = name
    globals().update(PRESETS[name])
    accent = PRESETS[name]["ACCENT"]
    globals().update(
        PRIMARY=NAVY, PRIMARY_HOVER=NAVY_HOVER, FOCUS=accent,
        BG=_wash(accent, 0.10), HOVER_BG=_wash(accent, 0.10), PRESSED_BG=_wash(accent, 0.18),
        HEADER_BG=_wash(accent, 0.12), ALT_ROW=_wash(accent, 0.035), ROW_RULE=_wash(accent, 0.08),
        DISABLED_BG=_wash(accent, 0.06), SCROLL=_wash(accent, 0.35), SCROLL_HOVER=_wash(accent, 0.5))


def _wash(colour: str, amount: float) -> str:
    """`colour` mixed into white: amount 0 is white, 1 is the colour itself."""
    c = QColor(colour)
    return "#" + "".join(f"{round(255 + (v - 255) * amount):02x}" for v in (c.red(), c.green(), c.blue()))


set_preset(DEFAULT_PRESET)



def _settings() -> QSettings:
    return QSettings("MedTracker", "MedTracker")


def saved_preset() -> str:
    return str(_settings().value("appearance/theme", DEFAULT_PRESET))


def save_preset(name: str) -> None:
    _settings().setValue("appearance/theme", name)


# --- zoom ------------------------------------------------------------------
# Scales text, padding and row heights so the app fits small screens (zoom out)
# or is easier to read (zoom in). Charts keep their drawn size.
ZOOM_LEVELS = (0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6)
zoom = 1.0


def px(size: float) -> int:
    """A pixel size at the current zoom (never below 1 for a non-zero size)."""
    return max(1, round(size * zoom)) if size else 0


def saved_zoom() -> float:
    try:
        value = float(_settings().value("appearance/zoom", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return value if value in ZOOM_LEVELS else 1.0


def set_zoom(value: float) -> None:
    """Set and remember the zoom. Widgets created afterwards use it."""
    global zoom
    zoom = value if value in ZOOM_LEVELS else 1.0
    _settings().setValue("appearance/zoom", zoom)


def step_zoom(steps: int) -> float:
    """The zoom level `steps` places bigger (+) or smaller (-) than the current one."""
    i = ZOOM_LEVELS.index(zoom) if zoom in ZOOM_LEVELS else ZOOM_LEVELS.index(1.0)
    return ZOOM_LEVELS[min(max(i + steps, 0), len(ZOOM_LEVELS) - 1)]


FONT_FAMILY = "Atkinson Hyperlegible Next"   # bundled in resources/fonts (OFL licence)


def tint(hex_colour: str, alpha: float) -> str:
    """rgba() string of a colour at the given opacity (for soft backgrounds)."""
    c = QColor(hex_colour)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {int(alpha * 255)})"


def _stylesheet() -> str:
    down = resource_path("resources/chevron-down.svg").as_posix()
    up = resource_path("resources/chevron-up.svg").as_posix()
    check = resource_path("resources/check.svg").as_posix()
    return _zoomed(f"""
    QWidget {{ color: {TEXT}; }}
    QMainWindow, QWidget#page, QWidget#pageContent, QScrollArea, QScrollArea > QWidget > QWidget
        {{ background: {BG}; }}
    QDialog {{ background: {BG}; }}

    /* ---------- sidebar ---------- */
    QWidget#sidebar, QScrollArea#sidebarScroll {{ background: {NAVY}; }}
    QWidget#sidebar QLabel {{ background: transparent; }}
    QLabel#brandTitle {{ color: white; font-size: 19px; font-weight: 700; }}
    QLabel#brandSub {{ color: {SIDEBAR_MUTED}; font-size: 12px; }}
    QLabel#navCaption {{ color: {SIDEBAR_MUTED}; font-size: 12px; font-weight: 700; padding-left: 20px; }}
    QListWidget#nav {{ background: transparent; border: none; outline: 0;
                       color: {SIDEBAR_TEXT}; font-size: 14px; }}
    QListWidget#nav::item {{ padding: 10px 12px; margin: 2px 12px; border-radius: 8px; }}
    QListWidget#nav::item:hover {{ background: {NAVY_HOVER}; color: white; }}
    QListWidget#nav::item:selected {{ background: white; color: {TEXT}; font-weight: 700; }}
    QPushButton#sideAction {{ background: {NAVY_HOVER}; color: white; border: 1px solid {SIDEBAR_BORDER};
                              border-radius: 8px; padding: 10px 12px; text-align: left;
                              font-weight: 700; margin: 0 12px; }}
    QPushButton#sideAction:hover {{ background: {SIDEBAR_ACTIVE}; border-color: {SIDEBAR_MUTED}; }}
    QLabel#demoBadge {{ background: {tint(AMBER, 0.18)}; color: #f3c56b; border-radius: 6px;
                        padding: 6px 8px; font-size: 11px; font-weight: 700; margin: 0 10px; }}
    QLabel#versionLabel {{ color: {SIDEBAR_MUTED}; font-size: 12px; padding-left: 20px; }}

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

    /* ---------- dashboard ---------- */
    QFrame#panel {{ background: {SURFACE}; border: none; border-radius: 12px; }}
    QFrame#panel QLabel, QWidget#panelCell QLabel {{ background: transparent; }}
    QLabel#dashTitle {{ font-size: 30px; font-weight: 800; color: {TEXT}; }}
    QLabel#sectionHeading {{ font-size: 21px; font-weight: 800; color: {TEXT}; }}
    QLabel#panelHeading {{ font-size: 19px; font-weight: 800; color: {TEXT}; }}
    QLabel#groupHeading {{ font-size: 17px; font-weight: 700; color: {TEXT}; }}
    QLabel#muted {{ color: {TEXT_MUTED}; }}
    QLabel#statLabel {{ color: {TEXT_MUTED}; font-size: 13px; font-weight: 700; }}
    QLabel#statValue {{ color: {TEXT}; font-size: 30px; font-weight: 800; }}
    QLabel#statNote {{ color: {TEXT_MUTED}; font-size: 12px; }}
    QLabel#sampleTag {{ color: {TEXT_MUTED}; border: 1px dashed #9aaaa5; border-radius: 6px;
                        padding: 1px 8px; font-size: 12px; }}
    QPushButton[kind="link"] {{ background: transparent; border: none; padding: 6px 0;
                                color: {TEXT}; font-weight: 700; text-decoration: underline;
                                text-align: left; }}
    QPushButton[kind="link"]:hover {{ color: {FOCUS}; }}
    QPushButton[kind="outline"] {{ background: transparent; border: 2px solid {TEXT}; color: {TEXT};
                                   font-weight: 700; }}
    QPushButton[kind="outline"]:hover {{ background: {tint(TEXT, 0.06)}; }}

    /* ---------- report period controls ---------- */
    QFrame#segmentBox {{ background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; }}
    QPushButton[kind="segment"] {{ background: transparent; border: none; border-radius: 6px;
                                   padding: 8px 16px; font-weight: 700; color: {TEXT}; }}
    QPushButton[kind="segment"]:checked {{ background: {NAVY}; color: white; }}
    QPushButton[kind="chip"] {{ background: {SURFACE}; border: 2px solid {BORDER_STRONG};
                                border-radius: 18px; padding: 7px 14px; font-weight: 700; }}
    QPushButton[kind="chip"]:hover {{ border-color: {TEXT_MUTED}; }}
    QPushButton[kind="chip"]:checked {{ background: {NAVY}; border-color: {NAVY}; color: white; }}
    QPushButton[kind="stepper"] {{ background: transparent; border: none; padding: 6px 12px;
                                   font-size: 18px; font-weight: 800; color: {TEXT}; }}
    QPushButton[kind="stepper"]:hover {{ background: {BG}; }}
    QPushButton[kind="stepper"]:disabled {{ color: {BORDER_STRONG}; }}
    QLabel#errorText {{ color: {RED}; font-weight: 700; }}
    QLabel#caption {{ color: {TEXT}; }}

    /* ---------- buttons ---------- */
    QPushButton {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER_STRONG};
                   border-radius: 8px; padding: 7px 16px; font-weight: 600; }}
    QPushButton:hover {{ background: {HOVER_BG}; border-color: {SCROLL}; }}
    QPushButton:pressed {{ background: {PRESSED_BG}; }}
    QPushButton:default {{ border-color: {PRIMARY}; }}
    QPushButton[kind="primary"] {{ background: {PRIMARY}; color: white; border: none; }}
    QPushButton[kind="primary"]:hover {{ background: {PRIMARY_HOVER}; }}
    QPushButton[kind="blue"] {{ background: {BLUE}; color: white; border: none; }}
    QPushButton[kind="blue"]:hover {{ background: {BLUE_HOVER}; }}
    QPushButton[kind="danger"] {{ color: {RED}; border-color: {tint(RED, 0.35)}; }}
    QPushButton[kind="danger"]:hover {{ background: {tint(RED, 0.08)}; }}
    QPushButton:disabled, QPushButton[kind="danger"]:disabled, QPushButton[kind="primary"]:disabled,
    QPushButton[kind="outline"]:disabled
        {{ background: {SURFACE}; color: #9aa5b5; border: 1px solid {BORDER}; }}
    QPushButton[size="large"] {{ padding: 11px 22px; font-size: 14px; border-radius: 10px; }}

    /* ---------- keyboard focus ---------- */
    QPushButton:focus, QPushButton[kind="danger"]:focus, QPushButton[kind="outline"]:focus,
    QPushButton[kind="chip"]:focus {{ border-color: {FOCUS}; }}
    QPushButton[kind="primary"]:focus, QPushButton[kind="blue"]:focus, QPushButton[kind="link"]:focus,
    QPushButton[kind="segment"]:focus, QPushButton[kind="stepper"]:focus,
    QPushButton#sideAction:focus {{ text-decoration: underline; }}
    QPushButton#sideAction:focus {{ border-color: white; }}
    QTableView {{ outline: 0; }}          /* the row highlight marks the current row */
    QTableView:focus {{ border: 1.5px solid {PRIMARY}; }}
    QCheckBox:focus {{ text-decoration: underline; }}
    QCheckBox::indicator:focus {{ border: 1.5px solid {PRIMARY}; }}
    QListWidget#nav:focus {{ border-left: 3px solid white; }}

    /* ---------- inputs ---------- */
    QLineEdit, QComboBox, QSpinBox, QDateEdit {{
        background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
        padding: 6px 10px; min-height: 20px; selection-background-color: {tint(PRIMARY, 0.3)};
        selection-color: {TEXT}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus
        {{ border: 1.5px solid {PRIMARY}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDateEdit:disabled
        {{ background: {DISABLED_BG}; color: #9aa5b5; }}
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
    QTableView {{ background: {SURFACE}; alternate-background-color: {ALT_ROW};
                  border: 1px solid {BORDER}; border-radius: 12px; gridline-color: transparent;
                  selection-background-color: {tint(PRIMARY, 0.14)}; selection-color: {TEXT}; }}
    QTableView::item {{ padding: 0 8px; border-bottom: 1px solid {ROW_RULE}; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{ background: {HEADER_BG}; color: {TEXT_MUTED}; font-weight: 700; font-size: 12px;
                            border: none; border-bottom: 1px solid {BORDER}; padding: 9px 8px; }}
    QHeaderView::section:first {{ border-top-left-radius: 12px; }}
    QHeaderView::section:last {{ border-top-right-radius: 12px; }}
    QTableCornerButton::section {{ background: {HEADER_BG}; border: none; }}


    /* ---------- misc ---------- */
    QSplitter::handle {{ background: transparent; height: 10px; }}
    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {SCROLL}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {SCROLL_HOVER}; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {SCROLL}; border-radius: 4px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollArea#sidebarScroll QScrollBar::handle:vertical {{ background: {SIDEBAR_BORDER}; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QStatusBar {{ background: {HEADER_BG}; border-top: 1px solid {BORDER}; color: {TEXT_MUTED}; }}
    QStatusBar QLabel {{ color: {TEXT_MUTED}; padding: 2px 6px; }}
    QMenuBar {{ background: {HEADER_BG}; border-bottom: 1px solid {BORDER}; }}
    QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
    QMenuBar::item:selected {{ background: {tint(PRIMARY, 0.12)}; border-radius: 4px; }}
    QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px; }}
    QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {tint(PRIMARY, 0.12)}; color: {TEXT}; }}
    QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
    QToolTip {{ background: {NAVY}; color: white; border: none; padding: 6px 8px; border-radius: 4px; }}
    QMessageBox {{ background: {SURFACE}; }}
    QCalendarWidget QWidget {{ alternate-background-color: {HEADER_BG}; }}
    QCalendarWidget QToolButton {{ color: {TEXT}; background: transparent; font-weight: 600; }}
    """)


def _zoomed(css: str) -> str:
    """Scale every pixel size in a stylesheet by the current zoom."""
    return re.sub(r"(?<![\d.])(\d+)px", lambda m: f"{px(int(m.group(1)))}px", css)


def apply_theme(app: QApplication, preset: str | None = None) -> None:
    """
    Apply the light MedTracker theme (same look on every OS, even in dark mode), in the
    given colour preset, or the one saved last time.
    """
    set_preset(preset or saved_preset())
    global zoom
    zoom = saved_zoom()
    app.setStyle("Fusion")
    palette = QPalette()
    for role, colour in {
        QPalette.Window: BG, QPalette.WindowText: TEXT, QPalette.Base: SURFACE,
        QPalette.AlternateBase: ALT_ROW, QPalette.Text: TEXT, QPalette.Button: SURFACE,
        QPalette.ButtonText: TEXT, QPalette.Highlight: PRIMARY, QPalette.HighlightedText: "#ffffff",
        QPalette.ToolTipBase: NAVY, QPalette.ToolTipText: "#ffffff",
        QPalette.PlaceholderText: "#9aa5b5", QPalette.Mid: BORDER_STRONG, QPalette.Link: BLUE,
    }.items():
        palette.setColor(role, QColor(colour))
    app.setPalette(palette)
    font = app.font()
    if _load_font():
        font.setFamily(FONT_FAMILY)
    if not hasattr(app, "_base_point_size"):     # the size before any zoom
        app._base_point_size = max(font.pointSizeF(), 10.0)
    font.setPointSizeF(app._base_point_size * zoom)
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)
    app.setStyleSheet(_stylesheet())


def _load_font() -> bool:
    """Register the bundled Atkinson Hyperlegible Next. False if it can't be loaded."""
    path = resource_path("resources/fonts/AtkinsonHyperlegibleNext.ttf")
    return path.exists() and QFontDatabase.addApplicationFont(str(path)) != -1
