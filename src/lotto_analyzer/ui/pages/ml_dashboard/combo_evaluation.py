"""ML-Dashboard: Modell-Kombinationen."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("ml_dashboard.combo")


class ComboEvaluationMixin:
    """Modell-Kombinationen Vergleich."""

    def _build_combo_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Modell-Kombinationen"),
            description=_("Welche Kombination von RF/GB/LSTM performt am besten?"),
        )
        content.append(group)

        try:
            from lotto_analyzer.ui.widgets.chart_view import ChartView
            self._chart_combo = ChartView(figsize=(10, 3.5))
            group.add(self._chart_combo)
        except Exception as e:
            logger.debug(f"ChartView (Combo) initialisieren fehlgeschlagen: {e}")
            self._chart_combo = None

        self._combo_list = Gtk.ListBox()
        self._combo_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._combo_list.add_css_class("boxed-list")
        group.add(self._combo_list)
        self._combo_rows: list = []

    def _update_combo_evaluation(self, data: dict) -> None:
        combos = data.get("combo_perf", [])

        # Chart
        if self._chart_combo:
            self._chart_combo.ax.clear()
            if combos:
                sorted_c = sorted(combos, key=lambda c: c.get("avg_matches", 0), reverse=True)
                keys = [c.get("combo_key", "?")[:15] for c in sorted_c]
                avgs = [c.get("avg_matches", 0) for c in sorted_c]
                colors = ["#26a269" if i == 0 else "#3584e4" for i in range(len(keys))]

                self._chart_combo.ax.bar(keys, avgs, color=colors, edgecolor="none")
                self._chart_combo.ax.set_title(_("Ø Treffer pro Modell-Kombination"),
                                                fontsize=12, fontweight="bold")
                self._chart_combo.ax.set_ylabel(_("Ø Treffer"))
                self._chart_combo.ax.tick_params(axis="x", rotation=45, labelsize=8)
                self._chart_combo.ax.grid(True, alpha=0.3, axis="y")
            else:
                self._chart_combo.ax.text(0.5, 0.5, _("Keine Combo-Daten"),
                                           ha="center", va="center", fontsize=14)
            self._chart_combo._safe_draw()

        # Tabelle
        while self._combo_rows:
            self._combo_list.remove(self._combo_rows.pop())

        for c in sorted(combos, key=lambda x: x.get("avg_matches", 0), reverse=True):
            key = c.get("combo_key", "?")
            avg = c.get("avg_matches", 0)
            total = c.get("total_predictions", 0)
            wins = c.get("win_count", 0)
            active = c.get("is_active", True)
            status = "✓" if active else "✗"

            row = Adw.ActionRow(
                title=f"{status} {key}  —  Ø {avg:.3f}",
                subtitle=f"{total} Predictions, {wins} Wins",
            )
            if not active:
                row.add_css_class("dim-label")
            self._combo_list.append(row)
            self._combo_rows.append(row)

        if not combos:
            row = Adw.ActionRow(title=_("Keine Kombinationen bewertet"))
            self._combo_list.append(row)
            self._combo_rows.append(row)
