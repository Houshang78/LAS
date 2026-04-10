"""ML-Dashboard: Self-Improvement Historie."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("ml_dashboard.self_improve")


class SelfImprovementMixin:
    """Self-Improvement Verlauf und Statistiken."""

    def _build_self_improve_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Self-Improvement"),
            description=_("AI-gesteuerte autonome Modell-Verbesserung"),
        )
        content.append(group)

        # Stats-Übersicht
        self._improve_stats_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._improve_stats_box.set_margin_top(8)
        self._improve_stats_box.set_margin_bottom(8)

        self._improve_stat_labels = {}
        for key, label in [
            ("total_runs", _("Durchläufe")),
            ("total_iterations", _("Iterationen")),
            ("approved", _("Genehmigt")),
            ("avg_improvement", _("Ø Verbesserung")),
        ]:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            val = Gtk.Label(label="—")
            val.add_css_class("title-2")
            box.append(val)
            lbl = Gtk.Label(label=label)
            lbl.add_css_class("dim-label")
            lbl.add_css_class("caption")
            box.append(lbl)
            box.set_hexpand(True)
            self._improve_stats_box.append(box)
            self._improve_stat_labels[key] = val

        group.add(self._improve_stats_box)

        # Chart
        try:
            from lotto_analyzer.ui.widgets.chart_view import ChartView
            self._chart_improve = ChartView(figsize=(10, 3))
            group.add(self._chart_improve)
        except Exception as e:
            logger.debug(f"ChartView (Improvement) initialisieren fehlgeschlagen: {e}")
            self._chart_improve = None

        # Runs-Tabelle
        self._improve_list = Gtk.ListBox()
        self._improve_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._improve_list.add_css_class("boxed-list")

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # Grow up to 2 rows (~112px), then scroll — same pattern as Kaufempfehlungen
        scroll.set_min_content_height(56)
        scroll.set_max_content_height(112)
        scroll.set_child(self._improve_list)
        self._improve_scroll = scroll
        group.add(scroll)
        self._improve_rows: list = []

    def _update_self_improvement(self, data: dict) -> None:
        runs = data.get("improve_runs", [])
        stats = data.get("improve_stats", {})

        # Stats
        self._improve_stat_labels["total_runs"].set_label(str(stats.get("total_runs", 0)))
        self._improve_stat_labels["total_iterations"].set_label(str(stats.get("total_iterations", 0)))
        self._improve_stat_labels["approved"].set_label(str(stats.get("approved_count", 0)))
        avg = stats.get("avg_improvement", 0)
        self._improve_stat_labels["avg_improvement"].set_label(
            f"{avg:+.3f}" if avg else "—"
        )

        # Chart
        if self._chart_improve:
            self._chart_improve.ax.clear()
            if runs:
                scores = [r.get("score_after", 0) or 0 for r in reversed(runs)]
                statuses = [r.get("status", "") for r in reversed(runs)]
                x = list(range(len(scores)))
                colors = ["#26a269" if s == "approved" else "#e01b24" if s == "rejected"
                          else "#3584e4" for s in statuses]

                self._chart_improve.ax.scatter(x, scores, c=colors, s=30, zorder=5)
                self._chart_improve.ax.plot(x, scores, color="#8b949e", linewidth=1, alpha=0.5)
                self._chart_improve.ax.set_title(_("Score pro Improvement-Run"),
                                                  fontsize=12, fontweight="bold")
                self._chart_improve.ax.set_ylabel("Score")
                self._chart_improve.ax.grid(True, alpha=0.3)
            else:
                self._chart_improve.ax.text(0.5, 0.5, _("Kein Self-Improvement durchgeführt"),
                                             ha="center", va="center", fontsize=12)
            self._chart_improve._safe_draw()

        # Tabelle
        while self._improve_rows:
            self._improve_list.remove(self._improve_rows.pop())

        for run in runs[:15]:
            status = run.get("status", "?")
            status_icon = {"approved": "✓", "rejected": "✗", "running": "⏳"}.get(status, "?")
            before = run.get("score_before", 0) or 0
            after = run.get("score_after", 0) or 0
            diff = after - before
            created = str(run.get("created_at", ""))[:16]

            row = Adw.ActionRow(
                title=f"{status_icon} {created}  |  {before:.3f} → {after:.3f} ({diff:+.3f})",
                subtitle=run.get("phase", ""),
            )
            if status == "approved":
                row.add_css_class("success")
            elif status == "rejected":
                row.add_css_class("error")
            self._improve_list.append(row)
            self._improve_rows.append(row)

        if not runs:
            row = Adw.ActionRow(title=_("Keine Improvement-Runs"))
            self._improve_list.append(row)
            self._improve_rows.append(row)

        # Dynamic height: grow to 2 rows, then scroll
        n = len(self._improve_rows)
        row_h = 56
        visible = min(n, 2) * row_h
        self._improve_scroll.set_max_content_height(max(visible, row_h))
