"""ML-Dashboard: Feature Importance."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("ml_dashboard.features")

# Feature-Namen übersetzen (Index → lesbarer Name)
FEATURE_LABELS = {
    0: "Häufigkeit Zahl 1", 1: "Häufigkeit Zahl 2",
}


def _feature_label(idx: int | str) -> str:
    """Feature-Index in lesbaren Namen umwandeln."""
    try:
        i = int(idx)
    except (ValueError, TypeError):
        return str(idx)
    if i < 49:
        return f"Freq Z.{i+1}"
    elif i < 98:
        return f"Freq (gew.) Z.{i-49+1}"
    elif i < 147:
        return f"Lücke Z.{i-98+1}"
    elif i < 196:
        return f"Trend Z.{i-147+1}"
    elif i < 245:
        return f"Momentum Z.{i-196+1}"
    elif i < 294:
        return f"CoOcc Z.{i-245+1}"
    elif i < 310:
        return f"Entropy/Stat {i-294}"
    elif i < 322:
        return f"Bayes/Markov {i-310}"
    return f"Feature {i}"


class FeatureImportanceMixin:
    """Feature Importance Visualisierung."""

    def _build_feature_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Feature Importance (Top 20)"),
            description=_("Welche Eingabe-Features sind für die ML-Modelle am wichtigsten?"),
        )
        content.append(group)

        info = Adw.ActionRow(
            title=_("Die 322 Features umfassen: Häufigkeiten, Lücken, Trends, "
                     "Momentum, Co-Occurrence, Entropy, Bayes-Posterior, Markov-Signale"),
        )
        info.set_title_lines(3)
        info.add_css_class("dim-label")
        group.add(info)

        try:
            from lotto_analyzer.ui.widgets.chart_view import ChartView
            self._chart_features = ChartView(figsize=(10, 5))
            group.add(self._chart_features)
        except Exception as e:
            logger.debug(f"ChartView (Features) initialisieren fehlgeschlagen: {e}")
            self._chart_features = None

    def _update_feature_importance(self, data: dict) -> None:
        fi = data.get("feature_importance", {})
        if not self._chart_features:
            return

        self._chart_features.ax.clear()

        if not fi:
            self._chart_features.ax.text(
                0.5, 0.5, _("Keine Feature-Importance Daten\n(nach erstem Backtest verfügbar)"),
                ha="center", va="center", fontsize=12,
            )
            self._chart_features._safe_draw()
            return

        # Top 20 sortiert
        sorted_fi = sorted(fi.items(), key=lambda x: float(x[1]), reverse=True)[:20]
        labels = [_feature_label(k) for k, _ in reversed(sorted_fi)]
        values = [float(v) for _, v in reversed(sorted_fi)]

        # Horizontal Bar Chart
        colors = ["#1c71d8" if v < max(values) * 0.7 else "#e01b24" for v in values]
        self._chart_features.ax.barh(labels, values, color=colors, edgecolor="none")
        self._chart_features.ax.set_title(_("Top 20 wichtigste Features"),
                                           fontsize=12, fontweight="bold")
        self._chart_features.ax.set_xlabel(_("Importance"))
        self._chart_features.ax.tick_params(axis="y", labelsize=8)
        self._chart_features.ax.grid(True, alpha=0.3, axis="x")

        self._chart_features._safe_draw()
