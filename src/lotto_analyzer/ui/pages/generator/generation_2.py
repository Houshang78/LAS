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
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from lotto_analyzer.ui.pages.generator.page import _get_next_draw_date
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


class GenerationMixin2:
    """Teil 2 von GenerationMixin."""

    def _on_reset_weights(self, button: Gtk.Button) -> None:
        """Gewichte auf Default-Werte zurücksetzen."""
        for strat_key, default_w in self._DEFAULT_WEIGHTS.items():
            slider = self._weight_sliders.get(strat_key)
            if slider:
                slider.get_adjustment().set_value(default_w)

    def _load_adaptive_weights(self) -> None:
        """Adaptive Gewichte via API laden."""
        def worker():
            weights = None
            try:
                if self.api_client:
                    draw_day = self._get_draw_day()
                    data = self.api_client.get_strategy_weights(draw_day.value)
                    weights = data.get("weights")
            except Exception as e:
                logger.warning(f"Strategie-Gewichte laden fehlgeschlagen: {e}")
            if weights:
                GLib.idle_add(self._apply_weights_to_sliders, weights)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_weights_to_sliders(self, weights: dict[str, float]) -> bool:
        """Gewichte in Slider uebernehmen."""
        for strat_key, val in weights.items():
            slider = self._weight_sliders.get(strat_key)
            if slider:
                slider.get_adjustment().set_value(val)
        return False

    def _get_custom_weights(self) -> dict[str, float] | None:
        """Benutzerdefinierte Gewichte aus den Slidern lesen."""
        if self._adaptive_toggle.get_active():
            return None  # Adaptive → Server/Generator entscheidet
        return {
            key: slider.get_value()
            for key, slider in self._weight_sliders.items()
        }

    def _on_mode_changed(self, combo, _pspec=None) -> None:
        """Generierungs-Modus umschalten: Statistik / Backtest / Beide."""
        idx = combo.get_selected()
        modes = ["statistik", "backtest", "beide"]
        self._gen_mode = modes[idx] if idx < len(modes) else "statistik"

        is_backtest = self._gen_mode in ("backtest", "beide")
        is_statistik = self._gen_mode in ("statistik", "beide")

        # Backtest-spezifische Widgets ein/ausblenden
        self._bt_window_spin.set_visible(is_backtest)
        self._bt_tips_spin.set_visible(is_backtest)

        # Statistik-spezifische Widgets immer zeigen bei "statistik" und "beide"
        self._count_spin.set_visible(is_statistik)
        self._strat_group.set_visible(is_statistik)

        # Button-Label anpassen
        labels = {
            "statistik": _("Tipps generieren"),
            "backtest": _("Backtest + Generieren"),
            "beide": _("Beide Modi generieren"),
        }
        self._gen_btn.set_label(labels.get(self._gen_mode, _("Tipps generieren")))

    def _on_day_changed(self, combo, _pspec) -> None:
        self._update_target_date()
        self._update_day_toggle_label()
        self._load_latest_predictions()

    def _update_target_date(self) -> None:
        draw_day = self._get_draw_day()
        next_date = _get_next_draw_date(draw_day)
        self._current_draw_date = next_date.isoformat()
        weekday_name = self._DAY_LABELS.get(draw_day.value, draw_day.value)
        self._date_row.set_subtitle(
            f"{weekday_name}, {next_date.strftime('%d.%m.%Y')}"
        )

    def _get_draw_day(self) -> DrawDay:
        idx = self._day_combo.get_selected()
        draw_days = self._config.draw_days
        if idx < len(draw_days):
            return DrawDay(draw_days[idx])
        return DrawDay(draw_days[0])

    def _update_day_toggle_label(self) -> None:
        """Button-Label auf den jeweils anderen Tag setzen."""
        if not hasattr(self, '_day_toggle'):
            return
        draw_days = self._config.draw_days
        if len(draw_days) < 2:
            self._day_toggle.set_visible(False)
            return
        self._day_toggle.set_visible(True)
        idx = self._day_combo.get_selected()
        other_idx = 1 - idx if idx < 2 else 0
        other_day = draw_days[other_idx]
        short = self._DAY_SHORT.get(other_day, other_day)
        self._day_toggle.set_label(f"\u2192 {short}")

    def _on_day_toggle(self, button: Gtk.Button) -> None:
        """Zum anderen Ziehungstag wechseln."""
        idx = self._day_combo.get_selected()
        new_idx = 1 - idx if idx < 2 else 0
        self._day_combo.set_selected(new_idx)

    # ══════════════════════════════════════════════
    # ML-Modelle Sektion
    # ══════════════════════════════════════════════

    def _init_ml_components(self) -> None:
        """ML-Engine und Trainer — läuft nur auf dem Server."""
        # Kein lokales ML-Init mehr im UI. Alles via API.
        pass

    def _build_ml_models_section(self) -> None:
        self._ml_group = Adw.PreferencesGroup(
            title=_("ML-Modelle"),
            description=_("Status und Training der ML-Modelle (RF, GB, LSTM)"),
        )
        self._ml_group.set_header_suffix(
            HelpButton(_("Zeigt ob die ML-Modelle (Random Forest, Gradient Boosting, LSTM) trainiert sind und deren Genauigkeit."))
        )
        self._content.append(self._ml_group)

        days = self._config.draw_days
        short1 = self._DAY_SHORT.get(days[0], days[0])
        short2 = self._DAY_SHORT.get(days[1], days[1])

        # Zwei Spalten nebeneinander (dynamisch für Spieltyp)
        cols_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        cols_box.set_homogeneous(True)

        self._ml_status_labels: dict[str, dict[str, Gtk.Label]] = {}
        self._ml_train_btns: dict[str, Gtk.Button] = {}

        for day in days:
            day_label = self._DAY_LABELS.get(day, day)
            day_short = self._DAY_SHORT.get(day, day)

            col_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            col_title = Gtk.Label(label=day_label)
            col_title.add_css_class("heading")
            col_box.append(col_title)

            self._ml_status_labels[day] = {}
            for model in ["RF", "GB", "LSTM"]:
                lbl = Gtk.Label(label=f"{model}: —")
                lbl.set_xalign(0)
                lbl.add_css_class("monospace")
                col_box.append(lbl)
                self._ml_status_labels[day][model.lower()] = lbl

            btn = Gtk.Button(label=f"{day_short} {_('trainieren')}")
            btn.set_tooltip_text(_("ML-Modelle für diesen Tag trainieren"))
            btn.add_css_class("pill")
            btn.set_margin_top(8)
            btn.connect("clicked", lambda b, d=DrawDay(day): self._start_day_training(d, b))
            col_box.append(btn)
            self._ml_train_btns[day] = btn

            cols_box.append(col_box)

        self._ml_group.add(cols_box)

        # ── Vergleichstabelle day1 ↔ day2 ──
        self._ml_comparison_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4,
        )
        self._ml_comparison_box.set_margin_top(12)
        comp_title = Gtk.Label(label=f"Vergleich {short1} \u2194 {short2}")
        comp_title.add_css_class("heading")
        self._ml_comparison_box.append(comp_title)

        self._ml_comp_labels: dict[str, Gtk.Label] = {}
        for model in ["rf", "gb", "lstm"]:
            lbl = Gtk.Label(label=f"{model.upper():6s} | —         | —         | —")
            lbl.set_xalign(0)
            lbl.add_css_class("monospace")
            self._ml_comparison_box.append(lbl)
            self._ml_comp_labels[model] = lbl

        self._ml_group.add(self._ml_comparison_box)

        # ── ML-Training Spinner + Status ──
        self._ml_train_spinner = Gtk.Spinner()
        self._ml_train_spinner.set_visible(False)
        self._ml_group.add(self._ml_train_spinner)

        self._ml_train_status = Gtk.Label(label="")
        self._ml_train_status.add_css_class("dim-label")
        self._ml_train_status.set_wrap(True)
        self._ml_group.add(self._ml_train_status)

        # ── Training prüfen ──
        self._check_training_btn = Gtk.Button(label=_("Training prüfen"))
        self._check_training_btn.set_tooltip_text(_("Prüft ob ML-Modelle aktuell und trainiert sind"))
        self._check_training_btn.add_css_class("flat")
        self._check_training_btn.set_icon_name("emblem-system-symbolic")
        self._check_training_btn.set_margin_top(8)
        self._check_training_btn.connect("clicked", self._on_check_training)
        self._ml_group.add(self._check_training_btn)

        # ── AI ML-Beratung ──
        self._ai_ml_btn = Gtk.Button(label=_("AI ML-Beratung"))
        self._ai_ml_btn.set_tooltip_text(_("AI analysiert ML-Modelle und gibt Trainings-Empfehlungen"))
        self._ai_ml_btn.add_css_class("flat")
        self._ai_ml_btn.set_icon_name("dialog-information-symbolic")
        self._ai_ml_btn.set_margin_top(8)
        self._ai_ml_btn.connect("clicked", self._on_ai_ml_advice)
        self._ml_group.add(self._ai_ml_btn)

        self._ai_ml_result = Gtk.Label(label="")
        self._ai_ml_result.set_wrap(True)
        self._ai_ml_result.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._ai_ml_result.set_xalign(0)
        self._ai_ml_result.set_selectable(True)
        self._ai_ml_result.set_visible(False)
        self._ml_group.add(self._ai_ml_result)

        # Initial laden
        GLib.idle_add(self._refresh_ml_status)

    def _refresh_ml_status(self) -> bool:
        """ML-Modell-Status via API laden und UI aktualisieren."""
        if not self.api_client:
            return False

        def worker():
            try:
                status = self.api_client.ml_status()
                GLib.idle_add(self._update_ml_status_ui, status)
            except Exception as e:
                logger.warning(f"ML-Status API-Abfrage fehlgeschlagen: {e}")
        threading.Thread(target=worker, daemon=True).start()
        return False

    def _update_ml_status_ui(self, status: dict) -> bool:
        """ML-Status Labels aktualisieren."""
        days = self._config.draw_days
        day_data: dict[str, dict[str, dict]] = {d: {} for d in days}

        for key, info in status.items():
            model_type = info.get("model_type", "")
            draw_day = info.get("draw_day", "")
            acc = info.get("accuracy", 0)
            trained = info.get("last_trained", "")
            trained_short = trained[:10] if trained else "nie"

            text = f"{model_type.upper()}: Acc {acc:.4f}  {trained_short}"

            if draw_day in day_data:
                day_data[draw_day][model_type] = info
                lbl = self._ml_status_labels.get(draw_day, {}).get(model_type)
                if lbl:
                    lbl.set_label(text)

        # Vergleichstabelle aktualisieren
        day1, day2 = days[0], days[1]
        short1 = self._DAY_SHORT.get(day1, day1)
        short2 = self._DAY_SHORT.get(day2, day2)
        for model in ["rf", "gb", "lstm"]:
            acc1 = day_data[day1].get(model, {}).get("accuracy", 0) or 0
            acc2 = day_data[day2].get(model, {}).get("accuracy", 0) or 0
            diff = acc1 - acc2
            better = f"{short1} {diff:+.4f}" if diff > 0 else f"{short2} {abs(diff):+.4f}" if diff < 0 else "gleich"
            text = f"{model.upper():6s} | {acc1:.4f}  | {acc2:.4f}  | {better}"
            lbl = self._ml_comp_labels.get(model)
            if lbl:
                lbl.set_label(text)

        return False

    def _on_check_training(self, button: Gtk.Button) -> None:
        """Training-Status prüfen und in InfoDialog anzeigen."""
        if not self.api_client:
            from lotto_analyzer.ui.helpers import show_error_toast
            show_error_toast(self, _("Serververbindung erforderlich"))
            return

        button.set_sensitive(False)

        def worker():
            try:
                status = self.api_client.ml_status()
                GLib.idle_add(self._show_training_check, status, None, button)
            except Exception as e:
                GLib.idle_add(self._show_training_check, {}, str(e), button)

        threading.Thread(target=worker, daemon=True).start()

    def _show_training_check(self, status: dict, error: str | None, button: Gtk.Button) -> bool:
        """Training-Check Ergebnis als InfoDialog anzeigen."""
        button.set_sensitive(True)

        if error:
            from lotto_analyzer.ui.dialogs.info_dialog import InfoDialog
            InfoDialog.show(self, _("Training-Status"), _("Fehler") + f": {error}")
            return False

        if not status:
            from lotto_analyzer.ui.dialogs.info_dialog import InfoDialog
            InfoDialog.show(self, _("Training-Status"), _("Keine Modell-Informationen verfügbar."))
            return False

        max_age = self.config_manager.config.learning.max_model_age_days
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=max_age)

        lines = [f"ML-Modell-Status (max. Alter: {max_age} Tage)", "=" * 50, ""]
        outdated = []

        for key, info in sorted(status.items()):
            model_type = info.get("model_type", "?").upper()
            draw_day = info.get("draw_day", "?")
            acc = info.get("accuracy", 0)
            trained = info.get("last_trained", "")
            trained_short = trained[:10] if trained else "nie"

            is_old = False
            if trained:
                try:
                    trained_dt = datetime.fromisoformat(trained)
                    # Server kann aware datetime liefern — für Vergleich
                    # müssen beide naive oder beide aware sein
                    if trained_dt.tzinfo is not None:
                        trained_dt = trained_dt.replace(tzinfo=None)
                    is_old = trained_dt < cutoff
                except ValueError:
                    is_old = True
            else:
                is_old = True

            marker = " [VERALTET]" if is_old else ""
            lines.append(f"{model_type:6s} {draw_day:12s}  Acc: {acc:.4f}  Trainiert: {trained_short}{marker}")
            if is_old:
                outdated.append(f"{model_type} ({draw_day})")

        lines.append("")
        if outdated:
            lines.append(f"{_('Veraltete Modelle')} ({len(outdated)}):")
            for m in outdated:
                lines.append(f"  - {m}")
            lines.append("")
            lines.append(_("Empfehlung: Training neu starten."))
        else:
            lines.append(_("Alle Modelle sind aktuell."))

        from lotto_analyzer.ui.dialogs.info_dialog import InfoDialog
        InfoDialog.show(self, _("Training-Status"), "\n".join(lines))
        return False

