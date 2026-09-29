"""ui/widgets.py - Small shared widgets and message-box helpers."""

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QBoxLayout, QComboBox, QCompleter, QDateEdit, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ui import theme
from ui.responsive import FlowLayout


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

def to_py_date(qdate: QDate) -> date:
    return date(qdate.year(), qdate.month(), qdate.day())


def to_qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def make_date_edit(value: date | None = None, max_today: bool = False) -> QDateEdit:
    """A date field with a pop-up calendar and an unambiguous YYYY-MM-DD format."""
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy-MM-dd")
    if max_today:
        edit.setMaximumDate(to_qdate(date.today()))
    edit.setDate(to_qdate(value or date.today()))
    return edit


class OptionalDateEdit(QDateEdit):
    """
    A date field that starts EMPTY (shows "Select date") so the user must
    choose a date. Clicking or tabbing into it jumps to today first.
    """

    EMPTY = QDate(2000, 1, 1)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd")
        self.setMinimumDate(self.EMPTY)
        self.setMaximumDate(QDate(2100, 12, 31))
        self.setSpecialValueText("Select date")
        self.clear_date()

    def clear_date(self):
        self.setDate(self.EMPTY)

    def is_empty(self) -> bool:
        return self.date() == self.EMPTY

    def value(self) -> date | None:
        return None if self.is_empty() else to_py_date(self.date())

    def _start_at_today(self):
        if self.is_empty():
            self.setDate(QDate.currentDate())

    def mousePressEvent(self, event):
        self._start_at_today()
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        if event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason):
            self._start_at_today()
        super().focusInEvent(event)


# --------------------------------------------------------------------------
# Combo boxes with type-ahead
# --------------------------------------------------------------------------

