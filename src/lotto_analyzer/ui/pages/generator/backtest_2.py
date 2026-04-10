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




class BacktestMixin2:
    """Teil 2 von BacktestMixin."""

    def _find_backtest_anomalies(
        self, strat_matches: dict[str, list[int]],
        dates: list[str], window: int = 10,
    ) -> list[str]:
        """Auffaellige Phasen im Backtest-Verlauf finden."""
        anomalies: list[str] = []

        for strat, matches in strat_matches.items():
            if strat == "random" or len(matches) < window * 2:
                continue

            # Gleitender Durchschnitt
            best_avg = 0.0
            best_start = 0
            worst_avg = float("inf")
            worst_start = 0

            for i in range(len(matches) - window + 1):
                window_avg = sum(matches[i:i + window]) / window
                if window_avg > best_avg:
                    best_avg = window_avg
                    best_start = i
                if window_avg < worst_avg:
                    worst_avg = window_avg
                    worst_start = i

            if best_avg > 1.5:
                start_date = dates[best_start] if best_start < len(dates) else "?"
                end_date = dates[min(best_start + window - 1, len(dates) - 1)]
                anomalies.append(
                    f"  {strat}: Beste Phase {start_date}—{end_date} "
                    f"(Ø {best_avg:.2f} Treffer)"
                )

            if worst_avg < 0.5 and best_avg > 1.0:
                start_date = dates[worst_start] if worst_start < len(dates) else "?"
                end_date = dates[min(worst_start + window - 1, len(dates) - 1)]
                anomalies.append(
                    f"  {strat}: Schwache Phase {start_date}—{end_date} "
                    f"(Ø {worst_avg:.2f} Treffer)"
                )

        return anomalies

    # ══════════════════════════════════════════════
    # Beide Modi: Statistik + Backtest
    # ══════════════════════════════════════════════

    def _on_generate_beide(self) -> None:
        """Beide Modi ausführen: Statistik-Predictions + Backtest-Predictions — via Server."""
        if not self.api_client:
            from lotto_analyzer.ui.helpers import show_error_toast
            show_error_toast(self, _("Serververbindung erforderlich"))
            with self._op_lock:
                self._generating = False
            return

        self._gen_btn.set_sensitive(False)
        self._spinner.set_visible(True)
        self._spinner.start()

        draw_day = self._get_draw_day()
        count = int(self._count_spin.get_value())
        window_months = int(self._bt_window_spin.get_value())
        selected_strategies = self._get_selected_strategies()
        custom_weights = self._get_custom_weights() if hasattr(self, '_weight_sliders') else None

        if not selected_strategies:
            selected_strategies = [Strategy.ENSEMBLE]

        self._status_label.set_label(
            _("Phase 1/2: Statistik-Predictions generieren...")
        )

        def worker():
            stat_results: list[GenerationResult] = []
            stat_strategies: list[str] = []
            bt_results: list[GenerationResult] = []
            bt_strategies: list[str] = []
            bt_steps: list[dict] = []
            bt_run_id = ""

            try:
                # ── Phase 1: Statistik-Predictions via API ──
                strategy_name = ",".join(s.value for s in selected_strategies)
                data = self.api_client.generate_batch(
                    strategy=strategy_name,
                    draw_day=draw_day.value,
                    count=count,
                    custom_weights=custom_weights,
                )
                for r in data.get("results", []):
                    gr = GenerationResult(
                        numbers=r["numbers"],
                        super_number=r.get("super_number", 0),
                        strategy=r.get("strategy", ""),
                        reasoning=r.get("reasoning", ""),
                        confidence=r.get("confidence", 0.0),
                    )
                    stat_results.append(gr)
                    stat_strategies.append(r.get("strategy", ""))

                stat_count = len(stat_results)
                GLib.idle_add(
                    self._status_label.set_label,
                    f"Phase 1/2: {stat_count} Statistik-Tipps -- "
                    + _("Phase 2/2: Backtest läuft") + f" ({window_months} " + _("Monate") + ")...",
                )

                # ── Phase 2: Backtest-Predictions via API ──
                data = self.api_client.start_backtest(
                    draw_day=draw_day.value,
                    window_months=window_months,
                )
                task_id = data.get("task_id") or data.get("run_id", "")
                if task_id:
                    import time
                    import json
                    start = time.monotonic()
                    while not self._cancel_event.is_set():
                        self._cancel_event.wait(5)
                        if self._cancel_event.is_set():
                            break
                        if time.monotonic() - start > self.POLL_TIMEOUT_SECONDS:
                            break
                        try:
                            task = self.api_client.get_task(task_id)
                        except Exception as e:
                            logger.warning(f"Task {task_id} abfragen fehlgeschlagen: {e}")
                            continue
                        status = task.get("status", "?")
                        if status == "completed":
                            result_raw = task.get("result")
                            result = json.loads(result_raw) if isinstance(result_raw, str) else (result_raw or {})
                            bt_run_id = result.get("run_id", task_id)
                            next_date = _get_next_draw_date(draw_day)
                            resp = self.api_client.get_predictions(
                                draw_day=draw_day.value,
                                draw_date=next_date.isoformat(),
                                limit=500,
                            )
                            for p in resp.get("predictions", []):
                                if not p.get("strategy", "").startswith("backtest_"):
                                    continue
                                nums_raw = p.get("predicted_numbers", "")
                                nums = [int(n) for n in nums_raw.split(",") if n.strip()] if isinstance(nums_raw, str) else list(nums_raw)
                                gr = GenerationResult(numbers=nums, strategy=p.get("strategy", ""), confidence=p.get("ml_confidence", 0.5))
                                bt_results.append(gr)
                                bt_strategies.append(p.get("strategy", ""))
                            try:
                                bt_steps = self.api_client.get_backtest_results(bt_run_id)
                            except Exception as e:
                                logger.warning(f"Backtest-Ergebnisse laden fehlgeschlagen: {e}")
                            break
                        elif status in ("failed", "cancelled"):
                            break
                        pct = int(task.get("progress", 0) * 100)
                        GLib.idle_add(
                            self._status_label.set_label,
                            f"Phase 1/2: {stat_count} Statistik-Tipps -- Backtest {pct}%...",
                        )

                # ── Ergebnisse zusammenfuehren ──
                all_results = stat_results + bt_results
                all_strategies = stat_strategies + bt_strategies

                summary = (
                    f"{len(stat_results)} Statistik + {len(bt_results)} Backtest = "
                    f"{len(all_results)} Predictions gespeichert"
                )
                GLib.idle_add(
                    self._on_beide_done,
                    all_results, all_strategies, summary, None,
                    bt_run_id, bt_steps,
                )
            except Exception as e:
                logger.error(f"Beide-Modi-Generierung fehlgeschlagen: {e}")
                # Statistik-Ergebnisse trotzdem zeigen wenn vorhanden
                if stat_results:
                    GLib.idle_add(
                        self._on_beide_done,
                        stat_results, stat_strategies,
                        f"{len(stat_results)} Statistik-Tipps (Backtest fehlgeschlagen: {e})",
                        None, "", [],
                    )
                else:
                    GLib.idle_add(
                        self._on_beide_done, [], [], "", str(e), "", [],
                    )

        self._cancel_event.clear()
        threading.Thread(target=worker, daemon=True).start()

    def _on_beide_done(
        self, results: list[GenerationResult], strategies: list[str],
        summary: str, error: str | None,
        bt_run_id: str = "", bt_steps: list[dict] | None = None,
    ) -> bool:
        """Beide-Modi-Generierung abgeschlossen."""
        with self._op_lock:
            self._generating = False
        self._gen_btn.set_sensitive(not self._is_readonly)
        self._spinner.stop()
        self._spinner.set_visible(False)

        if error:
            self._status_label.set_label(_("Fehler") + f": {error}")
            return False

        self._results = results
        self._result_strategies = strategies
        self._ai_top_picks = set()
        self._compare_btn.set_sensitive(bool(results))
        self._populate_results()
        self._load_prediction_dates()

        self._status_label.set_label(summary)

        # Backtest-Verlauf anzeigen wenn vorhanden
        if bt_steps:
            self._show_backtest_verlauf(bt_run_id, bt_steps)

        return False

    def _start_ai_analysis(self, results: list[GenerationResult]) -> None:
        """AI-Analyse aller Ergebnisse im Hintergrund starten."""
        self._status_label.set_label(
            f"{len(results)} Tipps generiert — AI analysiert Ergebnisse..."
        )
        self._spinner.set_visible(True)
        self._spinner.start()

        result_dicts = [
            {
                "numbers": sorted(r.numbers),
                "strategy": r.strategy,
                "confidence": r.confidence,
            }
            for r in results
        ]

        draw_day = self._get_draw_day().value

        def worker():
            try:
                ai_result = None
                if self.api_client:
                    try:
                        ai_result = self.api_client.ai_analyze_predictions(
                            results=result_dicts,
                            draw_day=draw_day,
                        )
                    except Exception as e:
                        logger.warning(f"AI-Analyse via API fehlgeschlagen: {e}")

                if ai_result:
                    GLib.idle_add(self._on_ai_analysis_done, ai_result)
                else:
                    GLib.idle_add(self._on_ai_analysis_done, None)
            except Exception as e:
                logger.warning(f"AI-Analyse fehlgeschlagen: {e}")
                GLib.idle_add(self._on_ai_analysis_done, None)

        threading.Thread(target=worker, daemon=True).start()

    def _on_ai_analysis_done(self, ai_result: dict | None) -> bool:
        """AI-Analyse abgeschlossen — Top-Picks markieren."""
        self._spinner.stop()
        self._spinner.set_visible(False)

        if not ai_result or not ai_result.get("top_picks"):
            total = len(self._results) if self._results else 0
            self._status_label.set_label(
                f"{total} Tipps generiert für {self._current_draw_date}"
            )
            return False

        top_picks = ai_result.get("top_picks", [])
        analysis = ai_result.get("analysis", "")
        self._ai_top_picks = set(top_picks)

        # Ergebnisse nach AI-Score sortieren: Top-Picks zuerst
        if self._results and top_picks:
            ranked = ai_result.get("ranked", [])
            # Score-Map erstellen (index → score)
            score_map: dict[int, float] = {}
            for entry in ranked:
                idx = entry.get("index", 0)
                # AI gibt 1-basierte Indizes zurück
                idx_0 = (idx - 1) if idx > 0 else idx
                score_map[idx_0] = entry.get("score", 5)

            # Ergebnisse mit AI-Score anreichern und sortieren
            indexed = list(enumerate(self._results))
            indexed.sort(
                key=lambda x: (
                    0 if x[0] in self._ai_top_picks else 1,
                    -score_map.get(x[0], 5),
                ),
            )
            self._results = [r for _, r in indexed]
            self._result_strategies = [
                self._result_strategies[i] if i < len(self._result_strategies)
                else r.strategy
                for i, r in indexed
            ]
            # Top-Picks auf neue Indizes umrechnen
            old_to_new = {old_i: new_i for new_i, (old_i, _) in enumerate(indexed)}
            self._ai_top_picks = {
                old_to_new[p] for p in top_picks if p in old_to_new
            }

            self._populate_results()

        pick_count = len(self._ai_top_picks)
        total = len(self._results)
        analysis_short = analysis[:100] + "..." if len(analysis) > 100 else analysis
        self._status_label.set_label(
            f"{total} Tipps — AI Top-{pick_count} markiert. {analysis_short}"
        )

        return False

