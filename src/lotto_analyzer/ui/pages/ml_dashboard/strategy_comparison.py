"""ML-Dashboard: Strategie-Vergleich."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("ml_dashboard.strategy")


class StrategyComparisonMixin:
    """Strategie-Performance Vergleich."""

    def _build_strategy_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Strategie-Vergleich"),
            description=_("Durchschnittliche Treffer pro Strategie"),
        )
        content.append(group)

        try:
            from lotto_analyzer.ui.widgets.chart_view import ChartView
            self._chart_strategy = ChartView(figsize=(10, 4))
            group.add(self._chart_strategy)
        except Exception as e:
            logger.debug(f"ChartView (Strategie) initialisieren fehlgeschlagen: {e}")
            self._chart_strategy = None

        self._strategy_list = Gtk.ListBox()
        self._strategy_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._strategy_list.add_css_class("boxed-list")
        group.add(self._strategy_list)
        self._strategy_rows: list = []

    def _update_strategy_comparison(self, data: dict) -> None:
        perfs = data.get("strategy_perf", [])

        # Chart
        if self._chart_strategy:
            self._chart_strategy.ax.clear()
            if perfs:
                sorted_perfs = sorted(perfs, key=lambda p: p.get("avg_matches", 0), reverse=True)
                names = [p.get("strategy", "?")[:12] for p in sorted_perfs]
                avgs = [p.get("avg_matches", 0) for p in sorted_perfs]
                colors = ["#e01b24" if i == 0 else "#3584e4" for i in range(len(names))]

                self._chart_strategy.ax.bar(names, avgs, color=colors, edgecolor="none")
                self._chart_strategy.ax.set_title(_("Ø Treffer pro Strategie"),
                                                   fontsize=12, fontweight="bold")
                self._chart_strategy.ax.set_ylabel(_("Ø Treffer"))
                self._chart_strategy.ax.tick_params(axis="x", rotation=45)
                self._chart_strategy.ax.grid(True, alpha=0.3, axis="y")
            else:
                self._chart_strategy.ax.text(0.5, 0.5, _("Keine Daten"),
                                              ha="center", va="center", fontsize=14)
            self._chart_strategy._safe_draw()

        # Tabelle
        while self._strategy_rows:
            self._strategy_list.remove(self._strategy_rows.pop())

        for p in sorted(perfs, key=lambda x: x.get("avg_matches", 0), reverse=True):
            strat = p.get("strategy", "?")
            avg = p.get("avg_matches", 0)
            total = p.get("total_predictions", 0)
            wins = p.get("win_count", 0)
            weight = p.get("weight", 1.0)
            hit_rate = (wins / total * 100) if total > 0 else 0

            row = Adw.ActionRow(
                title=f"{strat}  —  Ø {avg:.3f} {_('Treffer')}",
                subtitle=f"{total} Predictions, {wins} Wins ({hit_rate:.1f}%), Gewicht: {weight:.2f}",
            )
            self._strategy_list.append(row)
            self._strategy_rows.append(row)

        if not perfs:
            row = Adw.ActionRow(title=_("Keine Strategie-Daten"))
            self._strategy_list.append(row)
            self._strategy_rows.append(row)
