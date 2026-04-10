"""Generator-Seite: Ml Section Mixin."""

import threading
from datetime import date, datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.generation import ALL_COMBOS, combo_key
from lotto_common.models.generation import combo_key
from lotto_common.models.game_config import get_config
from lotto_analyzer.ui.widgets.help_button import HelpButton

logger = get_logger("generator.ml_section")



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


class MlSectionMixin:
    """Mixin für GeneratorPage: Ml Section."""

    # ══════════════════════════════════════════════
    # Modell-Kombinationen Sektion
    # ══════════════════════════════════════════════

    def _build_combo_section(self) -> None:
        combo_group = Adw.PreferencesGroup(
            title=_("Modell-Kombinationen"),
            description=_("Alle 7 Modell-Combos bewerten und schwache ausschliessen"),
        )
        combo_group.set_header_suffix(
            HelpButton(_("Verschiedene ML-Modell-Kombinationen. Schwache Combos koennen deaktiviert werden."))
        )
        self._content.append(combo_group)

        # Combo-Tabelle (7 Zeilen)
        self._combo_rows: dict[str, dict] = {}

        for models in ALL_COMBOS:
            key = combo_key(models)
            label = "+".join(m.upper() for m in sorted(models))

            row = Adw.ActionRow(title=label)
            row.set_subtitle(_("Keine Daten"))

            switch = Gtk.Switch()
            switch.set_active(True)
            switch.set_valign(Gtk.Align.CENTER)
            switch.connect("state-set", self._on_combo_toggle, key)
            row.add_suffix(switch)
            row.set_activatable_widget(switch)

            combo_group.add(row)
            self._combo_rows[key] = {"row": row, "switch": switch}

        # Aktive Combo Label
        self._active_combo_label = Gtk.Label(label=_("Aktive Combo") + ": —")
        self._active_combo_label.add_css_class("heading")
        self._active_combo_label.set_margin_top(8)
        combo_group.add(self._active_combo_label)

        # Combo-Vorhersage generieren Button
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
        )
        btn_box.set_margin_top(8)

        self._combo_gen_btn = Gtk.Button(label=_("Combo-Vorhersagen generieren"))
        self._combo_gen_btn.set_tooltip_text(_("Generiert Vorhersagen mit allen Modell-Kombinationen"))
        self._combo_gen_btn.add_css_class("pill")
        self._combo_gen_btn.connect("clicked", self._on_generate_combos)
        self.register_readonly_button(self._combo_gen_btn)
        btn_box.append(self._combo_gen_btn)

        self._combo_spinner = Gtk.Spinner()
        self._combo_spinner.set_visible(False)
        btn_box.append(self._combo_spinner)

        combo_group.add(btn_box)

        self._combo_status_label = Gtk.Label(label="")
        self._combo_status_label.add_css_class("dim-label")
        self._combo_status_label.set_wrap(True)
        combo_group.add(self._combo_status_label)

        # Initial laden
        GLib.idle_add(self._refresh_combo_status)

    def _refresh_combo_status(self) -> bool:
        """Combo-Status aus DB laden und UI aktualisieren."""
        if self.app_mode == "client" and self.api_client:
            draw_day = self._get_draw_day()

            def worker():
                try:
                    data = self.api_client.combo_status(draw_day.value)
                    status = data.get("status", [])
                    active = data.get("active_models", [])
                    GLib.idle_add(self._update_combo_ui, status, active)
                except Exception as e:
                    logger.warning(f"Combo-Status API-Abfrage fehlgeschlagen: {e}")

            threading.Thread(target=worker, daemon=True).start()
            return False

        self._init_ml_components()
        if not self._combo_evaluator or not self.db:
            return False

        draw_day = self._get_draw_day()

        def worker():
            try:
                status = self._combo_evaluator.get_combo_status(draw_day)
                active = self._combo_evaluator.get_active_combo(draw_day)
                GLib.idle_add(self._update_combo_ui, status, active)
            except Exception as e:
                logger.warning(f"Combo-Status Abfrage fehlgeschlagen: {e}")

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _update_combo_ui(
        self, status: list[dict], active_models: list[str],
    ) -> bool:
        """Combo-UI mit aktuellen Daten befuellen."""
        status_map = {s["combo_key"]: s for s in status}

        for key, widgets in self._combo_rows.items():
            row = widgets["row"]
            switch = widgets["switch"]
            perf = status_map.get(key)

            if perf:
                avg = perf["avg_matches"]
                total = perf["total_predictions"]
                wins = perf["win_count"]
                active = bool(perf["is_active"])
                row.set_subtitle(
                    f"Ø {avg:.2f} Treffer  |  {total} Vorhersagen  |  {wins} Gewinne"
                )
                switch.set_active(active)
            else:
                row.set_subtitle("Keine Daten")
                switch.set_active(True)

        active_key = "+".join(m.upper() for m in sorted(active_models))
        self._active_combo_label.set_label(
            f"Aktive Combo: {active_key} (beste Performance)"
        )
        return False

    def _on_combo_toggle(
        self, switch: Gtk.Switch, state: bool, key: str,
    ) -> bool:
        """Manueller Combo-Toggle."""
        draw_day = self._get_draw_day()

        if self.app_mode == "client" and self.api_client:
            def worker():
                try:
                    self.api_client.toggle_combo(draw_day.value, key, state)
                    GLib.idle_add(self._refresh_combo_status)
                except Exception as e:
                    logger.warning(f"Combo-Toggle API fehlgeschlagen: {e}")
            threading.Thread(target=worker, daemon=True).start()
            return False

        if not self.db:
            return False

        def worker():
            try:
                self.db.set_combo_active(draw_day.value, key, state)
                GLib.idle_add(self._refresh_combo_status)
            except Exception as e:
                logger.warning(f"Combo-Toggle fehlgeschlagen: {e}")

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _on_generate_combos(self, btn: Gtk.Button) -> None:
        """Alle 7 Combo-Vorhersagen generieren."""
        btn.set_sensitive(False)
        self._combo_spinner.set_visible(True)
        self._combo_spinner.start()
        self._combo_status_label.set_label(_("Generiere 7 Combo-Vorhersagen..."))

        draw_day = self._get_draw_day()
        draw_date = self._current_draw_date
        if not draw_date:
            self._update_target_date()
            draw_date = self._current_draw_date
        if not draw_date:
            logger.warning("Kein Zieldatum verfügbar, ueberspringe Combo-Generierung")
            self._combo_status_label.set_label(_("Kein Zieldatum verfügbar"))
            btn.set_sensitive(True)
            self._combo_spinner.stop()
            self._combo_spinner.set_visible(False)
            return

        if self.app_mode == "client" and self.api_client:
            def worker():
                try:
                    data = self.api_client.generate_combos(draw_day.value, draw_date)
                    success = data.get("success", 0)
                    total = data.get("total", 0)
                    GLib.idle_add(self._on_combo_gen_done, success, total, None)
                except Exception as e:
                    GLib.idle_add(self._on_combo_gen_done, 0, 0, str(e))
            threading.Thread(target=worker, daemon=True).start()
            return

        self._init_ml_components()
        if not self._combo_evaluator:
            self._combo_status_label.set_label(_("ML-Engine nicht verfügbar"))
            btn.set_sensitive(True)
            self._combo_spinner.stop()
            self._combo_spinner.set_visible(False)
            return

        def worker():
            try:
                results = self._combo_evaluator.generate_all_combos(
                    draw_day, draw_date,
                )
                success = sum(1 for v in results.values() if v)
                GLib.idle_add(
                    self._on_combo_gen_done, success, len(results), None,
                )
            except Exception as e:
                GLib.idle_add(self._on_combo_gen_done, 0, 0, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_combo_gen_done(
        self, success: int, total: int, error: str | None,
    ) -> bool:
        self._combo_gen_btn.set_sensitive(not self._is_readonly)
        self._combo_spinner.stop()
        self._combo_spinner.set_visible(False)

        if error:
            self._combo_status_label.set_label(_("Fehler") + f": {error}")
        else:
            self._combo_status_label.set_label(
                f"{success}/{total} Combo-Vorhersagen generiert"
            )
            self._refresh_combo_status()
        return False

    # ══════════════════════════════════════════════
    # ML-Feedback &amp; Tuning Sektion
    # ══════════════════════════════════════════════

    def _build_ml_feedback_section(self) -> None:
        tuning_group = Adw.PreferencesGroup(
            title=_("ML-Feedback &amp; Tuning"),
            description=_("LSTM-Parameter anpassen und Custom-Training starten"),
        )
        tuning_group.set_header_suffix(
            HelpButton(_("Automatische Suche nach optimalen ML-Trainingsparametern (Lernrate, Epochen, etc.)."))
        )
        self._content.append(tuning_group)

        # LSTM Epochen
        self._lstm_epochs_spin = Adw.SpinRow.new_with_range(10, 200, 10)
        self._lstm_epochs_spin.set_title("LSTM Epochen")
        self._lstm_epochs_spin.set_value(50)
        tuning_group.add(self._lstm_epochs_spin)

        # Lernrate (x0.001)
        self._lstm_lr_spin = Adw.SpinRow.new_with_range(1, 100, 1)
        self._lstm_lr_spin.set_title("Lernrate (x0.001)")
        self._lstm_lr_spin.set_value(1)
        tuning_group.add(self._lstm_lr_spin)

        # Custom-Training Button
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
        )
        btn_box.set_margin_top(8)

        self._custom_train_btn = Gtk.Button(label=_("Mit diesen Parametern trainieren"))
        self._custom_train_btn.set_tooltip_text(_("Startet Training mit den eingestellten Hyperparametern"))
        self._custom_train_btn.add_css_class("suggested-action")
        self._custom_train_btn.add_css_class("pill")
        self._custom_train_btn.connect("clicked", self._on_custom_train)
        self.register_readonly_button(self._custom_train_btn)
        btn_box.append(self._custom_train_btn)

        self._custom_train_spinner = Gtk.Spinner()
        self._custom_train_spinner.set_visible(False)
        btn_box.append(self._custom_train_spinner)

        tuning_group.add(btn_box)

        # Custom-Training Status
        self._custom_train_status = Gtk.Label(label="")
        self._custom_train_status.add_css_class("dim-label")
        self._custom_train_status.set_wrap(True)
        tuning_group.add(self._custom_train_status)

    def _on_custom_train(self, btn: Gtk.Button) -> None:
        """Custom-Training mit benutzerdefinierten Parametern."""
        self._init_ml_components()
        if not self._model_trainer:
            self._custom_train_status.set_label(_("ML-Engine nicht verfügbar"))
            return

        epochs = int(self._lstm_epochs_spin.get_value())
        lr = self._lstm_lr_spin.get_value() * 0.001

        btn.set_sensitive(False)
        self._custom_train_spinner.set_visible(True)
        self._custom_train_spinner.start()
        self._custom_train_status.set_label(
            f"Training mit {epochs} Epochen, LR={lr:.4f}..."
        )

        if self.app_mode == "client":
            def worker():
                try:
                    client = self.api_client
                    if not client:
                        from lotto_analyzer.client.api_client import APIClient
                        config = self.config_manager.config.server
                        client = APIClient(config)
                    result = client.train_ml_custom(epochs=epochs, lr=lr)
                    GLib.idle_add(self._on_custom_train_done, result, None)
                except Exception as e:
                    GLib.idle_add(self._on_custom_train_done, {}, str(e))
            threading.Thread(target=worker, daemon=True).start()
        else:
            def worker():
                try:
                    result = self._model_trainer.train_all(
                        lstm_epochs=epochs, lstm_lr=lr,
                    )
                    GLib.idle_add(self._on_custom_train_done, result, None)
                except Exception as e:
                    GLib.idle_add(self._on_custom_train_done, {}, str(e))
            threading.Thread(target=worker, daemon=True).start()

    def _on_custom_train_done(self, result: dict, error: str | None) -> bool:
        self._custom_train_btn.set_sensitive(True)
        self._custom_train_spinner.stop()
        self._custom_train_spinner.set_visible(False)

        if error:
            self._custom_train_status.set_label(_("Fehler") + f": {error}")
        else:
            self._custom_train_status.set_label(_("Custom-Training abgeschlossen!"))
            self._refresh_ml_status()
        return False

