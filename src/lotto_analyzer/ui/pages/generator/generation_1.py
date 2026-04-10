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



DAY_LABELS = {
    "saturday": "Samstag",
    "wednesday": "Mittwoch",
    "tuesday": "Dienstag",
    "friday": "Freitag",
}


class GenerationMixin1:
    """Teil 1 von GenerationMixin."""

    def set_game_type(self, game_type: GameType) -> None:
        """Spieltyp wechseln — UI-Elemente anpassen."""
        self._game_type = game_type
        self._config = get_config(game_type)

        # Tag-Combo neu aufbauen
        self._rebuild_day_combo()

        # Vergleichs-Sektion: Manuelle Eingabe anpassen
        self._rebuild_comparison_inputs()

        # Ergebnistabelle zurücksetzen
        self._results = []
        self._result_strategies = []
        self._populate_results()

        # ML-Modelle Sektion für neuen Spieltyp neu aufbauen
        self._rebuild_ml_section()

        # Generator zurücksetzen (wird lazy neu initialisiert)
        self._generator = None

        self._update_target_date()

        # Predictions für neuen Spieltyp laden
        self._load_latest_predictions()

    def _rebuild_day_combo(self) -> None:
        """Tag-Combo für den aktuellen Spieltyp neu aufbauen."""
        day_model = Gtk.StringList()
        for day in self._config.draw_days:
            day_model.append(self._DAY_LABELS.get(day, day))
        self._day_combo.set_model(day_model)
        self._day_combo.set_selected(0)
        self._update_day_toggle_label()

    def _rebuild_ml_section(self) -> None:
        """ML-Modelle Sektion entfernen und für den aktuellen Spieltyp neu aufbauen."""
        if not hasattr(self, '_ml_group') or self._ml_group is None:
            return

        # Vorgaenger-Widget merken (für Positionierung)
        prev_sibling = self._ml_group.get_prev_sibling()

        # Altes Widget entfernen
        self._content.remove(self._ml_group)

        # Neues Widget erstellen (wird am Ende angehaengt)
        self._build_ml_models_section()

        # An die richtige Position verschieben (nach prev_sibling)
        new_group = self._ml_group
        self._content.reorder_child_after(new_group, prev_sibling)

        self._refresh_ml_status()

    def _rebuild_comparison_inputs(self) -> None:
        """Manuelle Vergleichs-Eingabe für den aktuellen Spieltyp anpassen."""
        # Hauptzahlen-Spins anpassen
        for spin in self._manual_spins:
            adj = spin.get_adjustment()
            adj.set_lower(self._config.main_min)
            adj.set_upper(self._config.main_max)
            adj.set_value(self._config.main_min)

        # Anzahl der Hauptzahlen-Spins anpassen
        current_count = len(self._manual_spins)
        needed = self._config.main_count

        if hasattr(self, '_manual_nums_box'):
            if current_count > needed:
                for spin in self._manual_spins[needed:]:
                    self._manual_nums_box.remove(spin)
                self._manual_spins = self._manual_spins[:needed]
            elif current_count < needed:
                for _ in range(needed - current_count):
                    adj = Gtk.Adjustment(
                        value=self._config.main_min,
                        lower=self._config.main_min,
                        upper=self._config.main_max,
                        step_increment=1,
                    )
                    spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
                    spin.set_width_chars(3)
                    self._manual_spins.append(spin)
                    self._manual_nums_box.append(spin)

        # Bonus-Feld anpassen
        if hasattr(self, '_sz_spin'):
            adj_sz = self._sz_spin.get_adjustment()
            adj_sz.set_lower(self._config.bonus_min)
            adj_sz.set_upper(self._config.bonus_max)
            adj_sz.set_value(self._config.bonus_min)

        # Labels aktualisieren
        if hasattr(self, '_manual_numbers_row'):
            self._manual_numbers_row.set_title(
                f"Gewinnzahlen ({self._config.main_min}-{self._config.main_max})"
            )
        if hasattr(self, '_sz_row'):
            self._sz_row.set_title(
                f"{self._config.bonus_name} "
                f"({self._config.bonus_min}-{self._config.bonus_max})"
            )

    # ══════════════════════════════════════════════
    # Generierung
    # ══════════════════════════════════════════════

    def _build_generation_section(self) -> None:
        gen_group = Adw.PreferencesGroup(title=_("Generierung"))
        self._content.append(gen_group)

        # ── Modus-Auswahl: Statistik / Backtest / Beide ──
        self._gen_mode = "statistik"  # "statistik", "backtest" oder "beide"
        _MODE_OPTIONS = [_("Statistik-basiert"), _("Backtest-basiert"), _("Beide (Statistik + Backtest)")]
        self._mode_combo = Adw.ComboRow(title=_("Generierungs-Modus"))
        mode_model = Gtk.StringList()
        for opt in _MODE_OPTIONS:
            mode_model.append(opt)
        self._mode_combo.set_model(mode_model)
        self._mode_combo.set_selected(0)
        self._mode_combo.add_prefix(Gtk.Image.new_from_icon_name("view-dual-symbolic"))
        self._mode_combo.add_suffix(
            HelpButton(_(
                "Statistik: Generiert mit Hot/Cold/ML/AI/Ensemble auf Basis der Gesamtstatistik.\n"
                "Backtest: Walk-Forward Backtest, trainiert ML auf historischen Fenstern.\n"
                "Beide: Führt beide Methoden aus und speichert alle Predictions — "
                "ideal zum Vergleichen welche Methode besser trifft."
            ))
        )
        self._mode_combo.connect("notify::selected", self._on_mode_changed)
        gen_group.add(self._mode_combo)

        # Backtest-Fenster (nur im Backtest-Modus sichtbar)
        self._bt_window_spin = Adw.SpinRow.new_with_range(3, 36, 3)
        self._bt_window_spin.set_title(_("Backtest-Fenster (Monate)"))
        self._bt_window_spin.set_value(12)
        self._bt_window_spin.set_visible(False)
        self._bt_window_spin.add_suffix(
            HelpButton(_("Größe des Trainings-Fensters in Monaten. Kleiner = reaktiver, größer = stabiler."))
        )
        gen_group.add(self._bt_window_spin)

        self._bt_tips_spin = Adw.SpinRow.new_with_range(1, 20, 1)
        self._bt_tips_spin.set_title(_("Tipps pro Strategie"))
        self._bt_tips_spin.set_value(3)
        self._bt_tips_spin.set_visible(False)
        self._bt_tips_spin.add_suffix(
            HelpButton(_("Wie viele Tipp-Reihen pro Backtest-Strategie generiert werden."))
        )
        gen_group.add(self._bt_tips_spin)

        # Anzahl Tipps (bis 10 Mio — ab 200K läuft Mass-Gen via PostgreSQL)
        self._count_spin = Adw.SpinRow.new_with_range(1, 10_000_000, 1)
        self._count_spin.set_title(_("Anzahl Tipps"))
        self._count_spin.set_value(self.config_manager.config.generator.tip_count)
        self._count_spin.add_suffix(
            HelpButton(_(
                "Anzahl Tipp-Reihen pro Strategie (1 bis 10.000.000).\n"
                "Ab 200.000 wird automatisch Mass-Generation genutzt "
                "(PostgreSQL + Multicore, separate Prozesse)."
            ))
        )
        self._count_spin.connect("notify::value", self._on_tip_count_changed)
        gen_group.add(self._count_spin)

        # Hinweis-Label für Mass-Gen (ab 200K sichtbar)
        self._mass_gen_hint = Gtk.Label(
            label=_("Ab 200K: Mass-Generation (PostgreSQL, Multicore) — Hauptprogramm wird nicht belastet."),
        )
        self._mass_gen_hint.add_css_class("dim-label")
        self._mass_gen_hint.set_wrap(True)
        self._mass_gen_hint.set_visible(False)
        gen_group.add(self._mass_gen_hint)

        # Ziehungstag
        self._day_combo = Adw.ComboRow(title=_("Für Ziehungstag"))
        day_model = Gtk.StringList()
        for d in self._config.draw_days:
            day_model.append(self._DAY_LABELS.get(d, d))
        self._day_combo.set_model(day_model)
        self._day_combo.add_suffix(
            HelpButton(_("Für welchen Ziehungstag sollen Tipps generiert werden (Sa=Lotto, Di/Fr=EuroJackpot)."))
        )
        self._day_combo.connect("notify::selected", self._on_day_changed)
        gen_group.add(self._day_combo)

        # Ziel-Datum (auto-berechnet)
        self._date_row = Adw.ActionRow(title=_("Ziel-Datum"))
        self._date_row.add_prefix(
            Gtk.Image.new_from_icon_name("x-office-calendar-symbolic")
        )
        self._update_target_date()
        gen_group.add(self._date_row)

        # ── Strategie-Checkboxen ──
        strat_group = Adw.PreferencesGroup(title=_("Strategien"))
        strat_group.set_description(_("Mehrere Strategien gleichzeitig wählbar"))
        strat_group.set_header_suffix(
            HelpButton(_("Wähle eine oder mehrere Strategien. 'Alle' aktiviert alle. "
                        "'AI waehlt' laesst die AI die optimalen Strategien empfehlen."))
        )
        self._content.append(strat_group)

        self._strategy_checks: dict[str, Gtk.CheckButton] = {}
        self._ai_auto_active = False

        # "Alle" Toggle
        self._all_check = Gtk.CheckButton()
        all_row = Adw.ActionRow(
            title=_("Alle Strategien"),
            subtitle=_("Alle gleichzeitig generieren"),
        )
        all_row.add_prefix(self._all_check)
        all_row.set_activatable_widget(self._all_check)
        strat_group.add(all_row)
        self._all_check.connect("toggled", self._on_all_strategies_toggled)

        # "AI waehlt automatisch" Toggle
        self._ai_auto_check = Gtk.CheckButton()
        ai_row = Adw.ActionRow(
            title=_("AI waehlt automatisch"),
            subtitle=_("AI entscheidet welche Strategien optimal sind"),
        )
        ai_row.add_prefix(self._ai_auto_check)
        ai_row.set_activatable_widget(self._ai_auto_check)
        strat_group.add(ai_row)
        self._ai_auto_check.connect("toggled", self._on_ai_auto_toggled)

        # Separator
        sep_row = Adw.ActionRow()
        sep_row.set_sensitive(False)
        strat_group.add(sep_row)

        # Einzelne Strategien
        self._restoring_config = True
        try:
            for strategy in Strategy:
                check = Gtk.CheckButton()
                row = Adw.ActionRow(
                    title=self._STRATEGY_DISPLAY.get(strategy.value, strategy.value),
                    subtitle=self._STRATEGY_SUBTITLES.get(strategy.value, ""),
                )
                row.add_prefix(check)
                row.set_activatable_widget(check)
                strat_group.add(row)
                self._strategy_checks[strategy.value] = check
                check.connect("toggled", self._on_strategy_toggled)

            # Gespeicherte Strategie-Auswahl wiederherstellen
            saved = self.config_manager.config.generator.selected_strategies
            for key, cb in self._strategy_checks.items():
                cb.set_active(key in saved)
        finally:
            self._restoring_config = False

        self._strat_group = strat_group

        # Generieren-Button + Spinner
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
        )
        btn_box.set_margin_top(12)

        self._gen_btn = Gtk.Button(label=_("Tipps generieren"))
        self._gen_btn.set_tooltip_text(_("Generiert Tipps mit den ausgewählten Strategien"))
        self._gen_btn.add_css_class("suggested-action")
        self._gen_btn.add_css_class("pill")
        self._gen_btn.connect("clicked", self._on_generate)
        self.register_readonly_button(self._gen_btn)
        btn_box.append(self._gen_btn)

        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        btn_box.append(self._spinner)

        btn_box.append(
            HelpButton(_("Startet die Generierung auf dem Server. Läuft weiter auch wenn die App geschlossen wird."))
        )

        self._content.append(btn_box)

        # Mass-Gen Settings (Telegram Toggle + Threshold Spin)
        if hasattr(self, "_build_mass_gen_settings"):
            self._build_mass_gen_settings(gen_group)

    # ── Strategie-Checkboxen Callbacks ──

    def _on_all_strategies_toggled(self, check: Gtk.CheckButton) -> None:
        """'Alle' toggled alle Einzel-Checks."""
        active = check.get_active()
        if active:
            # AI-Auto deaktivieren wenn Alle aktiv
            self._ai_auto_check.set_active(False)
        for cb in self._strategy_checks.values():
            cb.set_active(active)
            cb.set_sensitive(not active)

    def _on_ai_auto_toggled(self, check: Gtk.CheckButton) -> None:
        """AI waehlt automatisch: Fragt AI und setzt Checks."""
        if not check.get_active():
            # AI-Modus deaktiviert — manuelle Checks wieder aktivieren
            self._ai_auto_active = False
            all_active = self._all_check.get_active()
            for cb in self._strategy_checks.values():
                cb.set_sensitive(not all_active)
            return

        # 'Alle' deaktivieren
        self._all_check.set_active(False)
        self._ai_auto_active = True

        # Checks deaktivieren waehrend AI entscheidet
        for cb in self._strategy_checks.values():
            cb.set_sensitive(False)

        # AI-Empfehlung im Hintergrund holen
        draw_day = self._get_draw_day()

        def worker():
            try:
                recommended = self._fetch_ai_strategy_recommendation(draw_day)
                GLib.idle_add(self._apply_ai_recommendation, recommended)
            except Exception as e:
                logger.warning(f"AI-Strategie-Empfehlung fehlgeschlagen: {e}")
                GLib.idle_add(self._apply_ai_recommendation, ["ensemble"])

        threading.Thread(target=worker, daemon=True).start()

    def _fetch_ai_strategy_recommendation(
        self, draw_day: DrawDay,
    ) -> list[str]:
        """AI-Empfehlung für optimale Strategien holen."""
        if self.app_mode == "client" and self.api_client:
            try:
                data = self.api_client.recommend_strategies(draw_day.value)
                return data.get("strategies", ["ensemble"])
            except Exception as e:
                logger.warning(f"API Strategie-Empfehlung fehlgeschlagen: {e}")

        # Standalone: direkt AI fragen
        if self._ai_analyst:
            try:
                result = self._ai_analyst.recommend_strategies(draw_day)
                return result.get("strategies", ["ensemble"])
            except Exception as e:
                logger.warning(f"AI Strategie-Empfehlung fehlgeschlagen: {e}")

        return ["ensemble"]

    def _apply_ai_recommendation(self, strategies: list[str]) -> bool:
        """AI-Empfehlung auf Checkboxen anwenden."""
        if not self._ai_auto_active:
            return False
        for key, cb in self._strategy_checks.items():
            cb.set_active(key in strategies)
            cb.set_sensitive(False)  # Manuelles Ändern verhindern bei AI-Modus
        return False

    def _get_selected_strategies(self) -> list[Strategy]:
        """Aktuell ausgewählte Strategien als Liste."""
        selected = []
        for strategy in Strategy:
            check = self._strategy_checks.get(strategy.value)
            if check and check.get_active():
                selected.append(strategy)
        return selected

    def _on_strategy_toggled(self, _check: Gtk.CheckButton) -> None:
        """Strategie-Auswahl geändert — in Config/Server speichern."""
        if getattr(self, "_restoring_config", False):
            return
        selected = [s.value for s in self._get_selected_strategies()]
        if selected:
            if self.app_mode == "client" and self.api_client:
                threading.Thread(
                    target=self._save_server_setting,
                    args=("selected_strategies", selected),
                    daemon=True,
                ).start()
            else:
                self.config_manager.config.generator.selected_strategies = selected
                self.config_manager.save()

    @property
    def MASS_GEN_THRESHOLD(self) -> int:
        """Mass-Gen Schwelle aus Config (editierbar in UI)."""
        return getattr(
            self.config_manager.config.generator, "mass_gen_threshold", 10_000,
        )

    def _on_tip_count_changed(self, spin, _pspec) -> None:
        """Anzahl Tipps geändert — Step anpassen, Hinweis zeigen, speichern."""
        if getattr(self, "_restoring_config", False):
            return
        count = int(spin.get_value())

        # Dynamische Schrittgröße je nach Größenordnung
        adj = spin.get_adjustment()
        if count >= 1_000_000:
            adj.set_step_increment(100_000)
            adj.set_page_increment(1_000_000)
        elif count >= 100_000:
            adj.set_step_increment(10_000)
            adj.set_page_increment(100_000)
        elif count >= 10_000:
            adj.set_step_increment(1_000)
            adj.set_page_increment(10_000)
        elif count >= 1_000:
            adj.set_step_increment(100)
            adj.set_page_increment(1_000)
        else:
            adj.set_step_increment(1)
            adj.set_page_increment(10)

        # Mass-Gen-Hinweis anzeigen ab Schwelle
        if hasattr(self, "_mass_gen_hint"):
            self._mass_gen_hint.set_visible(count >= self.MASS_GEN_THRESHOLD)

        if self.app_mode == "client" and self.api_client:
            threading.Thread(
                target=self._save_server_setting,
                args=("tip_count", count),
                daemon=True,
            ).start()
        else:
            self.config_manager.config.generator.tip_count = count
            self.config_manager.save()

    def _save_server_setting(self, key: str, value) -> None:
        """Generator-UI-Setting auf dem Server speichern (Background)."""
        try:
            self.api_client.update_generator_ui_settings(**{key: value})
        except Exception as e:
            logger.warning(f"Generator-UI-Setting '{key}' nicht gespeichert: {e}")

    # ══════════════════════════════════════════════
    # Ensemble-Gewichte
    # ══════════════════════════════════════════════

    _DEFAULT_WEIGHTS = {
        "hot": 0.8, "cold": 0.5, "mixed": 0.7,
        "ml": 2.5, "ai": 2.0, "avoid": 0.4,
    }

    def _build_weights_section(self) -> None:
        """Ensemble-Gewichte mit Slidern konfigurieren."""
        weights_group = Adw.PreferencesGroup(title=_("Ensemble-Gewichte"))
        weights_group.set_description(
            _("Gewichtung der einzelnen Strategien im Ensemble-Voting")
        )
        self._content.append(weights_group)
        self._weights_group = weights_group

        # Adaptive Toggle
        self._adaptive_toggle = Gtk.Switch()
        self._adaptive_toggle.set_active(True)
        self._adaptive_toggle.set_valign(Gtk.Align.CENTER)
        adaptive_row = Adw.ActionRow(
            title=_("Adaptive Gewichte"),
            subtitle=_("Gewichte automatisch aus Lern-Ergebnissen (AdaptiveLearner)"),
        )
        adaptive_row.add_suffix(self._adaptive_toggle)
        adaptive_row.set_activatable_widget(self._adaptive_toggle)
        weights_group.add(adaptive_row)
        self._adaptive_toggle.connect("notify::active", self._on_adaptive_toggle)

        # Slider pro Strategie
        self._weight_sliders: dict[str, Gtk.Scale] = {}
        self._weight_labels: dict[str, Gtk.Label] = {}

        for strat_key, default_w in self._DEFAULT_WEIGHTS.items():
            display = self._STRATEGY_DISPLAY.get(strat_key, strat_key)

            adj = Gtk.Adjustment(
                value=default_w, lower=0.0, upper=3.0,
                step_increment=0.1, page_increment=0.5,
            )
            scale = Gtk.Scale(
                orientation=Gtk.Orientation.HORIZONTAL,
                adjustment=adj,
            )
            scale.set_hexpand(True)
            scale.set_draw_value(False)
            scale.set_size_request(200, -1)
            scale.set_sensitive(False)  # Adaptive=True → read-only

            val_label = Gtk.Label(label=f"{default_w:.1f}")
            val_label.set_size_request(30, -1)
            val_label.add_css_class("monospace")

            scale.connect("value-changed", self._on_weight_changed, strat_key, val_label)

            row = Adw.ActionRow(title=display)
            row.add_suffix(scale)
            row.add_suffix(val_label)
            weights_group.add(row)

            self._weight_sliders[strat_key] = scale
            self._weight_labels[strat_key] = val_label

        # Zurücksetzen-Button
        reset_btn = Gtk.Button(label=_("Zurücksetzen"))
        reset_btn.set_tooltip_text(_("Strategie-Gewichte auf adaptive Standardwerte zurücksetzen"))
        reset_btn.add_css_class("flat")
        reset_btn.connect("clicked", self._on_reset_weights)
        reset_row = Adw.ActionRow(title="")
        reset_row.add_suffix(reset_btn)
        weights_group.add(reset_row)

        # Adaptive Gewichte initial laden
        self._load_adaptive_weights()

    def _on_adaptive_toggle(self, switch: Gtk.Switch, _pspec) -> None:
        """Adaptive Gewichte ein/ausschalten."""
        adaptive = switch.get_active()
        for scale in self._weight_sliders.values():
            scale.set_sensitive(not adaptive)
        if adaptive:
            self._load_adaptive_weights()

    def _on_weight_changed(
        self, scale: Gtk.Scale, strat_key: str, label: Gtk.Label,
    ) -> None:
        """Slider geändert — Label aktualisieren."""
        val = scale.get_value()
        label.set_label(f"{val:.1f}")


# TODO: Diese Datei ist >500Z weil: UI-Build für Generierung + Strategie-Checkboxen + Gewichte-Slider

