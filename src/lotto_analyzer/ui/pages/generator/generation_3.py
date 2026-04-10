"""Generator-Seite: Generation Mixin."""

import csv
import io
import sqlite3
from pathlib import Path
import threading
from datetime import date, datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib, Gio

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_analyzer.ui.widgets.help_button import HelpButton
from lotto_common.models.analysis import PredictionRecord

logger = get_logger("generator.generation")



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




class GenerationMixin3:
    """Teil 3 von GenerationMixin."""

    def _start_day_training(self, draw_day: DrawDay, btn: Gtk.Button) -> None:
        """Training für einen Ziehungstag starten — via Server."""
        btn.set_sensitive(False)
        self._ml_train_spinner.set_visible(True)
        self._ml_train_spinner.start()
        day_name = self._DAY_LABELS.get(draw_day.value, draw_day.value)
        self._ml_train_status.set_label(f"{day_name}-{_('Modelle werden trainiert (1-2 Min)...')}")

        # LSTM-Parameter aus Tuning-Sektion holen (falls vorhanden)
        epochs = int(self._lstm_epochs_spin.get_value()) if hasattr(self, '_lstm_epochs_spin') else 50
        lr = self._lstm_lr_spin.get_value() * 0.001 if hasattr(self, '_lstm_lr_spin') else 0.001

        if not self.api_client:
            from lotto_analyzer.ui.helpers import show_error_toast
            show_error_toast(self, _("Serververbindung erforderlich"))
            btn.set_sensitive(True)
            self._ml_train_spinner.stop()
            self._ml_train_spinner.set_visible(False)
            return

        self._train_via_server(draw_day, btn, epochs, lr)

    def set_api_client(self, client: "APIClient | None") -> None:
        """API-Client setzen."""
        super().set_api_client(client)
        self._ai_panel.api_client = client

    def refresh(self) -> None:
        """Generator-Daten nur neu laden wenn veraltet (>5min)."""
        if not self.is_stale() or not self.api_client:
            return
        self._load_latest_predictions()
        self._load_adaptive_weights()
        self._load_server_ui_settings()

    def _load_server_ui_settings(self) -> None:
        """Generator-UI-Settings vom Server laden und UI fuellen."""
        def worker():
            try:
                data = self.api_client.get_generator_ui_settings()
                GLib.idle_add(self._apply_server_ui_settings, data)
            except Exception as e:
                logger.warning(f"Generator-UI-Settings nicht geladen: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _apply_server_ui_settings(self, data: dict) -> bool:
        """Server-Settings in die UI uebernehmen (Main-Thread)."""
        self._restoring_config = True
        try:
            if "tip_count" in data:
                self._count_spin.set_value(data["tip_count"])
            if "selected_strategies" in data:
                saved = data["selected_strategies"]
                for key, cb in self._strategy_checks.items():
                    cb.set_active(key in saved)
        finally:
            self._restoring_config = False
        return False

    def _train_via_server(
        self, draw_day: DrawDay, btn: Gtk.Button,
        epochs: int = 50, lr: float = 0.001,
    ) -> None:
        """Training via API-Client an Server delegieren (as server task)."""
        self._training_btn = btn
        self._training_draw_day = draw_day

        def worker():
            try:
                result = self.api_client.train_ml_custom(
                    epochs=epochs, lr=lr, draw_day=draw_day.value,
                )
                task_id = result.get("task_id", "")
                if task_id:
                    GLib.idle_add(self._poll_training_task, task_id)
                else:
                    GLib.idle_add(self._on_training_done, result, btn, None)
            except Exception as e:
                GLib.idle_add(self._on_training_done, {}, btn, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_training_task(self, task_id: str) -> bool:
        """Poll server task status for ML training progress."""
        day_name = self._DAY_LABELS.get(
            self._training_draw_day.value, self._training_draw_day.value,
        )

        def check():
            try:
                task = self.api_client.get_task(task_id)
                if not task:
                    return
                status = task.get("status", "")
                progress = task.get("progress", 0)
                pct = int(progress * 100)
                GLib.idle_add(
                    self._ml_train_status.set_label,
                    f"{day_name}: {_('Training')} {pct}%",
                )
                if status in ("completed", "failed", "cancelled"):
                    error = task.get("error") if status == "failed" else None
                    GLib.idle_add(
                        self._on_training_done,
                        task, self._training_btn, error,
                    )
                    return
                # Continue polling
                GLib.timeout_add_seconds(3, lambda: (
                    threading.Thread(target=check, daemon=True).start()
                    or False
                ))
            except Exception as e:
                GLib.idle_add(
                    self._on_training_done, {}, self._training_btn, str(e),
                )

        threading.Thread(target=check, daemon=True).start()
        return False

    def _on_training_done(
        self, result: dict, btn: Gtk.Button, error: str | None,
    ) -> bool:
        btn.set_sensitive(True)
        self._ml_train_spinner.stop()
        self._ml_train_spinner.set_visible(False)

        if error:
            self._ml_train_status.set_label(_("Training fehlgeschlagen") + f": {error}")
        else:
            self._ml_train_status.set_label(_("Training abgeschlossen!"))
            self._refresh_ml_status()

        return False

    def _on_ai_ml_advice(self, btn: Gtk.Button) -> None:
        """AI ML-Beratung starten — via Server."""
        if not self.api_client:
            from lotto_analyzer.ui.helpers import show_error_toast
            show_error_toast(self, _("Serververbindung erforderlich"))
            return

        btn.set_sensitive(False)
        self._ai_ml_result.set_label(_("AI analysiert ML-Performance (via Server)..."))
        self._ai_ml_result.set_visible(True)

        def worker():
            try:
                status = self.api_client.ml_status()
                # AI-Analyse via Chat-Endpoint
                status_text = "\n".join(
                    f"  {k}: acc={v.get('accuracy', 0)}, trained={v.get('last_trained', 'nie')}"
                    for k, v in status.items() if isinstance(v, dict)
                )
                prompt = (
                    f"Analysiere die ML-Modell-Performance:\n{status_text}\n\n"
                    "Welches Modell performt am besten? Verbesserungsvorschlaege?"
                )
                response = self.api_client.chat(prompt)
                GLib.idle_add(self._on_ai_ml_done, response, None)
            except Exception as e:
                GLib.idle_add(self._on_ai_ml_done, "", str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ai_ml_done(self, response: str, error: str | None) -> bool:
        self._ai_ml_btn.set_sensitive(True)
        if error:
            self._ai_ml_result.set_label(_("AI-Analyse fehlgeschlagen") + f": {error}")
        elif response:
            self._ai_ml_result.set_label(response)
        else:
            self._ai_ml_result.set_label(_("Keine Antwort von AI erhalten."))
        self._ai_ml_result.set_visible(True)
        return False

    # ══════════════════════════════════════════════
    # Generator initialisieren
    # ══════════════════════════════════════════════

    def _init_generator(self):
        """Generator — läuft nur auf dem Server. UI nutzt API."""
        # Kein lokaler Generator mehr. Generierung geht via API.
        return None

    # ══════════════════════════════════════════════
    # Generierung
    # ══════════════════════════════════════════════

    def _on_generate(self, button: Gtk.Button) -> None:
        if self._is_readonly:
            return
        with self._op_lock:
            if self._generating:
                return
            self._generating = True

        if self.app_mode != "client" and not self.db:
            with self._op_lock:
                self._generating = False
            return

        # Backtest-Modus: andere Generierungs-Pipeline
        if self._gen_mode == "backtest":
            self._on_generate_backtest()
            return

        # Beide-Modus: Statistik zuerst, dann Backtest
        if self._gen_mode == "beide":
            self._on_generate_beide()
            return

        selected_strategies = self._get_selected_strategies()
        if not selected_strategies:
            self._status_label.set_label(_("Fehler: Mindestens eine Strategie wählen!"))
            with self._op_lock:
                self._generating = False
            return
        self._gen_btn.set_sensitive(False)
        self._spinner.set_visible(True)
        self._spinner.start()

        draw_day = self._get_draw_day()
        count = int(self._count_spin.get_value())

        # Ab 200K: Mass-Generation (PostgreSQL + Multicore, separate Prozesse)
        if count >= self.MASS_GEN_THRESHOLD and self.app_mode == "client" and self.api_client:
            self._start_mass_generate(draw_day, count, selected_strategies)
            return

        self._status_label.set_label(_("Generiere..."))
        multi_strategy = len(selected_strategies) > 1

        # Custom-Gewichte aus Slider (Phase 2)
        custom_weights = self._get_custom_weights() if hasattr(self, '_weight_sliders') else None

        if self.app_mode == "client" and self.api_client:
            def worker():
                try:
                    if multi_strategy:
                        strategy_name = ",".join(s.value for s in selected_strategies)
                    else:
                        strategy_name = selected_strategies[0].value
                    data = self.api_client.generate_batch(
                        strategy=strategy_name,
                        draw_day=draw_day.value,
                        count=count,
                        custom_weights=custom_weights,
                    )
                    task_id = data.get("task_id")
                    if task_id:
                        GLib.idle_add(self._start_generate_poll, task_id, draw_day)
                        return
                    # Fallback: alte synchrone Antwort
                    api_results = data.get("results", [])
                    results = []
                    strategies = []
                    for r in api_results:
                        gr = GenerationResult(
                            numbers=r["numbers"],
                            super_number=r.get("super_number", 0),
                            strategy=r.get("strategy", ""),
                            reasoning=r.get("reasoning", ""),
                            confidence=r.get("confidence", 0.0),
                        )
                        results.append(gr)
                        strategies.append(r.get("strategy", ""))
                    GLib.idle_add(self._on_generate_done, results, None, strategies)
                except (ConnectionError, TimeoutError, OSError) as e:
                    logger.error(f"Generierung via Server fehlgeschlagen: {e}")
                    GLib.idle_add(self._on_generate_done, [], str(e))
                except Exception as e:
                    logger.exception(f"Unerwarteter Fehler bei Server-Generierung: {e}")
                    GLib.idle_add(self._on_generate_done, [], str(e))
            threading.Thread(target=worker, daemon=True).start()
            return

        def worker():
            try:
                generator = self._init_generator()
                if not generator:
                    GLib.idle_add(self._on_generate_done, [], "Keine Datenbank verfügbar")
                    return

                # Auto-Training: ML/Ensemble braucht trainierte Modelle
                ml_strategies = {Strategy.ML, Strategy.ENSEMBLE}
                needs_ml = bool(ml_strategies & set(selected_strategies))
                if needs_ml and generator.needs_ml_training(draw_day):
                    GLib.idle_add(
                        self._status_label.set_label,
                        "ML-Modelle werden trainiert (1-2 Min)...",
                    )
                    self._init_ml_components()
                    if self._model_trainer:
                        self._model_trainer.train_day(draw_day)
                        GLib.idle_add(self._refresh_ml_status)

                # Custom-Gewichte ans Generator-Objekt
                if custom_weights:
                    generator._adaptive_weights = custom_weights

                results: list[GenerationResult] = []
                strategies: list[str] = []

                if multi_strategy:
                    multi = generator.generate_multi_strategy(
                        draw_day,
                        count_per_strategy=count,
                        strategies=selected_strategies,
                    )
                    for strat_name, strat_results in multi.items():
                        for r in strat_results:
                            results.append(r)
                            strategies.append(strat_name)
                else:
                    strategy = selected_strategies[0]
                    batch = generator.generate_batch(strategy, draw_day, count)
                    for r in batch:
                        results.append(r)
                        strategies.append(r.strategy)

                # In DB speichern
                draw_date = self._current_draw_date
                if not draw_date:
                    GLib.idle_add(self._update_target_date)
                    draw_date = self._current_draw_date
                if not draw_date:
                    logger.warning("Kein Zieldatum verfügbar, ueberspringe DB-Insert")
                    GLib.idle_add(self._on_generate_done, results, None, strategies)
                    return
                for i, result in enumerate(results):
                    pred = PredictionRecord(
                        draw_date=draw_date,
                        draw_day=draw_day.value,
                        strategy=result.strategy,
                        predicted_numbers=sorted(result.numbers),
                        ml_confidence=result.confidence,
                        ai_reasoning=result.reasoning,
                        position=i + 1,
                    )
                    self.db.insert_prediction(pred)

                # Combo-Vorhersagen mitgenerieren bei ML/Ensemble
                if needs_ml and self._combo_evaluator:
                    try:
                        self._combo_evaluator.generate_all_combos(
                            draw_day, draw_date,
                        )
                        GLib.idle_add(self._refresh_combo_status)
                    except Exception as e:
                        logger.warning(f"Combo-Generierung: {e}")

                GLib.idle_add(self._on_generate_done, results, None, strategies)
            except (sqlite3.Error, OSError) as e:
                logger.error(f"Generierung fehlgeschlagen: {e}")
                GLib.idle_add(self._on_generate_done, [], str(e))
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler bei Generierung: {e}")
                GLib.idle_add(self._on_generate_done, [], str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_generate_done(
        self, results: list[GenerationResult],
        error: str | None, strategies: list[str] | None = None,
    ) -> bool:
        # WS-Listener entfernen (Generierung ist fertig)
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("task_update", self._on_ws_generate_task)
        except Exception:
            pass
        with self._op_lock:
            self._generating = False
        self._gen_btn.set_sensitive(not self._is_readonly)
        self._spinner.stop()
        self._spinner.set_visible(False)

        if error:
            self._status_label.set_label(_("Fehler") + f": {error}")
            return False

        self._results = results
        self._result_strategies = strategies or [r.strategy for r in results]
        self._ai_top_picks: set[int] = set()
        self._compare_btn.set_sensitive(bool(results))
        self._populate_results()
        self._load_prediction_dates()

        # AI-Analyse im Hintergrund starten
        if results and len(results) >= 3:
            self._start_ai_analysis(results)

        return False

    # ══════════════════════════════════════════════
    # Task-Polling für Server-Generierung
    # ══════════════════════════════════════════════

    def _start_generate_poll(self, task_id: str, draw_day: DrawDay) -> bool:
        """Polling für laufenden Generate-Task starten."""
        self._status_label.set_label(
            _("Generierung läuft auf dem Server. Fenster kann geschlossen werden.")
        )
        with self._op_lock:
            self._generating = True
        self._gen_btn.set_sensitive(False)

        self._generate_task_id = task_id

        # WS-Listener fuer instant Updates (Polling bleibt als Fallback)
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.on("task_update", self._on_ws_generate_task)
        except Exception:
            pass

        import time
        import json

        def poller():
            start = time.monotonic()
            try:
                while not self._cancel_event.is_set():
                    self._cancel_event.wait(3)
                    if self._cancel_event.is_set():
                        return
                    if time.monotonic() - start > self.POLL_TIMEOUT_SECONDS:
                        GLib.idle_add(self._on_generate_done, [], "Timeout nach 30 Minuten")
                        return
                    try:
                        task = self.api_client.get_task(task_id)
                    except Exception as e:
                        logger.warning(f"Task-Polling fehlgeschlagen: {e}")
                        continue  # Netzwerk-Fehler: nächster Versuch
                    status = task.get("status", "?")

                    if status == "completed":
                        result_raw = task.get("result")
                        result = json.loads(result_raw) if isinstance(result_raw, str) else (result_raw or {})
                        api_results = result.get("results", [])
                        results = []
                        strategies = []
                        for r in api_results:
                            gr = GenerationResult(
                                numbers=r["numbers"],
                                super_number=r.get("super_number", 0),
                                strategy=r.get("strategy", ""),
                                reasoning=r.get("reasoning", ""),
                                confidence=r.get("confidence", 0.0),
                            )
                            results.append(gr)
                            strategies.append(r.get("strategy", ""))
                        GLib.idle_add(self._on_generate_done, results, None, strategies)
                        return
                    elif status in ("failed", "cancelled"):
                        error = task.get("error", "Unbekannter Fehler")
                        GLib.idle_add(self._on_generate_done, [], error)
                        return
                    else:
                        progress = task.get("progress", 0)
                        pct = int(progress * 100)
                        GLib.idle_add(
                            self._status_label.set_label,
                            f"Generierung läuft... ({pct}%) — Fenster kann geschlossen werden.",
                        )
            except Exception as e:
                GLib.idle_add(self._on_generate_done, [], str(e))

        self._cancel_event.clear()
        threading.Thread(target=poller, daemon=True).start()
        return False

    def _on_ws_generate_task(self, data: dict) -> bool:
        """Handle WS task_update — trigger instant generation progress refresh."""
        task_id = data.get("id", "")
        if hasattr(self, "_generate_task_id") and task_id == self._generate_task_id:
            import json
            status = data.get("status", "")
            progress = data.get("progress", 0)
            pct = int(progress * 100)
            if status == "completed":
                result_raw = data.get("result")
                try:
                    result = json.loads(result_raw) if isinstance(result_raw, str) else (result_raw or {})
                except Exception:
                    result = {}
                api_results = result.get("results", [])
                results = []
                strategies = []
                for r in api_results:
                    gr = GenerationResult(
                        numbers=r["numbers"],
                        super_number=r.get("super_number", 0),
                        strategy=r.get("strategy", ""),
                        reasoning=r.get("reasoning", ""),
                        confidence=r.get("confidence", 0.0),
                    )
                    results.append(gr)
                    strategies.append(r.get("strategy", ""))
                self._on_generate_done(results, None, strategies)
            elif status in ("failed", "cancelled"):
                error = data.get("error", "Unbekannter Fehler")
                self._on_generate_done([], error)
            else:
                self._status_label.set_label(
                    f"Generierung läuft... ({pct}%) — Fenster kann geschlossen werden.",
                )
        return False

    def _restore_state(self) -> None:
        """Beim Seitenaufruf: laufende Tasks fortsetzen oder letzte Predictions laden."""
        def worker():
            try:
                # 1. Laufende Tasks → Polling fortsetzen (nur Client-Modus)
                if self.app_mode == "client" and self.api_client:
                    try:
                        tasks = self.api_client.get_tasks(status="running")
                        for task in tasks:
                            if task.get("operation") == "generate_batch":
                                task_id = task.get("id")
                                draw_day_val = task.get("draw_day", "saturday")
                                try:
                                    dd = DrawDay(draw_day_val)
                                except ValueError:
                                    dd = DrawDay.SATURDAY
                                GLib.idle_add(self._start_generate_poll, task_id, dd)
                                return
                    except Exception as e:
                        logger.debug(f"Running-Tasks Abfrage fehlgeschlagen: {e}")

                # 2. Kein laufender Task → letzte Predictions laden
                GLib.idle_add(self._load_latest_predictions)
            except Exception as e:
                logger.debug(f"State-Restore fehlgeschlagen: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _load_latest_predictions(self, draw_day: DrawDay | None = None) -> bool:
        """Letzte Predictions für aktuellen Spieltag aus DB laden und anzeigen."""
        self._load_generation += 1
        current_gen = self._load_generation

        if draw_day is None:
            draw_day = self._get_draw_day()
        draw_date = self._current_draw_date

        if not draw_date:
            self._update_target_date()
            draw_date = self._current_draw_date

        def worker():
            try:
                predictions: list[dict] = []

                if self.app_mode == "client" and self.api_client:
                    resp = self.api_client.get_predictions(
                        draw_day=draw_day.value,
                        draw_date=draw_date,
                        limit=200,
                    )
                    predictions = resp.get("predictions", [])
                elif self.db:
                    predictions = self.db.get_predictions_paginated(
                        draw_day=draw_day.value,
                        draw_date=draw_date,
                        limit=200,
                    )

                if not predictions:
                    GLib.idle_add(self._on_predictions_restored, [], [], current_gen)
                    return

                results: list[GenerationResult] = []
                strategies: list[str] = []
                for p in predictions:
                    nums_raw = p.get("predicted_numbers", "")
                    if isinstance(nums_raw, str):
                        numbers = [int(n) for n in nums_raw.split(",") if n.strip()]
                    else:
                        numbers = list(nums_raw)
                    strategy = p.get("strategy", "")
                    confidence = p.get("ml_confidence", 0.0)
                    reasoning = p.get("ai_reasoning", "")
                    gr = GenerationResult(
                        numbers=numbers,
                        super_number=p.get("super_number", 0),
                        strategy=strategy,
                        reasoning=reasoning,
                        confidence=confidence,
                    )
                    results.append(gr)
                    strategies.append(strategy)

                GLib.idle_add(self._on_predictions_restored, results, strategies, current_gen)
            except Exception as e:
                logger.debug(f"Predictions laden fehlgeschlagen: {e}")

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _on_predictions_restored(
        self, results: list[GenerationResult], strategies: list[str],
        generation: int = 0,
    ) -> bool:
        """Geladene Predictions anzeigen (ohne AI-Analyse neu zu starten)."""
        # Veraltete Antwort verwerfen (Spieltyp wurde zwischenzeitlich gewechselt)
        if generation and generation != self._load_generation:
            return False
        self._results = results
        self._result_strategies = strategies
        self._ai_top_picks = set()
        self._compare_btn.set_sensitive(bool(results))
        self._populate_results()
        return False

    # ══════════════════════════════════════════════
    # CSV-Export
    # ══════════════════════════════════════════════

    _CSV_DIR = Path.home() / "lotto" / ".lotto"

    def _on_export_csv(self, btn) -> None:
        if not self._results:
            return

        from gi.repository import Gio

        self._CSV_DIR.mkdir(parents=True, exist_ok=True)

        dialog = Gtk.FileDialog()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dialog.set_initial_name(f"lotto_tipps_{self._current_draw_date}_{timestamp}.csv")
        dialog.set_initial_folder(Gio.File.new_for_path(str(self._CSV_DIR)))

        csv_filter = Gtk.FileFilter()
        csv_filter.set_name(_("CSV-Dateien"))
        csv_filter.add_pattern("*.csv")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(csv_filter)
        dialog.set_filters(filters)

        root = self.get_root()
        if root:
            dialog.save(root, None, self._on_export_done)

    def _on_export_done(self, dialog, result) -> None:
        try:
            file = dialog.save_finish(result)
            if not file:
                return

            path = file.get_path()
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                # Header dynamisch: Z1..Zn + Bonus-Name
                num_headers = [f"Z{i+1}" for i in range(self._config.main_count)]
                writer.writerow([
                    "Nr", "Strategie", *num_headers,
                    self._config.bonus_name, "Konfidenz", "Ziel-Datum",
                ])
                for i, result in enumerate(self._results):
                    nums = sorted(result.numbers)
                    strategy = self._result_strategies[i] if i < len(self._result_strategies) else result.strategy
                    # Bonus: EJ → Eurozahlen, 6aus49 → Superzahl
                    if result.bonus_numbers:
                        bonus_val = ",".join(str(n) for n in sorted(result.bonus_numbers))
                    else:
                        bonus_val = str(result.super_number)
                    writer.writerow([
                        i + 1, strategy,
                        *nums,
                        bonus_val,
                        f"{result.confidence:.2f}",
                        self._current_draw_date,
                    ])

            self._status_label.set_label(_("Exportiert") + f": {path}")
            logger.info(f"CSV exportiert: {path}")

        except Exception as e:
            self._status_label.set_label(_("Export fehlgeschlagen") + f": {e}")
            logger.error(f"CSV-Export: {e}")


# TODO: Diese Datei ist >500Z weil: Batch-Generierung UI mit Progress + Multiple Strategies
