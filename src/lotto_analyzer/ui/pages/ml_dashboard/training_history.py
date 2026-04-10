"""ML-Dashboard: Training-Verlauf Charts."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("ml_dashboard.training_history")


class TrainingHistoryMixin:
    """Training-Verlauf als Charts."""

    def _build_training_history_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Training-Verlauf"),
            description=_("Accuracy und Loss über Zeit"),
        )
        content.append(group)

        try:
            from lotto_analyzer.ui.widgets.chart_view import ChartView
            self._chart_training = ChartView(figsize=(10, 4))
            group.add(self._chart_training)
        except Exception as e:
            logger.debug(f"ChartView (Training) initialisieren fehlgeschlagen: {e}")
            self._chart_training = None
            group.add(Gtk.Label(label=_("Charts nicht verfügbar")))

        # Trainings-Tabelle
        self._training_list = Gtk.ListBox()
        self._training_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._training_list.add_css_class("boxed-list")

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(100)
        scroll.set_max_content_height(250)
        scroll.set_child(self._training_list)
        group.add(scroll)

        self._training_rows: list = []

    def _update_training_history(self, data: dict) -> None:
        """Training-Chart und Tabelle aktualisieren."""
        runs = data.get("training_runs", [])

        # Chart
        if self._chart_training and runs:
            self._chart_training.ax.clear()

            dates = []
            rf_acc = []
            gb_acc = []

            for run in reversed(runs):  # chronologisch
                created = run.get("created_at", "")
                dates.append(str(created)[:10])
                rf_acc.append(run.get("rf_accuracy", 0) or 0)
                gb_acc.append(run.get("gb_accuracy", 0) or 0)

            if dates:
                x = list(range(len(dates)))
                self._chart_training.ax.plot(x, rf_acc, label="RF", color="#e01b24",
                                             linewidth=2, marker="o", markersize=4)
                self._chart_training.ax.plot(x, gb_acc, label="GB", color="#1c71d8",
                                             linewidth=2, marker="s", markersize=4)
                self._chart_training.ax.set_title(_("ML-Accuracy pro Training"),
                                                   fontsize=12, fontweight="bold")
                self._chart_training.ax.set_ylabel("Accuracy")
                self._chart_training.ax.legend(loc="lower right")
                self._chart_training.ax.grid(True, alpha=0.3)

                step = max(1, len(dates) // 10)
                self._chart_training.ax.set_xticks(x[::step])
                self._chart_training.ax.set_xticklabels(dates[::step], rotation=45, fontsize=7)
            else:
                self._chart_training.ax.text(0.5, 0.5, _("Keine Training-Daten"),
                                              ha="center", va="center", fontsize=14)
            self._chart_training._safe_draw()

        # Tabelle
        while self._training_rows:
            self._training_list.remove(self._training_rows.pop())

        for run in runs[:15]:
            created = str(run.get("created_at", ""))[:16]
            rf = run.get("rf_accuracy", 0) or 0
            gb = run.get("gb_accuracy", 0) or 0
            samples = run.get("n_samples", 0) or 0
            duration = run.get("duration_sec", 0) or 0

            row = Adw.ActionRow(
                title=f"{created}  |  RF: {rf:.1%}  GB: {gb:.1%}",
                subtitle=f"{samples} Samples, {duration:.0f}s",
            )
            self._training_list.append(row)
            self._training_rows.append(row)

        if not runs:
            row = Adw.ActionRow(title=_("Keine Trainings vorhanden"))
            self._training_list.append(row)
            self._training_rows.append(row)
