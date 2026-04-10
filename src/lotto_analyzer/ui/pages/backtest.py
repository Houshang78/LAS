"""Backtest-Seite: Walk-Forward ML-Backtesting mit Charts."""

import json
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.i18n import _
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_common.utils.logging_config import get_logger
from datetime import date, datetime

logger = get_logger("backtest_page")

_GAME_OPTIONS = [
    (_("Lotto 6aus49 — Samstag"), "saturday"),
    (_("Lotto 6aus49 — Mittwoch"), "wednesday"),
    (_("EuroJackpot — Freitag"), "friday"),
    (_("EuroJackpot — Dienstag"), "tuesday"),
]

_DAY_LABELS = {"saturday": _("Samstag (6aus49)"), "wednesday": _("Mittwoch (6aus49)"),
               "tuesday": _("Dienstag (EJ)"), "friday": _("Freitag (EJ)")}


class BacktestPage(BasePage):
    """Walk-Forward Backtesting UI — nur Anzeige, Logik auf Server."""

    POLL_INTERVAL = 30      # Fallback-Polling (WS-primär, Polling nur Sicherheitsnetz)
    MAX_POLL_FAILS = 10     # Max fehlgeschlagene Polls bevor Timeout

    def __init__(self, config_manager, db, app_mode, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager=config_manager, db=db, app_mode=app_mode, api_client=api_client,
                         app_db=app_db, backtest_db=backtest_db)
        self._current_task_id = None  # Server-Task ID (für Cancel)
        self._current_run_id = None   # Backtest-Run ID (für Polling)
        self._poll_timer_id = None
        self._poll_fail_count = 0
        self._chart_hitrate = None
        self._chart_features = None

        self._build_ui()

    def cleanup(self) -> None:
        """Timer und Poll-State aufräumen (z.B. beim Seitenwechsel oder Beenden)."""
        super().cleanup()
        if self._poll_timer_id:
            GLib.source_remove(self._poll_timer_id)
            self._poll_timer_id = None
        self._poll_fail_count = 0
        self._spinner.stop()
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("task_update", self._on_ws_task)
        except Exception:
            pass

    def refresh(self) -> None:
        """Daten nur neu laden wenn veraltet (>5min)."""
        if self.is_stale():
            self._load_latest()
        self._check_running_backtest()

    # ── UI ──

    def _build_ui(self) -> None:
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.append(scroll)

        clamp = Adw.Clamp(maximum_size=1100)
        scroll.set_child(clamp)

        self._content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=16,
            margin_top=16, margin_bottom=16, margin_start=16, margin_end=16,
        )
        clamp.set_child(self._content)

        # Header + Controls
        header = Gtk.Box(spacing=12, margin_bottom=8)
        title = Gtk.Label(label=_("Walk-Forward Backtest"))
        title.add_css_class("title-1")
        header.append(title)
        self._content.append(header)

        # Spieltyp-Auswahl (getrennt nach 6aus49 / EuroJackpot)
        controls = Gtk.Box(spacing=12)

        self._day_dropdown = Gtk.DropDown.new_from_strings(
            [opt[0] for opt in _GAME_OPTIONS],
        )
        self._day_dropdown.set_selected(0)
        self._day_dropdown.set_valign(Gtk.Align.CENTER)
        controls.append(self._day_dropdown)

        # Fenster-Größe
        window_box = Gtk.Box(spacing=4)
        window_box.append(Gtk.Label(label=_("Fenster:")))
        self._window_spin = Gtk.SpinButton.new_with_range(3, 36, 3)
        self._window_spin.set_value(12)
        self._window_spin.set_tooltip_text(_("Trainings-Fenster in Monaten"))
        self._window_spin.set_valign(Gtk.Align.CENTER)
        window_box.append(self._window_spin)
        window_box.append(Gtk.Label(label=_("Monate")))
        controls.append(window_box)

        # Step-Size
        step_box = Gtk.Box(spacing=4)
        step_box.append(Gtk.Label(label=_("Schritt:")))
        self._step_spin = Gtk.SpinButton.new_with_range(1, 10, 1)
        self._step_spin.set_value(1)
        self._step_spin.set_tooltip_text(_("Schrittweite (1 = jede Ziehung)"))
        self._step_spin.set_valign(Gtk.Align.CENTER)
        step_box.append(self._step_spin)
        controls.append(step_box)

        self._start_btn = Gtk.Button(label=_("Einzeltest"))
        self._start_btn.add_css_class("suggested-action")
        self._start_btn.set_tooltip_text(_("Einmaligen Backtest mit gewählten Einstellungen starten"))
        self._start_btn.connect("clicked", self._on_start)
        self.register_readonly_button(self._start_btn)
        controls.append(self._start_btn)

        self._optimize_btn = Gtk.Button(label=_("Auto-Optimize"))
        self._optimize_btn.add_css_class("suggested-action")
        self._optimize_btn.set_tooltip_text(_("Autonome Optimierung: testet Fenster, Zeiträume, Strategien bis Erfolg"))
        self._optimize_btn.connect("clicked", self._on_optimize)
        self.register_readonly_button(self._optimize_btn)
        controls.append(self._optimize_btn)

        self._cancel_btn = Gtk.Button(label=_("Abbrechen"))
        self._cancel_btn.add_css_class("destructive-action")
        self._cancel_btn.set_visible(False)
        self._cancel_btn.connect("clicked", self._on_cancel)
        controls.append(self._cancel_btn)

        self._spinner = Gtk.Spinner()
        controls.append(self._spinner)
        self._content.append(controls)

        # Status + Progress
        self._status_row = Adw.ActionRow(title=_("Status"), subtitle=_("Kein Backtest gestartet"))
        self._content.append(self._status_row)

        self._progress_bar = Gtk.ProgressBar(show_text=True)
        self._progress_bar.set_visible(False)
        self._content.append(self._progress_bar)

        # Charts (lazy init — matplotlib kann crashen)
        self._charts_built = False

        # Bewertung
        self._verdict_group = Adw.PreferencesGroup(title=_("Bewertung"))
        self._verdict_row = Adw.ActionRow(title=_("Ergebnis"), subtitle="—")
        self._verdict_group.add(self._verdict_row)
        self._verdict_msg = Adw.ActionRow(title=_("Details"), subtitle="—")
        self._verdict_group.add(self._verdict_msg)
        self._content.append(self._verdict_group)

        # Zusammenfassung
        self._summary_group = Adw.PreferencesGroup(title=_("Statistik"))
        self._best_row = Adw.ActionRow(title=_("Beste Strategie"), subtitle="—")
        self._summary_group.add(self._best_row)
        self._random_row = Adw.ActionRow(title=_("ML vs. Zufall"), subtitle="—")
        self._summary_group.add(self._random_row)
        self._steps_row = Adw.ActionRow(title=_("Schritte"), subtitle="—")
        self._summary_group.add(self._steps_row)
        self._predictions_row = Adw.ActionRow(
            title=_("Predictions für nächste Woche"),
            subtitle=_("Werden nach Backtest generiert"),
        )
        self._summary_group.add(self._predictions_row)
        self._content.append(self._summary_group)

        # Run-History
        self._history_group = Adw.PreferencesGroup(title=_("Backtest-Verlauf"))
        self._history_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._history_listbox.add_css_class("boxed-list")
        self._history_group.add(self._history_listbox)
        self._content.append(self._history_group)

    def _ensure_charts(self) -> None:
        """Charts lazy initialisieren (vermeidet Crash beim Seiten-Laden)."""
        if self._charts_built:
            return
        try:
            from lotto_analyzer.ui.widgets.chart_view import ChartView

            group1 = Adw.PreferencesGroup(
                title=_("Trefferquote pro Strategie"),
                description=_("Durchschnittliche Treffer und 3+ Quote"),
            )
            self._chart_hitrate = ChartView(figsize=(10, 4))
            group1.add(self._chart_hitrate)

            group2 = Adw.PreferencesGroup(
                title=_("Feature Importance"),
                description=_("Welche Features sind am wichtigsten für ML"),
            )
            self._chart_features = ChartView(figsize=(10, 3))
            group2.add(self._chart_features)

            # Charts vor Summary einfuegen
            pos = 4  # Nach Status + Progress
            self._content.insert_child_after(group1, self._progress_bar)
            self._content.insert_child_after(group2, group1)

            self._charts_built = True
        except Exception as e:
            logger.warning(f"Charts konnten nicht geladen werden: {e}")

    # ── Actions ──

    def _check_running_backtest(self) -> None:
        """Prüfen ob ein Backtest auf dem Server läuft (z.B. nach GUI-Neustart)."""
        if not self.api_client:
            return

        def worker():
            try:
                # Laufende Backtest-Runs suchen
                runs = self.api_client.get_backtest_runs(limit=5)
                running = [r for r in runs if r.get("status") == "running"]
                if running:
                    GLib.idle_add(self._resume_running, running[0])
            except Exception as e:
                logger.warning(f"Laufende Backtests suchen fehlgeschlagen: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _resume_running(self, run: dict) -> bool:
        """Laufenden Backtest im UI fortsetzen (nach GUI-Neustart)."""
        self._current_run_id = run.get("id")
        self._current_task_id = run.get("id")
        steps = run.get("step_count", 0)
        total = run.get("total_steps", 0)
        progress = run.get("progress", 0)
        day_label = _DAY_LABELS.get(run.get("draw_day", ""), "?")

        self._start_btn.set_sensitive(False)
        self._cancel_btn.set_visible(True)
        self._spinner.start()
        self._progress_bar.set_visible(True)
        self._progress_bar.set_fraction(progress)
        self._progress_bar.set_text(f"{progress:.0%}")
        self._status_row.set_subtitle(
            _("Läuft (fortgesetzt)") + f": {day_label} — " + _("Schritt") + f" {steps}/{total}"
        )

        # Polling starten + WS-Listener fuer instant Updates
        if not self._poll_timer_id:
            self._poll_timer_id = GLib.timeout_add_seconds(self.POLL_INTERVAL, self._poll_progress)
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.on("task_update", self._on_ws_task)
        except Exception:
            pass

        logger.info(f"Backtest {self._current_task_id} fortgesetzt ({steps}/{total})")
        return False

    def _on_optimize(self, _btn) -> None:
        """Auto-Optimize starten — 3 Phasen autonome Optimierung."""
        if self._is_readonly:
            return
        if not self.api_client:
            self._status_row.set_subtitle(_("Kein Server verbunden"))
            return

        draw_day = self._get_draw_day()
        step_size = int(self._step_spin.get_value())

        self._start_btn.set_sensitive(False)
        self._optimize_btn.set_sensitive(False)
        self._cancel_btn.set_visible(True)
        self._spinner.start()
        self._status_row.set_subtitle(_("Auto-Optimize wird gestartet..."))
        self._progress_bar.set_visible(True)
        self._progress_bar.set_fraction(0)

        def worker():
            try:
                result = self.api_client._request("POST", "/backtest/optimize", json={
                    "draw_day": draw_day,
                    "step_size": step_size,
                    "success_threshold": 4,
                }).json()
                task_id = result.get("task_id", "")
                GLib.idle_add(self._on_started, task_id)
            except Exception as e:
                GLib.idle_add(self._on_start_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _get_draw_day(self) -> str:
        idx = self._day_dropdown.get_selected()
        if idx < len(_GAME_OPTIONS):
            return _GAME_OPTIONS[idx][1]
        logger.warning(f"Ungültiger Dropdown-Index {idx}, Fallback auf 'saturday'")
        return "saturday"

    def _on_start(self, _btn) -> None:
        if self._is_readonly:
            return
        if not self.api_client:
            self._status_row.set_subtitle(_("Kein Server verbunden"))
            return

        draw_day = self._get_draw_day()
        window = int(self._window_spin.get_value())
        step_size = int(self._step_spin.get_value())

        self._start_btn.set_sensitive(False)
        self._cancel_btn.set_visible(True)
        self._spinner.start()
        self._status_row.set_subtitle(_("Wird gestartet..."))
        self._progress_bar.set_visible(True)
        self._progress_bar.set_fraction(0)

        def worker():
            try:
                result = self.api_client.start_backtest(
                    draw_day, window, step_size=step_size,
                )
                task_id = result.get("task_id", "")
                GLib.idle_add(self._on_started, task_id)
            except Exception as e:
                GLib.idle_add(self._on_start_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_started(self, task_id: str) -> bool:
        self._current_task_id = task_id
        self._current_run_id = None  # Wird beim ersten Poll ermittelt
        self._poll_fail_count = 0
        self._status_row.set_subtitle(f"{_('Läuft')}... (Task: {task_id[:8]})")
        # Alte Chart-Daten löschen
        if self._chart_hitrate:
            self._chart_hitrate.ax.clear()
            self._chart_hitrate.canvas.draw_idle()
        if self._chart_features:
            self._chart_features.ax.clear()
            self._chart_features.canvas.draw_idle()
        if self._poll_timer_id:
            GLib.source_remove(self._poll_timer_id)
        self._poll_timer_id = GLib.timeout_add_seconds(self.POLL_INTERVAL, self._poll_progress)
        return False

    def _on_cancel(self, _btn) -> None:
        """Laufenden Backtest abbrechen."""
        if not self.api_client:
            return
        task_id = getattr(self, "_current_task_id", None)
        if not task_id:
            return

        self._cancel_btn.set_sensitive(False)
        self._status_row.set_subtitle(_("Wird abgebrochen..."))

        def worker():
            try:
                self.api_client.cancel_task(task_id)
                GLib.idle_add(self._on_cancelled)
            except Exception as e:
                GLib.idle_add(self._on_cancel_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_cancelled(self) -> bool:
        self._spinner.stop()
        self._start_btn.set_sensitive(not self._is_readonly)
        self._optimize_btn.set_sensitive(not self._is_readonly)
        self._cancel_btn.set_visible(False)
        self._progress_bar.set_visible(False)
        self._status_row.set_subtitle(_("Abgebrochen"))
        if self._poll_timer_id:
            GLib.source_remove(self._poll_timer_id)
            self._poll_timer_id = None
        return False

    def _on_cancel_error(self, error: str) -> bool:
        self._cancel_btn.set_sensitive(True)
        self._status_row.set_subtitle(_("Abbruch fehlgeschlagen") + f": {error}")
        return False

    def _on_start_error(self, error: str) -> bool:
        self._start_btn.set_sensitive(not self._is_readonly)
        self._optimize_btn.set_sensitive(not self._is_readonly)
        self._cancel_btn.set_visible(False)
        self._spinner.stop()
        self._progress_bar.set_visible(False)
        self._status_row.set_subtitle(_("Fehler") + f": {error}")
        return False

    def _on_ws_task(self, data: dict) -> bool:
        """Handle WS task_update — trigger instant progress refresh."""
        task_id = data.get("id", "")
        if task_id == self._current_task_id:
            # Direkt Progress aus WS-Event anzeigen
            progress = data.get("progress", 0)
            if progress > 0:
                self._progress_bar.set_fraction(progress)
                self._progress_bar.set_text(f"{progress:.0%}")
            status = data.get("status", "")
            if status in ("completed", "failed", "cancelled"):
                self._poll_progress()
        return False

    def _poll_progress(self) -> bool:
        if not self.api_client:
            self._poll_timer_id = None
            return False

        def worker():
            try:
                run = None
                # Bevorzugt: konkreten Run per ID abfragen
                if self._current_run_id:
                    run = self.api_client.get_backtest_run(self._current_run_id)
                if not run:
                    # Fallback: letzten Run für den Spieltag suchen
                    runs = self.api_client.get_backtest_runs(self._get_draw_day(), limit=1)
                    if runs:
                        run = runs[0]
                        self._current_run_id = run.get("id")
                if run:
                    self._poll_fail_count = 0
                    GLib.idle_add(self._on_progress_update, run)
                else:
                    self._poll_fail_count += 1
            except Exception as e:
                logger.warning(f"Backtest-Polling fehlgeschlagen: {e}")
                self._poll_fail_count += 1

            if self._poll_fail_count >= self.MAX_POLL_FAILS:
                GLib.idle_add(self._on_start_error, _("Polling-Timeout: Kein Backtest gefunden"))

        threading.Thread(target=worker, daemon=True).start()
        keep_running = self._poll_fail_count < self.MAX_POLL_FAILS
        if not keep_running:
            self._poll_timer_id = None
        return keep_running

    def _on_progress_update(self, run: dict) -> bool:
        status = run.get("status", "")
        progress = run.get("progress", 0)

        self._progress_bar.set_fraction(progress)
        self._progress_bar.set_text(f"{progress:.0%}")

        if status in ("completed", "cancelled"):
            self._spinner.stop()
            self._start_btn.set_sensitive(not self._is_readonly)
            self._optimize_btn.set_sensitive(not self._is_readonly)
            self._cancel_btn.set_visible(False)
            self._progress_bar.set_visible(False)
            label = _("Abgeschlossen") if status == "completed" else _("Abgebrochen")
            self._status_row.set_subtitle(label)
            if self._poll_timer_id:
                GLib.source_remove(self._poll_timer_id)
                self._poll_timer_id = None
            self._show_results(run)
            self._load_latest()
        elif status == "failed":
            self._spinner.stop()
            self._start_btn.set_sensitive(True)
            self._optimize_btn.set_sensitive(True)
            self._cancel_btn.set_visible(False)
            self._progress_bar.set_visible(False)
            summary = run.get("result_summary", "")
            self._status_row.set_subtitle(_("Fehlgeschlagen") + f": {summary[:100]}")
            if self._poll_timer_id:
                GLib.source_remove(self._poll_timer_id)
                self._poll_timer_id = None
        else:
            steps = run.get("step_count", 0)
            total = run.get("total_steps", 0)
            self._status_row.set_subtitle(_("Schritt") + f" {steps}/{total}")

        return False

    # ── Ergebnisse ──

    def _load_latest(self) -> None:
        if not self.api_client:
            return

        def worker():
            try:
                draw_day = self._get_draw_day()
                run = self.api_client.get_backtest_latest(draw_day)
                if run:
                    GLib.idle_add(self._show_results, run)
                runs = self.api_client.get_backtest_runs(limit=50)
                GLib.idle_add(self._show_history, runs)
            except Exception as e:
                logger.warning(f"Backtest-Ergebnisse laden fehlgeschlagen: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _show_results(self, run: dict) -> bool:
        self.mark_refreshed()
        best = run.get("best_strategy", "?")
        random_avg = run.get("random_baseline_avg", 0)
        avg = run.get("avg_matches", 0)
        day_label = _DAY_LABELS.get(run.get("draw_day", ""), "?")

        self._best_row.set_subtitle(f"{best.capitalize()} ({day_label})")
        if random_avg > 0:
            ratio = avg / random_avg
            self._random_row.set_subtitle(f"{ratio:.2f}x (ML: {avg:.3f}, {_('Zufall')}: {random_avg:.3f})")
        else:
            self._random_row.set_subtitle(f"Avg: {avg:.3f}")
        self._steps_row.set_subtitle(
            f"{run.get('step_count', 0)} {_('von')} {run.get('total_steps', 0)} "
            f"({run.get('window_months', '?')} {_('Monate Fenster')})"
        )

        try:
            summary = json.loads(run.get("result_summary", "{}"))
            self._ensure_charts()
            if summary and self._chart_hitrate:
                self._plot_strategy_chart(summary)

            # Verdict anzeigen
            verdict = summary.get("_verdict", {})
            if verdict:
                rating = verdict.get("rating", "—")
                self._verdict_row.set_subtitle(rating)
                self._verdict_msg.set_subtitle(verdict.get("message", "—"))
                # Farbe je nach Rating
                for css in ("success", "warning", "error"):
                    self._verdict_row.remove_css_class(css)
                if rating in ("SEHR GUT", "GUT"):
                    self._verdict_row.add_css_class("success")
                elif rating in ("LEICHT BESSER", "NEUTRAL"):
                    self._verdict_row.add_css_class("warning")
                else:
                    self._verdict_row.add_css_class("error")

            # Predictions-Info
            total_steps = run.get("total_steps", 0)
            strat_count = len([s for s in summary if not s.startswith("_")])
            self._predictions_row.set_subtitle(
                f"{strat_count * 3} " + _("Predictions generiert (3 pro Strategie)")
            )
        except (json.JSONDecodeError, TypeError):
            pass

        return False

    def _plot_strategy_chart(self, summary: dict) -> None:
        if not summary or not self._chart_hitrate:
            return

        names = []
        avgs = []
        for strat, data in sorted(summary.items(), key=lambda x: -x[1].get("avg_matches", 0) if isinstance(x[1], dict) else 0):
            if strat.startswith("_"):
                continue
            if not isinstance(data, dict):
                continue
            names.append(strat.capitalize())
            avgs.append(data.get("avg_matches", 0))

        if names:
            self._chart_hitrate.plot_bar(
                names, avgs,
                title=_("Durchschnittliche Treffer pro Strategie"),
                xlabel=_("Strategie"), ylabel=_("Avg. Treffer"),
                highlight_indices=[0],
            )

    def _show_history(self, runs: list) -> bool:
        while True:
            row = self._history_listbox.get_row_at_index(0)
            if row is None:
                break
            self._history_listbox.remove(row)

        if not runs:
            self._history_listbox.append(
                Adw.ActionRow(title=_("Keine Backtests"), subtitle=_("Starte den ersten!"))
            )
            return False

        for run in runs:
            day_label = _DAY_LABELS.get(run.get("draw_day", ""), "?")
            status = run.get("status", "?")
            best = run.get("best_strategy", "—")
            window = run.get("window_months", "?")
            created = run.get("created_at", "")[:16]
            steps = run.get("step_count", 0)
            total = run.get("total_steps", 0)

            row = Adw.ActionRow(
                title=f"{day_label} — {window}mo Fenster ({status})",
                subtitle=f"{_('Beste')}: {best} | {steps}/{total} {_('Schritte')} | {created}",
            )
            self._history_listbox.append(row)

        return False