class SearchComboBox(QComboBox):
    """
    Editable combo box with autocomplete that matches anywhere in the text,
    ignoring upper/lower case. Typing a new value is allowed.
    """

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(20)
        self.lineEdit().setPlaceholderText(placeholder)
        completer = QCompleter(self.model(), self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(completer)

    def set_items(self, items: list[str], keep_text: bool = True) -> None:
        text = self.currentText()
        self.blockSignals(True)
        self.clear()
        self.addItems(items)
        self.setCurrentIndex(-1)
        self.setEditText(text if keep_text else "")
        self.blockSignals(False)

    def text(self) -> str:
        return self.currentText().strip()


# --------------------------------------------------------------------------
# Cards, headers and buttons (styled by ui/theme.py)
# --------------------------------------------------------------------------

def add_shadow(widget, blur: int = 24, alpha: int = 22) -> None:
    """Soft drop shadow that lifts a card off the background."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 3)
    effect.setColor(QColor(15, 33, 57, alpha))
    widget.setGraphicsEffect(effect)


class Card(QFrame):
    """A white rounded panel. Put content in card.body (a QVBoxLayout)."""

    def __init__(self, title: str = "", parent=None, margins: int = 16):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margins, margins, margins, margins)
        self.body.setSpacing(10)
        self.header = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("sectionTitle")
        self.header.addWidget(self.title_label)
        self.header.addStretch()
        if title:
            self.body.addLayout(self.header)


class SummaryCard(QFrame):
    """
    A KPI tile: small title, big number, optional note and a coloured icon badge.

    It adapts to its own width: the number gets smaller and the icon badge is
    hidden when the card is narrow, so nothing is cut off.
    """

    def __init__(self, title: str, accent: str = theme.BLUE, icon: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumHeight(104)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        add_shadow(self)
        self.setStyleSheet(f"QFrame#card {{ border-top: 4px solid {accent}; }}")

        text = QVBoxLayout()
        text.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.title_label.setWordWrap(True)
        self.value_label = QLabel("-")
        self.value_label.setObjectName("cardValue")
        self.note_label = QLabel("")
        self.note_label.setObjectName("cardNote")
        self.note_label.setWordWrap(True)
        self.note_label.setVisible(False)
        for label in (self.title_label, self.value_label, self.note_label):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text.addWidget(self.title_label)
        text.addWidget(self.value_label)
        text.addWidget(self.note_label)
        text.addStretch()

        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(18, 14, 16, 14)
        self.layout_.addLayout(text, 1)
        self.badge = None
        if icon:
            self.badge = QLabel(icon)
            self.badge.setFixedSize(44, 44)
            self.badge.setAlignment(Qt.AlignCenter)
            self.badge.setStyleSheet(f"background: {theme.tint(accent, 0.14)}; border-radius: 12px;"
                                     f" font-size: 20px;")
            self.layout_.addWidget(self.badge, 0, Qt.AlignTop)
        self._size_class = None

    def set_value(self, value, note: str = "") -> None:
        self.value_label.setText(f"{value:,}" if isinstance(value, int) else str(value))
        self.note_label.setText(note)
        self.note_label.setVisible(bool(note))

    def resizeEvent(self, event):
        width = event.size().width()
        size_class = "wide" if width >= 240 else "medium" if width >= 185 else "narrow"
        if size_class != self._size_class:
            self._size_class = size_class
            value_px = {"wide": 30, "medium": 25, "narrow": 22}[size_class]
            self.value_label.setStyleSheet(f"font-size: {value_px}px;")
            margin = 18 if size_class == "wide" else 12
            self.layout_.setContentsMargins(margin, 14, margin - 2, 14)
            if self.badge is not None:
                self.badge.setVisible(size_class != "narrow")
        super().resizeEvent(event)


def make_button(text: str, kind: str = "", large: bool = False, icon_text: str = "") -> QPushButton:
    """Button styled by the theme. kind: "", "primary", "blue" or "danger"."""
    button = QPushButton(f"{icon_text}  {text}" if icon_text else text)
    if kind:
        button.setProperty("kind", kind)
    if large:
        button.setProperty("size", "large")
    button.setCursor(Qt.PointingHandCursor)
    return button


class PageHeader(QWidget):
    """
    Big page title with a grey subtitle and optional action widgets.
    The actions sit on the right when there is room, otherwise they wrap
    underneath the title.
    """

    def __init__(self, title: str, subtitle: str = "", *actions):
        super().__init__()
        self.texts = QWidget()
        text_layout = QVBoxLayout(self.texts)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("pageSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setMinimumWidth(0)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)

        self.actions = QWidget()
        action_layout = FlowLayout(self.actions, spacing=8)
        for widget in actions:
            action_layout.addWidget(widget)

        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 6)
        self.box.setSpacing(12)
        self.box.addWidget(self.texts, 1)
        self.box.addWidget(self.actions, 0, Qt.AlignVCenter)
        self.actions.setVisible(bool(actions))

    def _actions_width(self) -> int:
        layout = self.actions.layout()
        widths = [layout.itemAt(i).sizeHint().width() for i in range(layout.count())]
        return sum(widths) + 8 * max(len(widths) - 1, 0)

    def resizeEvent(self, event):
        needed = self.title_label.sizeHint().width() + 260 + self._actions_width()
        stacked = event.size().width() < needed
        direction = QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight
        if self.box.direction() != direction:
            self.box.setDirection(direction)
            self.box.setAlignment(self.actions, Qt.AlignLeft if stacked else Qt.AlignVCenter)
        super().resizeEvent(event)


def page_header(title: str, subtitle: str = "", *right_widgets) -> PageHeader:
    return PageHeader(title, subtitle, *right_widgets)


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def hint_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def scrolling_page(content: QWidget) -> QScrollArea:
    """Wrap page content so it scrolls on small screens."""
    content.setObjectName("pageContent")
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setWidget(content)
    return scroll


def page_layout(widget: QWidget) -> QVBoxLayout:
    """Standard page margins and spacing."""
    widget.setObjectName("page")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(28, 22, 28, 22)
    layout.setSpacing(16)
    return layout


def dialog_header(title: str, subtitle: str, icon: str, accent: str) -> QWidget:
    """Coloured header strip at the top of a data-entry dialog."""
    box = QFrame()
    box.setStyleSheet(f"QFrame {{ background: {theme.tint(accent, 0.10)}; border-radius: 12px; }}"
                      f" QLabel {{ background: transparent; }}")
    row = QHBoxLayout(box)
    row.setContentsMargins(14, 12, 14, 12)
    badge = QLabel(icon)
    badge.setFixedSize(40, 40)
    badge.setAlignment(Qt.AlignCenter)
    badge.setStyleSheet(f"background: {accent}; border-radius: 10px; font-size: 20px;"
                        f" font-weight: 700; color: white;")
    texts = QVBoxLayout()
    texts.setSpacing(0)
    title_label = QLabel(title)
    title_label.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {theme.TEXT};")
    sub = QLabel(subtitle)
    sub.setStyleSheet(f"color: {theme.TEXT_MUTED};")
    sub.setWordWrap(True)
    texts.addWidget(title_label)
    texts.addWidget(sub)
    row.addWidget(badge)
    row.addLayout(texts, 1)
    return box


def style_dialog_buttons(buttons) -> None:
    """Make the Save button of a QDialogButtonBox the primary (teal) button."""
    from PySide6.QtWidgets import QDialogButtonBox
    save = buttons.button(QDialogButtonBox.Save)
    if save is not None:
        save.setProperty("kind", "primary")
        save.setCursor(Qt.PointingHandCursor)
        save.setMinimumWidth(110)


# --------------------------------------------------------------------------
# Friendly message boxes
# --------------------------------------------------------------------------

def show_error(parent, message: str, title: str = "Please check") -> None:
    QMessageBox.warning(parent, title, message)


def show_info(parent, message: str, title: str = "Saved") -> None:
    QMessageBox.information(parent, title, message)


def ask_yes_no(parent, message: str, title: str = "Please confirm",
               yes_text: str = "Yes", no_text: str = "No") -> bool:
    box = QMessageBox(QMessageBox.Question, title, message, parent=parent)
    yes = box.addButton(yes_text, QMessageBox.YesRole)
    box.addButton(no_text, QMessageBox.NoRole)
    box.exec()
    return box.clickedButton() is yes
