"""
ui/icons.py - Small line icons drawn from inline SVG, in any colour.

Each icon is the inside of a 24 x 24 SVG, stroked in the colour asked for.
"""

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "dashboard": '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    "log": '<path d="M8 4h11v16H5V7z M8 4v3H5"/><path d="M9 11h7M9 15h7"/>',
    "stock": '<path d="M3 8l9-5 9 5v8l-9 5-9-5z M3 8l9 5 9-5 M12 13v8"/>',
    "report": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "tablet": '<circle cx="12" cy="12" r="8"/><path d="M6.5 17.5l11-11"/>',
    "bottle": '<path d="M9 3h6v3H9z M7 8h10v12a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1z M12 11v6M9 14h6"/>',
    "trend_down": '<path d="M4 6l6 6 4-4 6 7 M20 11v4h-4"/><path d="M3 21h18"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/>'
             '<path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14c2 .7 3 3 3 6"/>',
    "signout": '<path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 17l-5-5 5-5M5 12h11"/>',
    "hourglass": '<path d="M7 3h10M7 21h10M8 3c0 5 8 6 8 9s-8 4-8 9M16 3c0 5-8 6-8 9s8 4 8 9"/>',
}


def _svg(name: str, colour: str, stroke: float) -> bytes:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{colour}" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round">{_PATHS[name]}</svg>').encode()


def pixmap(name: str, colour: str, size: int = 20, stroke: float = 2.0,
           ratio: float = 2.0) -> QPixmap:
    """Render an icon at `size` logical pixels (sharp on HiDPI screens)."""
    renderer = QSvgRenderer(QByteArray(_svg(name, colour, stroke)))
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter, QRectF(0, 0, pm.width(), pm.height()))
    painter.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name: str, colour: str, selected_colour: str | None = None, size: int = 20) -> QIcon:
    """QIcon with an optional different colour when its item is selected."""
    result = QIcon()
    result.addPixmap(pixmap(name, colour, size), QIcon.Normal, QIcon.Off)
    if selected_colour:
        result.addPixmap(pixmap(name, selected_colour, size), QIcon.Selected, QIcon.Off)
        result.addPixmap(pixmap(name, selected_colour, size), QIcon.Selected, QIcon.On)
    return result


def badge(name: str, colour: str, background: str, size: int = 36, ratio: float = 2.0) -> QPixmap:
    """The icon centred on a rounded, tinted square (used on the summary cards)."""
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(background))
    painter.drawRoundedRect(QRectF(0, 0, pm.width(), pm.height()), 9 * ratio, 9 * ratio)
    inner = size * 0.62
    offset = (size - inner) / 2 * ratio
    QSvgRenderer(QByteArray(_svg(name, colour, 2.0))).render(
        painter, QRectF(offset, offset, inner * ratio, inner * ratio))
    painter.end()
    pm.setDevicePixelRatio(ratio)
    return pm
