"""Matplotlib Chart-Widget für GTK4."""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
import matplotlib
matplotlib.use("GTK4Agg")
from matplotlib.backends.backend_gtk4agg import FigureCanvasGTK4Agg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from lotto_common.utils.logging_config import get_logger

logger = get_logger("chart_view")


class _SafeFigureCanvas(FigureCanvas):
    """FigureCanvas mit Schutz gegen zero-size array bei leerem Chart.

    matplotlib's interner _draw_func Callback kann ValueError werfen wenn
    die Figure keine Pixel hat (z.B. beim ersten Layout bevor Daten da sind).
    """

    def on_draw_event(self, widget, ctx):
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                super().on_draw_event(widget, ctx)
        except (ValueError, RuntimeError):
            pass  # Empty chart — will be redrawn with data


class ChartView(Gtk.Box):
    """Einbettbares Matplotlib-Chart in GTK4."""
    def __init__(self, title="", figsize=(8, 4)):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.figure = Figure(figsize=figsize, dpi=100)
        self.figure.set_tight_layout(True)
        self.ax = self.figure.add_subplot(111)
        self.canvas = _SafeFigureCanvas(self.figure)
        self.canvas.set_vexpand(True)
        self.canvas.set_hexpand(True)
        self.append(self.canvas)
        if title:
            self.ax.set_title(title)

    def _safe_draw(self) -> None:
        """Canvas zeichnen mit Schutz gegen zero-size array Fehler."""
        try:
            self.canvas.draw()
        except (ValueError, RuntimeError) as e:
            logger.debug(f"Chart draw fehlgeschlagen: {e}")

    def plot_bar(self, x_values, y_values, title="", xlabel="", ylabel="",
                 color="#3584e4", highlight_indices=None):
        self.ax.clear()
        if not x_values or not y_values:
            self.ax.set_title(title or "Keine Daten")
            self._safe_draw()
            return
        colors = [color] * len(x_values)
        if highlight_indices:
            for i in highlight_indices:
                if 0 <= i < len(colors):
                    colors[i] = "#e01b24"
        self.ax.bar(x_values, y_values, color=colors, edgecolor="none", width=0.8)
        if title: self.ax.set_title(title, fontsize=12, fontweight="bold")
        if xlabel: self.ax.set_xlabel(xlabel)
        if ylabel: self.ax.set_ylabel(ylabel)
        self.ax.tick_params(axis='x', rotation=45 if len(x_values) > 20 else 0)
        self._safe_draw()

    def plot_line(self, x_values, y_values, title="", xlabel="", ylabel="",
                  color="#3584e4", label=None):
        self.ax.clear()
        self.ax.plot(x_values, y_values, color=color, linewidth=2,
                     marker="o", markersize=3, label=label)
        if title: self.ax.set_title(title, fontsize=12, fontweight="bold")
        if xlabel: self.ax.set_xlabel(xlabel)
        if ylabel: self.ax.set_ylabel(ylabel)
        if label: self.ax.legend()
        self.ax.grid(True, alpha=0.3)
        self._safe_draw()

    def plot_hot_cold(self, frequencies, hot_numbers, cold_numbers,
                      title="Hot/Cold Zahlen"):
        self.ax.clear()
        if not frequencies:
            self.ax.set_title(title)
            self._safe_draw()
            return
        numbers = [f.number for f in frequencies]
        counts = [f.count for f in frequencies]
        colors = []
        for f in frequencies:
            if f.number in hot_numbers:
                colors.append("#e01b24")
            elif f.number in cold_numbers:
                colors.append("#1c71d8")
            else:
                colors.append("#a0a0a0")
        self.ax.bar(numbers, counts, color=colors, edgecolor="none", width=0.8)
        self.ax.set_title(title, fontsize=12, fontweight="bold")
        self.ax.set_xlabel("Zahl")
        self.ax.set_ylabel("Häufigkeit")
        legend = [Patch(facecolor="#e01b24", label="Hot"),
                  Patch(facecolor="#1c71d8", label="Cold"),
                  Patch(facecolor="#a0a0a0", label="Normal")]
        self.ax.legend(handles=legend, loc="upper right")
        self._safe_draw()

    def plot_super_number(self, freq_data, title="Superzahl-Häufigkeit"):
        self.ax.clear()
        if not freq_data:
            self.ax.set_title(title)
            self.ax.text(0.5, 0.5, "Keine Daten", ha="center", va="center",
                         transform=self.ax.transAxes, fontsize=14, color="#888")
            self._safe_draw()
            return
        numbers = [f.number for f in freq_data]
        counts = [f.count for f in freq_data]
        max_count = max(counts) if counts else 0
        colors = ["#26a269" if c == max_count and max_count > 0 else "#3584e4" for c in counts]
        self.ax.bar(numbers, counts, color=colors, edgecolor="none", width=0.6)
        self.ax.set_title(title, fontsize=12, fontweight="bold")
        self.ax.set_xlabel("Superzahl")
        self.ax.set_ylabel("Häufigkeit")
        self.ax.set_xticks(range(10))
        self._safe_draw()

    def plot_pairs(self, pair_data, title="Häufigste Zahlenpaare", top_n=20):
        self.ax.clear()
        if not pair_data:
            self.ax.set_title(title)
            self._safe_draw()
            return
        pairs = pair_data[:top_n]
        labels = [f"{p.number_a}-{p.number_b}" for p in pairs]
        counts = [p.count for p in pairs]
        y_pos = range(len(labels))
        self.ax.barh(y_pos, counts, color="#3584e4", edgecolor="none")
        self.ax.set_yticks(y_pos)
        self.ax.set_yticklabels(labels, fontsize=8)
        self.ax.set_title(title, fontsize=12, fontweight="bold")
        self.ax.set_xlabel("Häufigkeit")
        self.ax.invert_yaxis()
        self._safe_draw()

    def plot_trends(self, trend_data, title="Trends (Momentum)"):
        self.ax.clear()
        if not trend_data:
            self.ax.set_title(title)
            self._safe_draw()
            return
        numbers = [t.number for t in trend_data]
        momentums = [t.momentum * 100 for t in trend_data]
        colors = ["#26a269" if m > 0 else "#e01b24" if m < -0.5
                  else "#a0a0a0" for m in momentums]
        self.ax.bar(numbers, momentums, color=colors, edgecolor="none", width=0.8)
        self.ax.set_title(title, fontsize=12, fontweight="bold")
        self.ax.set_xlabel("Zahl")
        self.ax.set_ylabel("Momentum (%)")
        self.ax.axhline(y=0, color="black", linewidth=0.5)
        self.ax.grid(True, alpha=0.3, axis="y")
        self._safe_draw()

    def clear(self):
        self.ax.clear()
        self._safe_draw()
