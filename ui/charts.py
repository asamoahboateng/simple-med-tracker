"""
ui/charts.py - matplotlib charts embedded in Qt widgets, styled to match the app.

The backend is set explicitly to QtAgg (works with PySide6).
"""

import calendar
import io
from datetime import timedelta

import matplotlib

matplotlib.use("QtAgg")

import matplotlib.dates as mdates  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from ui import theme  # noqa: E402
from ui.widgets import Card, hint_label  # noqa: E402

BLUE = theme.BLUE
TEAL = theme.PRIMARY
STATUS_BAR_COLOURS = {"OK": theme.GREEN, "LOW": theme.AMBER, "OUT OF STOCK": theme.RED}
TEXT = theme.TEXT
MUTED = theme.TEXT_MUTED
GRID = "#edf0f5"

matplotlib.rcParams.update({
    "font.size": 9,
    "axes.edgecolor": "#d9dfe8",
    "axes.labelcolor": MUTED,
    "xtick.color": MUTED,
    "ytick.color": "#3d4a61",
})


def _shorten(label: str, limit: int = 28) -> str:
    return label if len(label) <= limit else label[: limit - 1] + "…"


class ChartWidget(FigureCanvasQTAgg):
    """A figure with one set of axes and simple plotting helpers."""

    def __init__(self, title: str = "", parent=None, height: float = 3.2):
        self.figure = Figure(figsize=(5, height), layout="constrained", facecolor="white")
        super().__init__(self.figure)
        self.setParent(parent)
        self.title = title          # drawn inside the figure only if given
        self.setMinimumHeight(270)
        self.setStyleSheet("background: transparent;")

    # --- helpers -------------------------------------------------------------
    def _axes(self):
        self.figure.clear()
        ax = self.figure.add_subplot()
        ax.set_facecolor("white")
        if self.title:
            ax.set_title(self.title, loc="left", fontsize=11, color=TEXT, fontweight="bold")
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(length=0, labelsize=8.5, pad=6)
        return ax

    def _empty(self, ax, message="No data yet"):
        ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes,
                color=MUTED, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        self.draw_idle()

    # --- chart types ---------------------------------------------------------
    def plot_barh(self, labels, values, colour=BLUE, empty_message="No data yet"):
        """Horizontal bars, largest at the top; the top bar is highlighted."""
        ax = self._axes()
        if not values:
            return self._empty(ax, empty_message)
        labels = [_shorten(label) for label in labels][::-1]
        values = list(values)[::-1]
        colours = [to_rgba(colour, 0.45)] * (len(values) - 1) + [to_rgba(colour)]  # top = strongest
        bars = ax.barh(range(len(values)), values, color=colours, height=0.62)
        ax.set_yticks(range(len(values)), labels)
        ax.bar_label(bars, labels=[f"{v:,}" for v in values], padding=4, fontsize=8.5,
                     color=TEXT, fontweight="bold")
        ax.margins(x=0.14)
        ax.spines["left"].set_visible(False)
        ax.spines["bottom"].set_visible(False)
        ax.set_xticks([])
        self.draw_idle()

    def plot_bar(self, labels, values, colours=None, empty_message="No data yet"):
        """Vertical bars with rotated labels."""
        ax = self._axes()
        if not values:
            return self._empty(ax, empty_message)
        bars = ax.bar(range(len(values)), values, color=colours or BLUE, width=0.62)
        ax.set_xticks(range(len(values)), [_shorten(label, 18) for label in labels],
                      rotation=40, ha="right", fontsize=8)
        ax.bar_label(bars, labels=[f"{v:,}" for v in values], padding=2, fontsize=7.5,
                     color=TEXT)
        ax.margins(y=0.15)
        ax.grid(axis="y", color=GRID)
        ax.set_axisbelow(True)
        ax.spines["left"].set_visible(False)
        self.draw_idle()

    def plot_daily(self, days, values, empty_message="No data yet"):
        """Line chart with one point per day; the x-axis always spans the whole month."""
        ax = self._axes()
        if not days:
            return self._empty(ax, empty_message)
        ax.fill_between(days, values, color=TEAL, alpha=0.13, linewidth=0)
        ax.plot(days, values, color=TEAL, linewidth=2.2, solid_capstyle="round")
        ax.plot(days, values, "o", color="white", markersize=4.5,
                markeredgecolor=TEAL, markeredgewidth=1.6)
        ax.set_ylim(bottom=0, top=max(max(values) * 1.18, 1))
        first = days[0].replace(day=1)
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        ax.set_xlim(first - timedelta(hours=12), last + timedelta(hours=12))
        ax.xaxis.set_major_locator(mdates.DayLocator(bymonthday=range(1, 32, 3)))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d"))
        ax.set_xlabel(days[0].strftime("%B %Y"), fontsize=8)
        ax.grid(axis="y", color=GRID)
        ax.set_axisbelow(True)
        ax.spines["left"].set_visible(False)
        self.draw_idle()

    def png_bytes(self, dpi: int = 150) -> bytes:
        """The current chart as PNG image data (used for the PDF export)."""
        buffer = io.BytesIO()
        self.figure.savefig(buffer, format="png", dpi=dpi, facecolor="white")
        return buffer.getvalue()


class ChartCard(Card):
    """A card with a title, an optional subtitle and a chart inside."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(title, parent)
        if subtitle:
            self.body.addWidget(hint_label(subtitle))
        self.chart = ChartWidget()
        self.body.addWidget(self.chart, 1)   # the chart takes all spare height

