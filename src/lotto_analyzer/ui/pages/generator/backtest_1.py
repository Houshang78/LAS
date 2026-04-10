"""Generator-Seite: Backtest Mixin."""

import threading
from datetime import date, datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_analyzer.ui.pages.generator.page import _get_next_draw_date
try:
    from lotto_analyzer.ui.widgets.chart_view import ChartView
except ImportError:
    ChartView = None
from lotto_common.models.analysis import PredictionRecord

logger = get_logger("generator.backtest")



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




class BacktestMixin1:
    """Teil 1 von BacktestMixin."""

    def _on_generate_backtest(self) -> None:
        """Backtest-basierte Generierung: Walk-Forward + Predictions."""
        self._gen_btn.set_sensitive(False)
        self._spinner.set_visible(True)
        self._spinner.start()

        draw_day = self._get_draw_day()
        window_months = int(self._bt_window_spin.get_value())
        tips_per_strategy = int(self._bt_tips_spin.get_value())

        self._status_label.set_label(
            _("Backtest läuft") + f" ({window_months} " + _("Monate") + ")..."
        )

        if not self.api_client:
            from lotto_analyzer.ui.helpers import show_error_toast
            show_error_toast(self, _("Serververbindung erforderlich"))
            with self._op_lock:
                self._generating = False
            self._gen_btn.set_sensitive(not self._is_readonly)
            self._spinner.stop()
            self._spinner.set_visible(False)
            return

        self._on_generate_backtest_client(draw_day, window_months, tips_per_strategy)

    def _on_generate_backtest_client(
        self, draw_day: DrawDay, window_months: int, tips_per_strategy: int,
    ) -> None:
        """Backtest-Generierung via Server (Client-Modus)."""
        def worker():
            try:
                # Backtest auf Server starten
                data = self.api_client.start_backtest(
                    draw_day=draw_day.value,
                    window_months=window_months,
                )
                task_id = data.get("task_id") or data.get("run_id", "")

                if not task_id:
                    GLib.idle_add(self._on_backtest_generate_done, [], [], "", "Kein Task-ID erhalten")
                    return

                # Polling bis fertig
                import time
                start = time.monotonic()
                while not self._cancel_event.is_set():
                    self._cancel_event.wait(5)
                    if self._cancel_event.is_set():
                        return
                    if time.monotonic() - start > self.POLL_TIMEOUT_SECONDS:
                        GLib.idle_add(self._on_backtest_generate_done, [], [], "", "Timeout")
                        return

                    try:
                        task = self.api_client.get_task(task_id)
                    except Exception as e:
                        logger.warning(f"Task {task_id} abfragen fehlgeschlagen: {e}")
                        continue

                    status = task.get("status", "?")
                    progress = task.get("progress", 0)
                    pct = int(progress * 100)
                    GLib.idle_add(
                        self._status_label.set_label,
                        f"Backtest {pct}%...",
                    )

                    if status == "completed":
                        # Predictions laden
                        next_date = _get_next_draw_date(draw_day)
                        resp = self.api_client.get_predictions(
                            draw_day=draw_day.value,
                            draw_date=next_date.isoformat(),
                            limit=500,
                        )
                        preds = resp.get("predictions", [])
                        bt_preds = [p for p in preds if p.get("strategy", "").startswith("backtest_")]

                        results = []
                        strategies = []
                        for p in bt_preds:
                            nums_raw = p.get("predicted_numbers", "")
                            if isinstance(nums_raw, str):
                                numbers = [int(n) for n in nums_raw.split(",") if n.strip()]
                            else:
                                numbers = list(nums_raw)
                            strat = p.get("strategy", "")
                            gr = GenerationResult(
                                numbers=numbers,
                                strategy=strat,
                                confidence=p.get("ml_confidence", 0.5),
                            )
                            results.append(gr)
                            strategies.append(strat)

                        import json
                        result_raw = task.get("result")
                        result = json.loads(result_raw) if isinstance(result_raw, str) else (result_raw or {})
                        best_strat = result.get("best_strategy", "?")
                        avg = result.get("avg_matches", 0)
                        run_id = result.get("run_id", task_id)
                        summary = f"Backtest: {len(results)} Tipps, beste: {best_strat} (Ø {avg:.3f})"
                        # Backtest-Schritte via API laden
                        bt_steps = []
                        try:
                            bt_steps = self.api_client.get_backtest_results(run_id)
                        except Exception as e:
                            logger.warning(f"Backtest-Ergebnisse laden fehlgeschlagen: {e}")
                        GLib.idle_add(
                            self._on_backtest_generate_done,
                            results, strategies, summary, None, run_id, bt_steps,
                        )
                        return

                    elif status in ("failed", "cancelled"):
                        error = task.get("error", "Unbekannter Fehler")
                        GLib.idle_add(self._on_backtest_generate_done, [], [], "", error, "", [])
                        return

            except Exception as e:
                GLib.idle_add(self._on_backtest_generate_done, [], [], "", str(e), "", [])

        self._cancel_event.clear()
        threading.Thread(target=worker, daemon=True).start()

    def _on_backtest_generate_done(
        self, results: list[GenerationResult], strategies: list[str],
        summary: str, error: str | None,
        run_id: str = "", bt_steps: list[dict] | None = None,
    ) -> bool:
        """Backtest-Generierung abgeschlossen — Ergebnisse + Verlauf anzeigen."""
        with self._op_lock:
            self._generating = False
        self._gen_btn.set_sensitive(not self._is_readonly)
        self._spinner.stop()
        self._spinner.set_visible(False)

        if error:
            self._status_label.set_label(_("Backtest-Fehler") + f": {error}")
            return False

        self._results = results
        self._result_strategies = strategies
        self._ai_top_picks = set()
        self._compare_btn.set_sensitive(bool(results))
        self._populate_results()
        self._status_label.set_label(summary)

        # Backtest-Verlauf anzeigen (Charts + Analyse)
        if bt_steps:
            self._show_backtest_verlauf(run_id, bt_steps)

        return False

    def _show_backtest_verlauf(self, run_id: str, bt_steps: list[dict]) -> None:
        """Backtest-Verlauf mit Charts und Strategie-Analyse anzeigen."""
        import json as json_mod

        # Container erstellen/leeren
        if not hasattr(self, '_bt_verlauf_frame'):
            self._bt_verlauf_frame = Gtk.Frame()
            self._bt_verlauf_box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=12,
            )
            self._bt_verlauf_box.set_margin_top(16)
            self._bt_verlauf_box.set_margin_bottom(16)
            self._bt_verlauf_box.set_margin_start(16)
            self._bt_verlauf_box.set_margin_end(16)

            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_min_content_height(200)
            scroll.set_max_content_height(800)
            scroll.set_child(self._bt_verlauf_box)
            self._bt_verlauf_frame.set_child(scroll)

            # Nach der Ergebnis-Tabelle einfuegen
            self._content.insert_child_after(
                self._bt_verlauf_frame, self._results_frame,
            )

        # Container leeren
        while self._bt_verlauf_box.get_first_child():
            self._bt_verlauf_box.remove(self._bt_verlauf_box.get_first_child())
        self._bt_verlauf_frame.set_visible(True)

        # ── Titel ──
        title = Gtk.Label(label=f"Backtest-Verlauf — {run_id}")
        title.add_css_class("title-2")
        title.set_xalign(0)
        self._bt_verlauf_box.append(title)

        # ── Daten aufbereiten ──
        dates: list[str] = []
        strat_matches: dict[str, list[int]] = {}
        rf_scores: list[float] = []
        gb_scores: list[float] = []
        best_weeks: list[dict] = []  # Wochen mit >=3 Treffern

        for step in bt_steps:
            draw_date = step.get("draw_date", "")
            dates.append(draw_date)
            rf_scores.append(step.get("rf_score", 0) or 0)
            gb_scores.append(step.get("gb_score", 0) or 0)

            try:
                sr = json_mod.loads(step.get("strategy_results", "{}"))
            except (json_mod.JSONDecodeError, TypeError):
                sr = {}

            for strat, data in sr.items():
                strat_matches.setdefault(strat, [])
                m = data.get("matches", 0)
                strat_matches[strat].append(m)
                if m >= 3:
                    best_weeks.append({
                        "date": draw_date, "strategy": strat,
                        "matches": m, "numbers": data.get("numbers", []),
                    })

        total_steps = len(dates)
        if total_steps == 0:
            self._bt_verlauf_box.append(
                Gtk.Label(label=_("Keine Backtest-Ergebnisse vorhanden."))
            )
            return

        # ── Chart 1: Treffer pro Woche (alle Strategien) ──
        try:
            from lotto_analyzer.ui.widgets.chart_view import ChartView

            chart_matches = ChartView(figsize=(10, 4))
            chart_matches.ax.clear()
            x_idx = list(range(total_steps))
            x_labels = [d[5:] if len(d) > 5 else d for d in dates]  # MM-DD

            for strat, matches in strat_matches.items():
                if strat == "random":
                    chart_matches.ax.plot(
                        x_idx[:len(matches)], matches,
                        linestyle="--", alpha=0.5, color="gray", label="Random",
                    )
                else:
                    chart_matches.ax.plot(
                        x_idx[:len(matches)], matches,
                        linewidth=1.5, alpha=0.8, label=strat.capitalize(), marker="",
                    )

            chart_matches.ax.axhline(y=3, color="red", linestyle=":", alpha=0.5, label="3er-Schwelle")
            chart_matches.ax.set_title("Treffer pro Ziehung (Walk-Forward)", fontsize=12, fontweight="bold")
            chart_matches.ax.set_xlabel("Ziehung")
            chart_matches.ax.set_ylabel("Treffer")
            chart_matches.ax.legend(loc="upper right", fontsize=7, ncol=3)
            chart_matches.ax.grid(True, alpha=0.3)

            # X-Achse: nur jeden N-ten Label zeigen
            tick_step = max(1, total_steps // 15)
            chart_matches.ax.set_xticks(x_idx[::tick_step])
            chart_matches.ax.set_xticklabels(x_labels[::tick_step], rotation=45, fontsize=7)
            chart_matches._safe_draw()

            self._bt_verlauf_box.append(chart_matches)
        except Exception as e:
            logger.warning(f"Backtest-Chart Treffer fehlgeschlagen: {e}")

        # ── Chart 2: ML-Modell Accuracy (RF vs GB) ──
        try:
            if any(s > 0 for s in rf_scores) or any(s > 0 for s in gb_scores):
                chart_ml = ChartView(figsize=(10, 3))
                chart_ml.ax.clear()
                chart_ml.ax.plot(x_idx, rf_scores, label="Random Forest", color="#e01b24", linewidth=1.5)
                chart_ml.ax.plot(x_idx, gb_scores, label="Gradient Boosting", color="#1c71d8", linewidth=1.5)
                chart_ml.ax.set_title("ML-Modell Accuracy pro Schritt", fontsize=12, fontweight="bold")
                chart_ml.ax.set_xlabel("Schritt")
                chart_ml.ax.set_ylabel("Accuracy")
                chart_ml.ax.legend(loc="upper right", fontsize=8)
                chart_ml.ax.grid(True, alpha=0.3)
                tick_step = max(1, total_steps // 15)
                chart_ml.ax.set_xticks(x_idx[::tick_step])
                chart_ml.ax.set_xticklabels(x_labels[::tick_step], rotation=45, fontsize=7)
                chart_ml._safe_draw()
                self._bt_verlauf_box.append(chart_ml)
        except Exception as e:
            logger.warning(f"Backtest-Chart ML fehlgeschlagen: {e}")

        # ── Strategie-Vergleich Tabelle ──
        comp_title = Gtk.Label(label=_("Strategie-Vergleich"))
        comp_title.add_css_class("title-3")
        comp_title.set_xalign(0)
        comp_title.set_margin_top(8)
        self._bt_verlauf_box.append(comp_title)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_start(8)
        header.set_margin_end(8)
        for text, width in [
            ("Strategie", 120), ("Ø Treffer", 80), ("3+ Treffer", 80),
            ("Hit-Rate %", 80), ("Max", 50), ("vs Random", 80),
        ]:
            lbl = Gtk.Label(label=text)
            lbl.add_css_class("heading")
            lbl.set_size_request(width, -1)
            lbl.set_xalign(0)
            header.append(lbl)
        self._bt_verlauf_box.append(header)
        self._bt_verlauf_box.append(Gtk.Separator())

        # Random-Baseline
        random_matches = strat_matches.get("random", [])
        random_avg = sum(random_matches) / len(random_matches) if random_matches else 0

        # Zeilen sortiert nach avg
        sorted_strats = sorted(
            strat_matches.items(),
            key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0,
            reverse=True,
        )

        for strat, matches in sorted_strats:
            if not matches:
                continue
            avg = sum(matches) / len(matches)
            wins_3plus = sum(1 for m in matches if m >= 3)
            hit_rate = (wins_3plus / len(matches)) * 100
            max_m = max(matches)
            vs_random = f"{avg - random_avg:+.3f}" if random_avg > 0 else "—"

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.set_margin_start(8)
            row.set_margin_end(8)
            row.set_margin_top(2)
            row.set_margin_bottom(2)

            strat_lbl = Gtk.Label(label=strat.capitalize())
            strat_lbl.set_size_request(120, -1)
            strat_lbl.set_xalign(0)
            color = STRATEGY_COLORS.get(strat, "")
            if color:
                _apply_css(strat_lbl, f"label {{ color: {color}; font-weight: bold; }}".encode())
            row.append(strat_lbl)

            for text, width in [
                (f"{avg:.3f}", 80), (str(wins_3plus), 80),
                (f"{hit_rate:.1f}%", 80), (str(max_m), 50), (vs_random, 80),
            ]:
                lbl = Gtk.Label(label=text)
                lbl.set_size_request(width, -1)
                lbl.set_xalign(0)
                lbl.add_css_class("monospace")
                row.append(lbl)

            self._bt_verlauf_box.append(row)

        # ── Erfolgswochen (3+ Treffer) ──
        if best_weeks:
            success_title = Gtk.Label(
                label=f"{_('Erfolgswochen')} (3+ {_('Treffer')}): {len(best_weeks)}"
            )
            success_title.add_css_class("title-3")
            success_title.set_xalign(0)
            success_title.set_margin_top(12)
            self._bt_verlauf_box.append(success_title)

            # Sortiert nach Treffer (beste zuerst), max 20
            best_weeks.sort(key=lambda w: -w["matches"])
            for w in best_weeks[:20]:
                nums_str = " ".join(str(n) for n in w["numbers"])
                lbl = Gtk.Label(
                    label=f"  {w['date']}  {w['strategy']:12s}  {w['matches']}er  [{nums_str}]",
                )
                lbl.set_xalign(0)
                lbl.add_css_class("monospace")
                if w["matches"] >= 5:
                    lbl.add_css_class("success")
                elif w["matches"] >= 4:
                    lbl.add_css_class("warning")
                self._bt_verlauf_box.append(lbl)

        # ── Zeitraum-Info ──
        if dates:
            info_text = (
                f"\n{_('Zeitraum')}: {dates[0]} — {dates[-1]} "
                f"({total_steps} {_('Ziehungen')})\n"
                f"Random-Baseline: Ø {random_avg:.3f} {_('Treffer')}\n"
            )
            # Phasen mit Auffälligkeiten finden
            window_size = max(10, total_steps // 10)
            anomalies = self._find_backtest_anomalies(strat_matches, dates, window_size)
            if anomalies:
                info_text += f"\n{_('Auffälligkeiten')}:\n" + "\n".join(anomalies)

            info_label = Gtk.Label(label=info_text)
            info_label.set_xalign(0)
            info_label.set_wrap(True)
            info_label.set_selectable(True)
            info_label.set_margin_top(8)
            self._bt_verlauf_box.append(info_label)

