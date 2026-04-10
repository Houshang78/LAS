"""Generator-Seite: Performance Mixin."""

import threading
from datetime import date, datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.generation import combo_key
from lotto_common.models.game_config import get_config
from lotto_analyzer.ui.widgets.help_button import HelpButton
try:
    from lotto_analyzer.ui.widgets.speak_button import SpeakButton
except ImportError:
    SpeakButton = None

logger = get_logger("generator.performance")



try:
    from lotto_analyzer.ui.pages.generator.page import STRATEGY_COLORS, _apply_css
except ImportError:
    STRATEGY_COLORS = {}
    def _apply_css(w, c): pass

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




class PerformanceMixin2:
    """Teil 2 von PerformanceMixin."""

    def _on_ai_analysis_done(self, response: str, error: str | None) -> bool:
        self._ai_analysis_btn.set_sensitive(True)
        if error:
            text = _("AI-Analyse fehlgeschlagen") + f": {error}"
        elif response:
            text = response
        else:
            text = _("Keine Antwort von AI erhalten.")
        self._ai_analysis_label.set_label(text)
        self._ai_analysis_label.set_visible(True)
        self._ai_speak_btn.text = text
        return False

    def _show_local_analysis(self, perf_data: list[dict]) -> None:
        """Lokale Analyse ohne AI-Backend."""
        if not perf_data:
            return

        best = max(perf_data, key=lambda p: p["weight"])
        worst = min(perf_data, key=lambda p: p["weight"])
        total_preds = sum(p["total_predictions"] for p in perf_data)

        text = (
            f"Lokale Analyse ({total_preds} Vorhersagen gesamt):\n\n"
            f"Beste Strategie: {best['strategy']} "
            f"(Ø {best['avg_matches']:.2f} Treffer, "
            f"Gewicht: {best['weight']:.2f})\n"
            f"Schlechteste: {worst['strategy']} "
            f"(Ø {worst['avg_matches']:.2f} Treffer, "
            f"Gewicht: {worst['weight']:.2f})\n\n"
            f"Empfehlung: Verwende '{best['strategy']}' oder 'Ensemble' "
            f"für optimale Ergebnisse."
        )
        self._ai_analysis_label.set_label(text)
        self._ai_analysis_label.set_visible(True)
        self._ai_speak_btn.text = text

    # ══════════════════════════════════════════════
    # ML-Training Steuerung (AI-gesteuert)
    # ══════════════════════════════════════════════

    def _build_ml_training_section(self) -> None:
        """ML-Training-Sektion: Hyperparameter-Suche, Zeitraum-Vergleich, Turnier."""
        train_group = Adw.PreferencesGroup(
            title=_("ML-Training Steuerung"),
            description=_("AI-gesteuertes Training: Hyperparameter optimieren, Zeiträume vergleichen"),
        )
        train_group.set_header_suffix(
            HelpButton(_("Laesst alle Strategien gegeneinander antreten und ermittelt die beste."))
        )
        self._content.append(train_group)

        # Button-Leiste
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self._hypersearch_btn = Gtk.Button(label=_("Hyperparameter-Suche"))
        self._hypersearch_btn.set_tooltip_text(_("Optimiert ML-Parameter durch automatische Suche"))
        self._hypersearch_btn.add_css_class("flat")
        self._hypersearch_btn.set_icon_name("system-search-symbolic")
        self._hypersearch_btn.connect("clicked", self._on_hypersearch)
        btn_box.append(self._hypersearch_btn)

        self._range_compare_btn = Gtk.Button(label=_("Zeitraum-Vergleich"))
        self._range_compare_btn.set_tooltip_text(_("Vergleicht ML-Performance ueber verschiedene Zeiträume"))
        self._range_compare_btn.add_css_class("flat")
        self._range_compare_btn.set_icon_name("x-office-calendar-symbolic")
        self._range_compare_btn.connect("clicked", self._on_range_compare)
        btn_box.append(self._range_compare_btn)

        self._tournament_btn = Gtk.Button(label=_("Strategie-Turnier"))
        self._tournament_btn.set_tooltip_text(_("Laesst alle Strategien in 5 Runden gegeneinander antreten"))
        self._tournament_btn.add_css_class("flat")
        self._tournament_btn.set_icon_name("trophy-symbolic")
        self._tournament_btn.connect("clicked", self._on_tournament)
        btn_box.append(self._tournament_btn)

        self._ai_auto_train_btn = Gtk.Button(label=_("AI Auto-Training"))
        self._ai_auto_train_btn.set_tooltip_text(_("AI steuert Training-Optimierung automatisch"))
        self._ai_auto_train_btn.add_css_class("suggested-action")
        self._ai_auto_train_btn.set_icon_name("starred-symbolic")
        self._ai_auto_train_btn.connect("clicked", self._on_ai_auto_train)
        btn_box.append(self._ai_auto_train_btn)

        train_group.add(btn_box)

        # Spinner + Status
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._train_mgr_spinner = Gtk.Spinner()
        self._train_mgr_spinner.set_visible(False)
        status_box.append(self._train_mgr_spinner)

        self._train_mgr_status = Gtk.Label(label="")
        self._train_mgr_status.set_xalign(0)
        self._train_mgr_status.set_wrap(True)
        self._train_mgr_status.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._train_mgr_status.set_selectable(True)
        status_box.append(self._train_mgr_status)
        train_group.add(status_box)

        # Training-Historie
        self._train_history_btn = Gtk.Button(label=_("Training-Historie laden"))
        self._train_history_btn.set_tooltip_text(_("Zeigt vergangene Trainingslaeufe und deren Ergebnisse"))
        self._train_history_btn.add_css_class("flat")
        self._train_history_btn.connect("clicked", self._on_load_training_history)
        train_group.add(self._train_history_btn)

        self._train_history_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4,
        )
        self._train_history_frame = Gtk.Frame()
        self._train_history_frame.set_child(self._train_history_box)
        self._train_history_frame.set_visible(False)
        self._content.append(self._train_history_frame)

    def _set_training_buttons_sensitive(self, sensitive: bool) -> None:
        """Alle Training-Buttons (de)aktivieren."""
        for btn in [self._hypersearch_btn, self._range_compare_btn,
                     self._tournament_btn, self._ai_auto_train_btn]:
            btn.set_sensitive(sensitive)

    def _start_training_op(self, label: str) -> None:
        """Training-Operation UI-Start."""
        self._set_training_buttons_sensitive(False)
        self._train_mgr_spinner.set_visible(True)
        self._train_mgr_spinner.start()
        self._train_mgr_status.set_label(label)

    def _on_ws_training_task(self, data: dict) -> bool:
        """Handle WS task_update — trigger instant training progress refresh."""
        task_id = data.get("id", "")
        if hasattr(self, "_training_task_id") and task_id == self._training_task_id:
            import json
            status = data.get("status", "")
            progress = data.get("progress", 0)
            pct = int(progress * 100)
            self._train_mgr_status.set_label(f"Läuft... ({pct}%)")
            if status == "completed":
                result_raw = data.get("result")
                try:
                    result = json.loads(result_raw) if isinstance(result_raw, str) else (result_raw or {})
                except Exception:
                    result = {}
                fmt = getattr(self, "_training_format_fn", None)
                text = fmt(result) if fmt else str(result)
                self._finish_training_op(text)
            elif status in ("failed", "cancelled"):
                error = data.get("error", "Unbekannter Fehler")
                self._finish_training_op(f"Abgebrochen/Fehler: {error}")
        return False

    def _finish_training_op(self, result_text: str) -> bool:
        """Training-Operation UI-Ende (GLib.idle_add kompatibel)."""
        # WS-Listener entfernen
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("task_update", self._on_ws_training_task)
        except Exception:
            pass
        self._set_training_buttons_sensitive(True)
        self._train_mgr_spinner.stop()
        self._train_mgr_spinner.set_visible(False)
        self._train_mgr_status.set_label(result_text)
        return False

    def _poll_task_result(self, task_id: str, format_fn) -> None:
        """Task-Ergebnis per Polling abfragen (Background-Thread).

        Args:
            task_id: Server-Task-ID
            format_fn: Callable(result_dict) -> str — formatiert Ergebnis
        """
        import time
        import json

        self._training_task_id = task_id
        self._training_format_fn = format_fn

        # WS-Listener fuer instant Updates (Polling bleibt als Fallback)
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.on("task_update", self._on_ws_training_task)
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
                        GLib.idle_add(self._finish_training_op, "Timeout nach 30 Minuten")
                        return
                    try:
                        task = self.api_client.get_task(task_id)
                    except Exception as e:
                        logger.warning(f"Training-Task-Polling fehlgeschlagen: {e}")
                        continue
                    status = task.get("status", "?")
                    progress = task.get("progress", 0)
                    pct = int(progress * 100)
                    GLib.idle_add(
                        self._train_mgr_status.set_label,
                        f"Läuft... ({pct}%)",
                    )
                    if status == "completed":
                        result_raw = task.get("result")
                        result = json.loads(result_raw) if result_raw else {}
                        text = format_fn(result)
                        GLib.idle_add(self._finish_training_op, text)
                        return
                    elif status in ("failed", "cancelled"):
                        error = task.get("error", "Unbekannter Fehler")
                        GLib.idle_add(
                            self._finish_training_op,
                            f"Abgebrochen/Fehler: {error}",
                        )
                        return
            except Exception as e:
                GLib.idle_add(self._finish_training_op, f"Polling-Fehler: {e}")

        self._cancel_event.clear()
        threading.Thread(target=poller, daemon=True).start()

    def _on_hypersearch(self, btn) -> None:
        """Hyperparameter-Suche starten — via Server."""
        if not self.api_client:
            from lotto_analyzer.ui.helpers import show_error_toast
            show_error_toast(self, _("Serververbindung erforderlich"))
            return

        self._start_training_op("Hyperparameter-Suche läuft (kann mehrere Minuten dauern)...")
        draw_day = self._get_draw_day()

        def worker():
            try:
                data = self.api_client.hypersearch(draw_day.value)
                task_id = data.get("task_id")
                if task_id:
                    def fmt(result):
                        runs = result.get("runs", [])
                        if runs:
                            best = runs[0]
                            return (
                                f"Hyperparameter-Suche: {len(runs)} Runs.\n"
                                f"Bester: {best.get('run_id', '?')} — "
                                f"avg_matches={best.get('avg_matches', 0):.2f}"
                            )
                        return "Hyperparameter-Suche: Keine Ergebnisse."
                    self._poll_task_result(task_id, fmt)
                    return
                runs = data.get("runs", [])
                if runs:
                    best = runs[0]
                    text = (
                        f"Hyperparameter-Suche: {len(runs)} Runs abgeschlossen.\n"
                        f"Bester Run: {best.get('run_id', '?')} — "
                        f"avg_matches={best.get('avg_matches', 0):.2f}"
                    )
                else:
                    text = "Hyperparameter-Suche: Keine Ergebnisse."
                GLib.idle_add(self._finish_training_op, text)
            except Exception as e:
                GLib.idle_add(self._finish_training_op, f"Fehler: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_range_compare(self, btn) -> None:
        """Zeitraum-Vergleich starten — via Server."""
        if not self.api_client:
            from lotto_analyzer.ui.helpers import show_error_toast
            show_error_toast(self, _("Serververbindung erforderlich"))
            return

        self._start_training_op("Zeitraum-Vergleich läuft...")
        draw_day = self._get_draw_day()

        def worker():
            try:
                data = self.api_client.compare_ranges(draw_day.value)
                task_id = data.get("task_id")
                if task_id:
                    def fmt(result):
                        runs = result.get("runs", [])
                        if runs:
                            best = runs[0]
                            return (
                                f"Zeitraum-Vergleich: {len(runs)} Zeiträume.\n"
                                f"Bester: {best.get('year_from', '?')}-"
                                f"{best.get('year_to', '?')} — "
                                f"avg_matches={best.get('avg_matches', 0):.2f}"
                            )
                        return "Zeitraum-Vergleich: Keine Ergebnisse."
                    self._poll_task_result(task_id, fmt)
                    return
                runs = data.get("runs", [])
                if runs:
                    best = runs[0]
                    text = (
                        f"Zeitraum-Vergleich: {len(runs)} Zeiträume getestet.\n"
                        f"Bester: {best.get('year_from', '?')}-{best.get('year_to', '?')} — "
                        f"avg_matches={best.get('avg_matches', 0):.2f}"
                    )
                else:
                    text = "Zeitraum-Vergleich: Keine Ergebnisse."
                GLib.idle_add(self._finish_training_op, text)
            except Exception as e:
                GLib.idle_add(self._finish_training_op, f"Fehler: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_tournament(self, btn) -> None:
        """Strategie-Turnier starten — via Server."""
        if not self.api_client:
            from lotto_analyzer.ui.helpers import show_error_toast
            show_error_toast(self, _("Serververbindung erforderlich"))
            return

        self._start_training_op("Strategie-Turnier läuft (5 Runden)...")
        draw_day = self._get_draw_day()

        def worker():
            try:
                data = self.api_client.tournament(draw_day.value)
                task_id = data.get("task_id")
                if task_id:
                    def fmt(result):
                        ranking = result.get("ranking", [])
                        if ranking:
                            lines = [f"Turnier-Ergebnis ({len(ranking)} Combos):"]
                            for i, r in enumerate(ranking[:5], 1):
                                lines.append(
                                    f"  {i}. {r['combo_key']}: "
                                    f"avg={r.get('avg_matches', 0):.2f}, "
                                    f"wins={r.get('wins', 0)}"
                                )
                            return "\n".join(lines)
                        return "Turnier: Keine Ergebnisse."
                    self._poll_task_result(task_id, fmt)
                    return
                ranking = data.get("ranking", [])
                if ranking:
                    lines = [f"Turnier-Ergebnis ({len(ranking)} Combos):"]
                    for i, r in enumerate(ranking[:5], 1):
                        lines.append(
                            f"  {i}. {r['combo_key']}: "
                            f"avg={r.get('avg_matches', 0):.2f}, "
                            f"wins={r.get('wins', 0)}"
                        )
                    text = "\n".join(lines)
                else:
                    text = "Turnier: Keine Ergebnisse."
                GLib.idle_add(self._finish_training_op, text)
            except Exception as e:
                GLib.idle_add(self._finish_training_op, f"Fehler: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_ai_auto_train(self, btn) -> None:
        """AI-gesteuertes Auto-Training starten — via Server."""
        if not self.api_client:
            from lotto_analyzer.ui.helpers import show_error_toast
            show_error_toast(self, _("Serververbindung erforderlich"))
            return

        self._start_training_op("AI Auto-Training: Claude waehlt Parameter...")
        draw_day = self._get_draw_day()

        def worker():
            try:
                data = self.api_client.ai_train(draw_day.value, mode="auto")
                task_id = data.get("task_id")
                if task_id:
                    def fmt(result):
                        reasoning = result.get("ai_reasoning", "")
                        avg = result.get("avg_matches", 0)
                        status = result.get("status", "?")
                        return (
                            f"AI Auto-Training: {status}\n"
                            f"avg_matches={avg:.2f}\n"
                            f"Begründung: {reasoning}"
                        )
                    self._poll_task_result(task_id, fmt)
                    return
                result = data
                reasoning = result.get("ai_reasoning", "")
                avg = result.get("avg_matches", 0)
                status = result.get("status", "?")
                text = (
                    f"AI Auto-Training: {status}\n"
                    f"avg_matches={avg:.2f}\n"
                    f"Begründung: {reasoning}"
                )
                GLib.idle_add(self._finish_training_op, text)
            except Exception as e:
                GLib.idle_add(self._finish_training_op, f"Fehler: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_load_training_history(self, btn) -> None:
        """Training-Historie laden und anzeigen — via Server."""
        if not self.api_client:
            from lotto_analyzer.ui.helpers import show_error_toast
            show_error_toast(self, _("Serververbindung erforderlich"))
            return

        draw_day = self._get_draw_day()

        def worker():
            try:
                data = self.api_client.training_history(draw_day.value)
                history = data.get("history", [])
                GLib.idle_add(self._show_training_history, history)
            except Exception as e:
                GLib.idle_add(
                    self._train_mgr_status.set_label, f"Fehler: {e}",
                )

        threading.Thread(target=worker, daemon=True).start()

    def _show_training_history(self, history: list[dict]) -> bool:
        """Training-Historie in UI anzeigen."""
        while self._train_history_box.get_first_child():
            self._train_history_box.remove(self._train_history_box.get_first_child())

        self._train_history_frame.set_visible(True)

        if not history:
            label = Gtk.Label(label=_("Keine Training-Runs vorhanden."))
            label.add_css_class("dim-label")
            label.set_margin_top(12)
            label.set_margin_bottom(12)
            self._train_history_box.append(label)
            return False

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_start(8)
        header.set_margin_end(8)
        header.set_margin_top(8)
        for text, width in [
            ("Run-ID", 80), ("Epochen", 70), ("LR", 60),
            ("Ø Treffer", 80), ("Status", 80), ("Ausgeloest", 80),
        ]:
            lbl = Gtk.Label(label=text)
            lbl.add_css_class("heading")
            lbl.set_size_request(width, -1)
            lbl.set_xalign(0)
            header.append(lbl)
        self._train_history_box.append(header)
        self._train_history_box.append(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
        )

        # Zeilen (max 20)
        best_avg = max((h.get("avg_matches") or 0 for h in history), default=0)
        for h in history[:20]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.set_margin_start(8)
            row.set_margin_end(8)
            row.set_margin_top(2)
            row.set_margin_bottom(2)

            avg = h.get("avg_matches") or 0
            is_best = avg > 0 and avg == best_avg

            for text, width in [
                (str(h.get("run_id", "?"))[:8], 80),
                (str(h.get("lstm_epochs", "?")), 70),
                (f"{h.get('lstm_lr', 0):.4f}", 60),
                (f"{avg:.2f}" if avg else "-", 80),
                (h.get("status", "?"), 80),
                (h.get("triggered_by", "?"), 80),
            ]:
                lbl = Gtk.Label(label=text)
                lbl.set_size_request(width, -1)
                lbl.set_xalign(0)
                if is_best and "Treffer" not in text:
                    lbl.add_css_class("accent")
                row.append(lbl)

            self._train_history_box.append(row)

        return False

# TODO: Diese Datei ist >500Z weil: ML-Training Steuerung mit 4 Operationen + WS-Integration + Training-Historie

