"""Prediction-Qualität: Historische Trefferquoten und Strategie-Trends."""

import json
import sqlite3
import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.i18n import _
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_analyzer.ui.widgets.chart_view import ChartView
from lotto_common.utils.logging_config import get_logger

logger = get_logger("prediction_quality")

# Ziehungstage: UI-Labels und zugehoerige API-Werte
DAY_LABELS = [_("Alle Tage"), _("Samstag"), _("Mittwoch"), _("Dienstag"), _("Freitag")]
DAY_VALUES = [None, "saturday", "wednesday", "tuesday", "friday"]


class PredictionQualityPage(BasePage):
    """Historische Prediction-Performance mit Charts."""

    def __init__(self, config_manager, db, app_mode, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager=config_manager, db=db, app_mode=app_mode, api_client=api_client,
                         app_db=app_db, backtest_db=backtest_db)

        self._build_ui()

    def refresh(self) -> None:
        """Daten nur neu laden wenn veraltet (>5min)."""
        if self.is_stale():
            self._load_data()

    # ── UI ──

    def _build_ui(self) -> None:
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.append(scroll)

        clamp = Adw.Clamp(maximum_size=1100)
        scroll.set_child(clamp)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=16,
            margin_top=16, margin_bottom=16, margin_start=16, margin_end=16,
        )
        clamp.set_child(content)

        # Header
        header = Gtk.Box(spacing=12)
        title = Gtk.Label(label=_("Prediction-Qualität"))
        title.add_css_class("title-1")
        header.append(title)

        self._day_dropdown = Gtk.DropDown.new_from_strings(DAY_LABELS)
        self._day_dropdown.set_selected(0)
        self._day_dropdown.connect("notify::selected", self._on_day_changed)
        self._day_dropdown.set_valign(Gtk.Align.CENTER)
        header.append(self._day_dropdown)

        self._spinner = Gtk.Spinner()
        header.append(self._spinner)
        content.append(header)

        # Chart 1: Trefferquote ueber Zeit (Linie)
        group1 = Adw.PreferencesGroup(
            title=_("Trefferquote ueber Zeit"),
            description=_("Prozent der Predictions mit 3+ Treffern pro Zyklus"),
        )
        self._chart_hitrate = ChartView(figsize=(10, 3))
        group1.add(self._chart_hitrate)
        content.append(group1)

        # Chart 2: Match-Verteilung (Balken)
        group2 = Adw.PreferencesGroup(
            title=_("Treffer-Verteilung"),
            description=_("Wie viele Predictions haben 0, 1, 2, 3, 4, 5, 6 Treffer"),
        )
        self._chart_distribution = ChartView(figsize=(10, 3))
        group2.add(self._chart_distribution)
        content.append(group2)

        # Chart 3: Strategie-Vergleich (Balken)
        group3 = Adw.PreferencesGroup(
            title=_("Strategie-Vergleich"),
            description=_("Durchschnittliche Treffer und Gewinnrate pro Strategie"),
        )
        self._chart_strategies = ChartView(figsize=(10, 3))
        group3.add(self._chart_strategies)
        content.append(group3)

        # Chart 4: ML-Training Fortschritt (Linie)
        group4 = Adw.PreferencesGroup(
            title=_("ML-Training Fortschritt"),
            description=_("LSTM-Loss und Modell-Genauigkeit ueber Zeit"),
        )
        self._chart_ml = ChartView(figsize=(10, 3))
        group4.add(self._chart_ml)
        content.append(group4)

        # Zusammenfassung
        self._summary_group = Adw.PreferencesGroup(title=_("Zusammenfassung"))
        self._total_row = Adw.ActionRow(title=_("Predictions gesamt"), subtitle="—")
        self._summary_group.add(self._total_row)
        self._best_row = Adw.ActionRow(title=_("Bester Treffer"), subtitle="—")
        self._summary_group.add(self._best_row)
        self._winrate_row = Adw.ActionRow(title=_("Gewinnrate (3+)"), subtitle="—")
        self._summary_group.add(self._winrate_row)
        self._best_strategy_row = Adw.ActionRow(title=_("Beste Strategie"), subtitle="—")
        self._summary_group.add(self._best_strategy_row)
        content.append(self._summary_group)

    # ── Daten laden ──

    def _get_selected_day(self) -> str | None:
        idx = self._day_dropdown.get_selected()
        return DAY_VALUES[idx] if idx < len(DAY_VALUES) else None

    def _on_day_changed(self, dropdown, _pspec) -> None:
        self._load_data()

    def _load_data(self) -> None:
        if not self.api_client and not self.db:
            return

        self._spinner.start()
        draw_day = self._get_selected_day()

        def worker():
            data = {"reports": [], "strategy": [], "training": [], "accuracy": {}}

            try:
                # Zyklus-Berichte (Trefferquote ueber Zeit)
                if self.api_client:
                    if draw_day:
                        data["reports"] = self.api_client.get_reports(
                            draw_day=draw_day, limit=50,
                        )
                    else:
                        data["reports"] = self.api_client.get_reports(limit=50)
                    if not isinstance(data["reports"], list):
                        logger.warning("get_reports: unerwarteter Typ %s", type(data["reports"]))
                        data["reports"] = []
                elif self.app_db:
                    data["reports"] = self.app_db.get_cycle_reports(
                        draw_day=draw_day, limit=50,
                    )
            except Exception as e:
                logger.warning(f"Reports laden fehlgeschlagen: {e}")

            try:
                # Strategie-Performance
                if self.api_client:
                    days = [draw_day] if draw_day else ["saturday", "wednesday", "tuesday", "friday"]
                    all_perf = []
                    for d in days:
                        try:
                            resp = self.api_client.strategy_performance(d)
                            if not isinstance(resp, (dict, list)):
                                logger.warning("strategy_performance(%s): unerwarteter Typ %s", d, type(resp))
                                continue
                            perf = resp.get("performance", []) if isinstance(resp, dict) else resp
                            all_perf.extend(perf if isinstance(perf, list) else [])
                        except Exception as e:
                            logger.warning(f"Performance laden fehlgeschlagen ({day_str}): {e}")
                    data["strategy"] = all_perf
                elif self.db:
                    data["strategy"] = self.db.get_strategy_performance(draw_day)
            except Exception as e:
                logger.warning(f"Strategy-Performance laden fehlgeschlagen: {e}")

            try:
                # ML-Training Runs
                if self.api_client:
                    # ML-Status als Fallback (kein /ml/training-runs Endpoint)
                    ml = self.api_client.ml_status()
                    if not isinstance(ml, dict):
                        logger.warning("ml_status: unerwarteter Typ %s", type(ml))
                        ml = {}
                    training_entries = []
                    for day_key, info in ml.items():
                        if isinstance(info, dict) and info.get("last_trained"):
                            training_entries.append({
                                "draw_day": day_key,
                                "created_at": info.get("last_trained"),
                                "test_loss": info.get("test_loss"),
                                "accuracy": info.get("accuracy", info.get("test_accuracy")),
                                "status": "completed",
                            })
                    data["training"] = training_entries
                elif self.db:
                    data["training"] = self.db.get_training_runs(
                        draw_day=draw_day, limit=30,
                    )
            except Exception as e:
                logger.warning(f"Training-Runs laden fehlgeschlagen: {e}")

            try:
                # Match-Verteilung (aus Berichten aggregieren)
                if data["reports"]:
                    total_compared = 0
                    total_3plus = 0
                    best_match = 0
                    for r in data["reports"]:
                        compared = r.get("predictions_compared", 0)
                        total_compared += compared
                        total_3plus += r.get("wins_3plus", 0)
                        bm = r.get("best_match", 0)
                        if bm > best_match:
                            best_match = bm
                    data["accuracy"] = {
                        "total": total_compared,
                        "wins_3plus": total_3plus,
                        "best_match": best_match,
                    }
            except Exception as e:
                logger.warning(f"Match-Verteilung berechnen fehlgeschlagen: {e}")

            GLib.idle_add(self._on_data_loaded, data)

        def safe_worker():
            try:
                worker()
            except (sqlite3.Error, ConnectionError, TimeoutError, OSError) as e:
                logger.warning(f"Prediction-Quality Daten laden fehlgeschlagen: {e}")
                GLib.idle_add(self._spinner.stop)
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler bei Prediction-Quality: {e}")
                GLib.idle_add(self._spinner.stop)

        threading.Thread(target=safe_worker, daemon=True).start()

    def _on_data_loaded(self, data: dict) -> bool:
        self.mark_refreshed()
        self._spinner.stop()

        reports = data.get("reports", [])
        strategy = data.get("strategy", [])
        training = data.get("training", [])
        accuracy = data.get("accuracy", {})

        self._plot_hitrate(reports)
        self._plot_distribution(reports)
        self._plot_strategies(strategy)
        self._plot_ml_progress(training)
        self._update_summary(accuracy, strategy)

        return False

    # ── Charts ──

    def _plot_hitrate(self, reports: list) -> None:
        """Trefferquote (3+) pro Zyklus als Linie."""
        if not reports:
            self._chart_hitrate.ax.clear()
            self._chart_hitrate.ax.set_title(_("Keine Daten"))
            self._chart_hitrate._safe_draw()
            return

        # Chronologisch sortieren
        sorted_reports = sorted(reports, key=lambda r: r.get("draw_date", ""))
        dates = []
        rates = []
        for r in sorted_reports:
            compared = r.get("predictions_compared", 0)
            if compared == 0:
                continue
            wins = r.get("wins_3plus", 0)
            rate = (wins / compared) * 100
            date_str = r.get("draw_date", "?")
            try:
                dt = datetime.fromisoformat(date_str[:10])
                date_str = dt.strftime("%d.%m.")
            except (ValueError, IndexError):
                date_str = date_str[:10] if len(date_str) >= 10 else date_str
            dates.append(date_str)
            rates.append(rate)

        if dates:
            self._chart_hitrate.plot_line(
                dates, rates,
                title=_("Trefferquote (3+ Treffer) pro Zyklus"),
                xlabel=_("Datum"), ylabel=_("Quote (%)"),
                color="#26a269",
            )
            # X-Labels rotieren
            self._chart_hitrate.ax.tick_params(axis="x", rotation=45, labelsize=7)
            self._chart_hitrate._safe_draw()

    def _plot_distribution(self, reports: list) -> None:
        """Match-Verteilung aus Berichten (Balken)."""
        if not reports:
            self._chart_distribution.ax.clear()
            self._chart_distribution.ax.set_title(_("Keine Daten"))
            self._chart_distribution._safe_draw()
            return

        # Match-Kategorien aus allen Berichten aggregieren
        cat_totals: dict[str, int] = {}
        for r in reports:
            cats = r.get("match_categories", {})
            if isinstance(cats, str):
                try:
                    cats = json.loads(cats)
                except Exception as e:
                    logger.warning(f"Kategorie-JSON Parsing fehlgeschlagen: {e}")
                    cats = {}
            if isinstance(cats, dict):
                for cat, cnt in cats.items():
                    cat_totals[cat] = cat_totals.get(cat, 0) + cnt

        if cat_totals:
            # Sortieren: 0er, 1er, 2er, 3er, ...
            sorted_cats = sorted(cat_totals.items(), key=lambda x: x[0])
            labels = [c[0] for c in sorted_cats]
            values = [c[1] for c in sorted_cats]

            # 3+ hervorheben
            highlight = [i for i, l in enumerate(labels) if any(
                l.startswith(f"{n}er") for n in range(3, 7)
            )]

            self._chart_distribution.plot_bar(
                labels, values,
                title=_("Treffer-Verteilung (alle Zyklen)"),
                xlabel=_("Kategorie"), ylabel=_("Anzahl"),
                highlight_indices=highlight,
            )

    def _plot_strategies(self, perf: list) -> None:
        """Strategie-Vergleich als Balken."""
        if not perf:
            self._chart_strategies.ax.clear()
            self._chart_strategies.ax.set_title(_("Keine Daten"))
            self._chart_strategies._safe_draw()
            return

        # Nach Strategie aggregieren
        agg: dict[str, dict] = {}
        for p in perf:
            s = p.get("strategy", "?")
            if s not in agg:
                agg[s] = {"avg_sum": 0, "count": 0, "wins": 0, "total": 0}
            agg[s]["avg_sum"] += p.get("avg_matches", 0)
            agg[s]["count"] += 1
            agg[s]["wins"] += p.get("win_count", 0)
            agg[s]["total"] += p.get("total_predictions", 0)

        names = []
        avg_matches = []
        for s, a in sorted(agg.items(), key=lambda x: -x[1]["avg_sum"] / max(x[1]["count"], 1)):
            names.append(s.capitalize())
            avg_matches.append(a["avg_sum"] / max(a["count"], 1))

        if names:
            self._chart_strategies.plot_bar(
                names, avg_matches,
                title=_("Durchschnittliche Treffer pro Strategie"),
                xlabel=_("Strategie"), ylabel=_("Avg. Treffer"),
                highlight_indices=[0],  # Beste hervorheben
            )

    def _plot_ml_progress(self, training: list) -> None:
        """ML-Training LSTM-Loss ueber Zeit."""
        if not training:
            self._chart_ml.ax.clear()
            self._chart_ml.ax.set_title(_("Keine Training-Daten"))
            self._chart_ml._safe_draw()
            return

        sorted_runs = sorted(training, key=lambda r: r.get("created_at", ""))
        dates = []
        losses = []
        for r in sorted_runs:
            loss = r.get("lstm_loss")
            if loss and loss > 0:
                dt = r.get("created_at", "?")
                if len(dt) >= 10:
                    dt = dt[:10]
                dates.append(dt)
                losses.append(loss)

        if dates:
            self._chart_ml.plot_line(
                dates, losses,
                title=_("LSTM Test-Loss ueber Training-Laeufe"),
                xlabel=_("Datum"), ylabel="Loss",
                color="#e66100",
            )
            self._chart_ml.ax.tick_params(axis="x", rotation=45, labelsize=7)
            self._chart_ml._safe_draw()

    def _update_summary(self, accuracy: dict, strategy: list) -> None:
        """Zusammenfassungs-Zeilen aktualisieren."""
        total = accuracy.get("total", 0)
        wins = accuracy.get("wins_3plus", 0)
        best = accuracy.get("best_match", 0)

        self._total_row.set_subtitle(f"{total:,}".replace(",", "."))
        self._best_row.set_subtitle(f"{best} {_('Richtige')}" if best else "—")

        if total > 0:
            rate = (wins / total) * 100
            self._winrate_row.set_subtitle(f"{rate:.2f}% ({wins} {_('von')} {total})")
        else:
            self._winrate_row.set_subtitle("—")

        if strategy:
            best_s = max(strategy, key=lambda p: p.get("avg_matches", 0))
            self._best_strategy_row.set_subtitle(
                f"{best_s.get('strategy', '?').capitalize()} "
                f"(Avg: {best_s.get('avg_matches', 0):.2f}, "
                f"Wins: {best_s.get('win_count', 0)})"
            )
        else:
            self._best_strategy_row.set_subtitle("—")
