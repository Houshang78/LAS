"""ML-Dashboard: Export als Markdown."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("ml_dashboard.export")


class ExportMixin:
    """Bericht exportieren."""

    def _build_export_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Bericht exportieren"),
        )
        content.append(group)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        export_btn = Gtk.Button(label=_("Als Markdown exportieren"))
        export_btn.set_icon_name("document-save-symbolic")
        export_btn.add_css_class("suggested-action")
        export_btn.connect("clicked", self._on_export_md)
        btn_box.append(export_btn)

        copy_btn = Gtk.Button(label=_("In Zwischenablage"))
        copy_btn.set_icon_name("edit-copy-symbolic")
        copy_btn.connect("clicked", self._on_copy_report)
        btn_box.append(copy_btn)

        group.add(btn_box)

    def _generate_report_markdown(self) -> str:
        """ML-Dashboard Bericht als Markdown."""
        data = getattr(self, "_ml_data", {})
        draw_day = data.get("draw_day", "?")

        lines = [
            f"# ML-Dashboard Bericht — {draw_day.capitalize()}",
            f"Erstellt: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## Modell-Status",
        ]

        model_ready = data.get("model_ready", {})
        for key in ("rf", "gb", "lstm"):
            status = "✓ Trainiert" if model_ready.get(key) else "✗ Nicht trainiert"
            names = {"rf": "Random Forest", "gb": "Gradient Boosting", "lstm": "LSTM"}
            lines.append(f"- **{names[key]}**: {status}")

        lines.append("")
        lines.append("## Strategie-Performance")
        lines.append("")
        lines.append("| Strategie | Ø Treffer | Predictions | Wins | Hit-% |")
        lines.append("|---|---|---|---|---|")

        for p in sorted(data.get("strategy_perf", []),
                         key=lambda x: x.get("avg_matches", 0), reverse=True):
            strat = p.get("strategy", "?")
            avg = p.get("avg_matches", 0)
            total = p.get("total_predictions", 0)
            wins = p.get("win_count", 0)
            hit = (wins / total * 100) if total > 0 else 0
            lines.append(f"| {strat} | {avg:.3f} | {total} | {wins} | {hit:.1f}% |")

        lines.append("")
        lines.append("## Training-Verlauf")
        lines.append("")
        for run in data.get("training_runs", [])[:10]:
            created = str(run.get("created_at", ""))[:16]
            rf = run.get("rf_accuracy", 0) or 0
            gb = run.get("gb_accuracy", 0) or 0
            lines.append(f"- {created}: RF {rf:.1%}, GB {gb:.1%}")

        lines.append("")
        lines.append("## Modell-Kombinationen")
        lines.append("")
        for c in sorted(data.get("combo_perf", []),
                          key=lambda x: x.get("avg_matches", 0), reverse=True):
            key = c.get("combo_key", "?")
            avg = c.get("avg_matches", 0)
            lines.append(f"- {key}: Ø {avg:.3f}")

        stats = data.get("improve_stats", {})
        if stats:
            lines.append("")
            lines.append("## Self-Improvement")
            lines.append(f"- Durchläufe: {stats.get('total_runs', 0)}")
            lines.append(f"- Iterationen: {stats.get('total_iterations', 0)}")
            lines.append(f"- Genehmigt: {stats.get('approved_count', 0)}")

        return "\n".join(lines)

    def _on_export_md(self, _btn) -> None:
        """Markdown-Datei speichern."""
        report = self._generate_report_markdown()

        dialog = Gtk.FileDialog()
        dialog.set_initial_name(f"ml_report_{self._draw_day}.md")

        def on_save(dlg, result):
            try:
                gfile = dlg.save_finish(result)
                if gfile:
                    path = gfile.get_path()
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(report)
                    logger.info(f"ML-Bericht exportiert: {path}")
            except Exception as e:
                logger.warning(f"Export fehlgeschlagen: {e}")

        dialog.save(self.get_root(), None, on_save)

    def _on_copy_report(self, _btn) -> None:
        """Bericht in Zwischenablage kopieren."""
        report = self._generate_report_markdown()
        clipboard = self.get_clipboard()
        clipboard.set(report)
        logger.info("ML-Bericht in Zwischenablage kopiert")
