"""Generator-Seite: Ml Training Mixin."""

import threading
from datetime import date, datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
try:
    from lotto_analyzer.ui.widgets.improvement_report import ImprovementReportPanel
except ImportError:
    ImprovementReportPanel = None
from lotto_analyzer.ui.widgets.help_button import HelpButton

logger = get_logger("generator.ml_training")



from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config

try:
    from lotto_common.models.generation import Strategy, GenerationResult
except ImportError:
    from enum import Enum
    from dataclasses import dataclass, field
    class Strategy(Enum):
        HOT = "hot"; COLD = "cold"; MIXED = "mixed"; ML = "ml"
        AI = "ai"; AVOID = "avoid"; ENSEMBLE = "ensemble"
    @dataclass
    class GenerationResult:
        numbers: list = field(default_factory=list)
        super_number: int = 0; strategy: str = ""
        reasoning: str = ""; confidence: float = 0.0
        bonus_numbers: list = field(default_factory=list)
        number_reasons: dict = field(default_factory=dict)


class MlTrainingMixin:
    """Mixin für GeneratorPage: Ml Training."""

    # ══════════════════════════════════════════════
    # ML Self-Improvement Sektion
    # ══════════════════════════════════════════════

    def _build_self_improve_section(self) -> None:
        """Self-Improvement Sektion: AI-Loop + Bericht-Panel."""
        improve_group = Adw.PreferencesGroup(
            title=_("ML Self-Improvement"),
            description=_("AI verbessert ML-Modelle automatisch — mit Bericht und Diskussion"),
        )
        improve_group.set_header_suffix(
            HelpButton(_("AI analysiert und verbessert ML-Modelle automatisch in mehreren Durchläufen."))
        )
        self._content.append(improve_group)

        # Button-Leiste
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self._self_improve_btn = Gtk.Button(label=_("Self-Improve starten"))
        self._self_improve_btn.set_tooltip_text(_("AI analysiert und verbessert ML-Modelle automatisch"))
        self._self_improve_btn.add_css_class("suggested-action")
        self._self_improve_btn.set_icon_name("emblem-synchronizing-symbolic")
        self._self_improve_btn.connect("clicked", self._on_start_self_improve)
        self.register_readonly_button(self._self_improve_btn)
        btn_box.append(self._self_improve_btn)

        self._multi_stage_btn = Gtk.Button(label=_("Multi-Stage Training"))
        self._multi_stage_btn.set_tooltip_text(_("Dreistufiges Training: Pretrain, Finetune, Sharpen"))
        self._multi_stage_btn.add_css_class("flat")
        self._multi_stage_btn.set_icon_name("view-list-symbolic")
        self._multi_stage_btn.connect("clicked", self._on_multi_stage_train)
        self.register_readonly_button(self._multi_stage_btn)
        btn_box.append(self._multi_stage_btn)

        self._backtest_learn_btn = Gtk.Button(label=_("Backtest-Lernphasen"))
        self._backtest_learn_btn.set_tooltip_text(_("Zeigt Backtest-Optimierung Ergebnisse: welche Konfiguration am besten performt"))
        self._backtest_learn_btn.add_css_class("flat")
        self._backtest_learn_btn.set_icon_name("system-run-symbolic")
        self._backtest_learn_btn.connect("clicked", self._on_show_backtest_learn)
        btn_box.append(self._backtest_learn_btn)

        improve_group.add(btn_box)

        # Spinner + Status
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._improve_spinner = Gtk.Spinner()
        self._improve_spinner.set_visible(False)
        status_box.append(self._improve_spinner)

        self._improve_status = Gtk.Label(label="")
        self._improve_status.set_xalign(0)
        self._improve_status.set_wrap(True)
        self._improve_status.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._improve_status.set_selectable(True)
        status_box.append(self._improve_status)
        improve_group.add(status_box)

        # ImprovementReportPanel
        self._report_panel = ImprovementReportPanel(
            ai_analyst=self._ai_analyst,
            api_client=self.api_client,
            audio_service=self._audio_service,
            config_manager=self.config_manager,
        )
        self._report_panel.set_visible(False)
        self._content.append(self._report_panel)

    def _on_start_self_improve(self, btn) -> None:
        """Self-Improvement Loop starten."""
        self._self_improve_btn.set_sensitive(False)
        self._multi_stage_btn.set_sensitive(False)
        self._improve_spinner.set_visible(True)
        self._improve_spinner.start()
        self._improve_status.set_label(_("Self-Improvement startet..."))
        self._report_panel.set_visible(False)

        draw_day = self._get_draw_day()

        def worker():
            try:
                if self.api_client:
                    data = self.api_client.start_self_improve(draw_day.value)
                    task_id = data.get("task_id")
                    if task_id:
                        self._poll_self_improve(task_id)
                        return
                    GLib.idle_add(self._finish_self_improve, _("Kein Task-ID erhalten"), "")
                else:
                    from lotto_analyzer.ui.helpers import show_error_toast
                    GLib.idle_add(show_error_toast, self, _("Serververbindung erforderlich"))
                    GLib.idle_add(self._finish_self_improve, _("Serververbindung erforderlich"), "")
            except Exception as e:
                GLib.idle_add(self._finish_self_improve, f"Fehler: {e}", "")

        threading.Thread(target=worker, daemon=True).start()

    def _poll_self_improve(self, task_id: str) -> None:
        """Self-Improvement Task-Status per Polling abfragen."""
        import time
        import json as json_mod

        self._self_improve_task_id = task_id

        # WS-Listener fuer instant Updates (Polling bleibt als Fallback)
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.on("task_update", self._on_ws_self_improve_task)
        except Exception:
            pass

        def poller():
            start = time.monotonic()
            try:
                while not self._cancel_event.is_set():
                    self._cancel_event.wait(30)  # Slow fallback; WS pushes instant
                    if self._cancel_event.is_set():
                        return
                    if time.monotonic() - start > self.POLL_TIMEOUT_SECONDS:
                        GLib.idle_add(
                            self._finish_self_improve, "Timeout nach 30 Minuten", "",
                        )
                        return
                    try:
                        task = self.api_client.get_task(task_id)
                    except Exception as e:
                        logger.warning(f"Self-Improve-Task-Polling fehlgeschlagen: {e}")
                        continue
                    status = task.get("status", "?")
                    progress = task.get("progress", 0)
                    pct = int(progress * 100)
                    GLib.idle_add(
                        self._improve_status.set_label,
                        f"Self-Improvement läuft... ({pct}%)",
                    )
                    if status == "completed":
                        result_raw = task.get("result")
                        result = json_mod.loads(result_raw) if result_raw else {}
                        report = result.get("report", "")
                        total_iter = result.get("total_iterations", 0)
                        approved = result.get("approved_count", 0)
                        improvement = result.get("total_improvement", 0)
                        summary = (
                            f"Self-Improvement abgeschlossen: "
                            f"{total_iter} Iterationen, "
                            f"{approved} approved, "
                            f"Verbesserung: {improvement:+.4f}"
                        )
                        GLib.idle_add(
                            self._finish_self_improve, summary, report,
                        )
                        return
                    elif status in ("failed", "cancelled"):
                        error = task.get("error", "Unbekannter Fehler")
                        GLib.idle_add(
                            self._finish_self_improve,
                            f"Abgebrochen/Fehler: {error}", "",
                        )
                        return
            except Exception as e:
                GLib.idle_add(
                    self._finish_self_improve, f"Polling-Fehler: {e}", "",
                )

        self._cancel_event.clear()
        threading.Thread(target=poller, daemon=True).start()

    def _on_ws_self_improve_task(self, data: dict) -> bool:
        """Handle WS task_update — trigger instant self-improve progress refresh."""
        task_id = data.get("id", "")
        if hasattr(self, "_self_improve_task_id") and task_id == self._self_improve_task_id:
            import json as json_mod
            status = data.get("status", "")
            progress = data.get("progress", 0)
            pct = int(progress * 100)
            self._improve_status.set_label(f"Self-Improvement läuft... ({pct}%)")
            if status == "completed":
                result_raw = data.get("result")
                try:
                    result = json_mod.loads(result_raw) if isinstance(result_raw, str) else (result_raw or {})
                except Exception:
                    result = {}
                report = result.get("report", "")
                total_iter = result.get("total_iterations", 0)
                approved = result.get("approved_count", 0)
                improvement = result.get("total_improvement", 0)
                summary = (
                    f"Self-Improvement abgeschlossen: "
                    f"{total_iter} Iterationen, "
                    f"{approved} approved, "
                    f"Verbesserung: {improvement:+.4f}"
                )
                self._finish_self_improve(summary, report)
            elif status in ("failed", "cancelled"):
                error = data.get("error", "Unbekannter Fehler")
                self._finish_self_improve(f"Abgebrochen/Fehler: {error}", "")
        return False

    def _finish_self_improve(self, summary: str, report: str) -> bool:
        """Self-Improvement UI-Ende."""
        # WS-Listener entfernen
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("task_update", self._on_ws_self_improve_task)
        except Exception:
            pass
        self._self_improve_btn.set_sensitive(True)
        self._multi_stage_btn.set_sensitive(True)
        self._improve_spinner.stop()
        self._improve_spinner.set_visible(False)
        self._improve_status.set_label(summary)

        if report:
            self._report_panel.set_report(report)
            self._report_panel.set_visible(True)
        return False

    def _on_multi_stage_train(self, btn) -> None:
        """Multi-Stage Training starten."""
        self._self_improve_btn.set_sensitive(False)
        self._multi_stage_btn.set_sensitive(False)
        self._improve_spinner.set_visible(True)
        self._improve_spinner.start()
        self._improve_status.set_label(_("Multi-Stage Training: PRETRAIN → FINETUNE → SHARPEN..."))

        draw_day = self._get_draw_day()

        def worker():
            try:
                if self.api_client:
                    data = self.api_client.train_multi_stage(draw_day.value)
                    task_id = data.get("task_id")
                    if task_id:
                        def fmt(result):
                            stages = result.get("stages", [])
                            final = result.get("final_score", 0)
                            duration = result.get("total_duration", 0)
                            lines = [
                                f"Multi-Stage Training: {len(stages)} Stufen, "
                                f"Score={final:.4f}, Dauer={duration:.0f}s",
                            ]
                            for s in stages:
                                lines.append(
                                    f"  {s['stage']}: RF={s.get('rf_accuracy', 0):.4f}, "
                                    f"GB={s.get('gb_accuracy', 0):.4f}, "
                                    f"Samples={s.get('train_samples', 0)}"
                                )
                            return "\n".join(lines)
                        self._poll_task_result(task_id, fmt)
                        return
                    GLib.idle_add(self._finish_multi_stage, _("Kein Task-ID erhalten"))
                else:
                    from lotto_analyzer.ui.helpers import show_error_toast
                    GLib.idle_add(show_error_toast, self, _("Serververbindung erforderlich"))
                    GLib.idle_add(self._finish_multi_stage, _("Serververbindung erforderlich"))
            except Exception as e:
                GLib.idle_add(self._finish_multi_stage, f"Fehler: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _finish_multi_stage(self, text: str) -> bool:
        """Multi-Stage Training UI-Ende."""
        self._self_improve_btn.set_sensitive(True)
        self._multi_stage_btn.set_sensitive(True)
        self._improve_spinner.stop()
        self._improve_spinner.set_visible(False)
        self._improve_status.set_label(text)
        return False

    def _on_show_backtest_learn(self, _btn) -> None:
        """Backtest-Lernphasen anzeigen: Welche Konfiguration performt am besten."""
        import json as json_mod

        dialog = Adw.Dialog()
        dialog.set_title(_("Backtest-Lernphasen"))
        dialog.set_content_width(550)
        dialog.set_content_height(450)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                          margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        scroll.set_child(content)
        dialog.set_child(scroll)

        draw_day = self._get_draw_day().value

        def worker():
            runs = []
            try:
                if self.api_client:
                    runs = self.api_client.get_backtest_runs(draw_day, limit=10)
            except Exception as e:
                logger.warning(f"Backtest-Runs laden fehlgeschlagen: {e}")
            GLib.idle_add(show_data, runs)

        def show_data(runs):
            if not runs:
                content.append(Gtk.Label(
                    label=f"Keine Backtest-Daten für {draw_day}.\n"
                          "Starte einen Backtest im Backtest-Tab.",
                    wrap=True,
                ))
                return

            # Beste Konfiguration hervorheben
            completed = [r for r in runs if r.get("status") == "completed"]
            if completed:
                best_run = max(completed, key=lambda r: r.get("avg_matches", 0))
                best_frame = Gtk.Frame()
                best_frame.add_css_class("card")
                best_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                                   margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
                best_box.append(Gtk.Label(
                    label=f"Beste Konfiguration: {best_run.get('best_strategy', '?').capitalize()}",
                    xalign=0, css_classes=["heading"],
                ))
                best_box.append(Gtk.Label(
                    label=f"Fenster: {best_run.get('window_months', '?')} Monate | "
                          f"Avg: {best_run.get('avg_matches', 0):.3f} | "
                          f"Random: {best_run.get('random_baseline_avg', 0):.3f}",
                    xalign=0,
                ))

                try:
                    summary = json_mod.loads(best_run.get("result_summary", "{}"))
                    verdict = summary.get("_verdict", {})
                    if verdict:
                        best_box.append(Gtk.Label(
                            label=f"Bewertung: {verdict.get('rating', '—')}",
                            xalign=0, css_classes=["success"] if "GUT" in verdict.get("rating", "") else [],
                        ))
                except Exception as e:
                    logger.warning(f"Backtest-Bewertung Parsing fehlgeschlagen: {e}")

                best_frame.set_child(best_box)
                content.append(best_frame)

            # Alle Runs als Liste
            content.append(Gtk.Label(label="\nAlle Durchlaeufe:", xalign=0, css_classes=["heading"]))
            for run in runs:
                label = Gtk.Label(
                    label=f"{run.get('window_months', '?')}mo | "
                          f"{run.get('best_strategy', '—')} | "
                          f"Avg: {run.get('avg_matches', 0):.3f} | "
                          f"{run.get('status', '?')} | "
                          f"{run.get('created_at', '')[:16]}",
                    xalign=0, selectable=True,
                )
                content.append(label)

        threading.Thread(target=worker, daemon=True).start()
        dialog.present(self.get_root())
