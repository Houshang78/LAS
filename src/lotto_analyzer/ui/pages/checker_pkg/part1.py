"""Checker Teil 1."""

from __future__ import annotations

import threading
from gi.repository import Gtk, Adw, GLib
from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from datetime import date, datetime
import time
from lotto_common.config import ConfigManager
from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config


logger = get_logger("checker.part1")

from lotto_analyzer.ui.widgets.number_ball import NumberBallRow

from lotto_analyzer.ui.widgets.help_button import HelpButton


class Part1Mixin:
    pass

    def __init__(self, config_manager: ConfigManager, db: Database | None, app_mode: str, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager, db, app_mode, api_client, app_db=app_db, backtest_db=backtest_db)
        self._checking = False
        self._game_type: GameType = GameType.LOTTO6AUS49
        self._config = get_config(self._game_type)
        self._ai_analyst = None
        self._init_ai()
        self._build_ui()

    def _build_ui(self) -> None:
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        self.append(scrolled)

        clamp = Adw.Clamp(maximum_size=900)
        scrolled.set_child(clamp)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        clamp.set_child(content)

        title = Gtk.Label(label=_("Schein-Prüfung"))
        title.add_css_class("title-1")
        content.append(title)

        # ── Vorhersage laden ──
        pred_group = Adw.PreferencesGroup(
            title=_("Vorhersage laden"),
            description=_("Gespeicherte AI/ML-Vorhersage auswählen und in den Schein eintragen"),
        )
        pred_group.set_header_suffix(
            HelpButton(_("Lade gespeicherte Vorhersagen und trage sie automatisch in die Schein-Prüfung ein."))
        )
        content.append(pred_group)

        # Tab-Toggle: Meine Tipps / Alle Vorhersagen
        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        tab_box.set_margin_bottom(4)

        self._pred_tab_mine = Gtk.ToggleButton(label=_("Meine Tipps"))
        self._pred_tab_mine.set_active(True)
        self._pred_tab_mine.add_css_class("flat")
        self._pred_tab_mine.connect("toggled", self._on_pred_tab_changed)
        tab_box.append(self._pred_tab_mine)

        self._pred_tab_all = Gtk.ToggleButton(label=_("Alle Vorhersagen"))
        self._pred_tab_all.set_active(False)
        self._pred_tab_all.add_css_class("flat")
        self._pred_tab_all.connect("toggled", self._on_pred_tab_changed)
        tab_box.append(self._pred_tab_all)

        pred_group.add(tab_box)

        # Ziehtag + Datum + Laden in einer Zeile
        pred_filter = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        pred_day_label = Gtk.Label(label=_("Ziehtag:"))
        pred_filter.append(pred_day_label)

        self._pred_day_combo = Gtk.ComboBoxText()
        for day in ["saturday", "wednesday", "tuesday", "friday"]:
            self._pred_day_combo.append_text(day)
        self._pred_day_combo.set_active(0)
        self._pred_day_combo.connect("changed", self._on_pred_day_changed)
        pred_filter.append(self._pred_day_combo)

        pred_date_label = Gtk.Label(label=_("Datum:"))
        pred_date_label.set_margin_start(12)
        pred_filter.append(pred_date_label)

        self._pred_date_combo = Gtk.ComboBoxText()
        self._pred_date_combo.set_size_request(150, -1)
        pred_filter.append(self._pred_date_combo)

        self._pred_load_btn = Gtk.Button(label=_("Laden"))
        self._pred_load_btn.add_css_class("suggested-action")
        self._pred_load_btn.set_icon_name("view-refresh-symbolic")
        self._pred_load_btn.set_margin_start(12)
        self._pred_load_btn.connect("clicked", self._on_load_predictions)
        pred_filter.append(self._pred_load_btn)

        pred_group.add(pred_filter)

        # Vorhersage-Auswahl ComboBox
        self._pred_select_combo = Gtk.ComboBoxText()
        self._pred_select_combo.set_size_request(400, -1)
        self._pred_select_combo.append_text(_("— Erst Vorhersagen laden —"))
        self._pred_select_combo.set_active(0)
        pred_group.add(self._pred_select_combo)

        # Eintragen-Button + Status-Label
        pred_action = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        pred_action.set_margin_top(4)

        self._pred_fill_btn = Gtk.Button(label=_("Eintragen"))
        self._pred_fill_btn.add_css_class("pill")
        self._pred_fill_btn.set_icon_name("emblem-ok-symbolic")
        self._pred_fill_btn.set_tooltip_text(_("Vorhersage in Schein-Felder eintragen"))
        self._pred_fill_btn.connect("clicked", self._on_fill_prediction)
        self._pred_fill_btn.set_sensitive(False)
        pred_action.append(self._pred_fill_btn)

        self._pred_status = Gtk.Label(label="")
        self._pred_status.add_css_class("dim-label")
        self._pred_status.set_hexpand(True)
        self._pred_status.set_xalign(0)
        pred_action.append(self._pred_status)

        pred_group.add(pred_action)

        # Interner Cache für geladene Predictions
        self._pred_items: list[dict] = []

        # Zahlen-Eingabe
        self._input_group = Adw.PreferencesGroup(
            title=_("Dein Schein"),
            description=(
                f"{self._config.main_count} " + _("Zahlen") + " "
                f"({self._config.main_min}-{self._config.main_max}) " + _("und") + " "
                f"{self._config.bonus_name} "
                f"({self._config.bonus_min}-{self._config.bonus_max}) " + _("eingeben")
            ),
        )
        self._input_group.set_header_suffix(
            HelpButton(_("Deine 6 getippten Zahlen eingeben (1-49). Jede Zahl darf nur einmal vorkommen."))
        )
        content.append(self._input_group)

        # Hauptzahlen-Felder
        self._number_entries: list[Adw.SpinRow] = []
        for i in range(self._config.main_count):
            spin = Adw.SpinRow.new_with_range(
                self._config.main_min, self._config.main_max, 1,
            )
            spin.set_title(_("Zahl") + f" {i + 1}")
            spin.set_value(self._config.main_min)
            self._number_entries.append(spin)
            self._input_group.add(spin)

        # Bonus-Zahlen (Superzahl / Eurozahlen)
        self._bonus_entries: list[Adw.SpinRow] = []
        for i in range(self._config.bonus_count):
            title = self._config.bonus_name if self._config.bonus_count == 1 else f"{self._config.bonus_name} {i + 1}"
            spin = Adw.SpinRow.new_with_range(
                self._config.bonus_min, self._config.bonus_max, 1,
            )
            spin.set_title(title)
            spin.set_value(self._config.bonus_min)
            self._bonus_entries.append(spin)
            self._input_group.add(spin)

        # Legacy alias for backward compatibility
        self._super_entry = self._bonus_entries[0] if self._bonus_entries else None

        # Ziehungsdatum
        date_group = Adw.PreferencesGroup(title=_("Ziehung"))
        content.append(date_group)

        self._day_combo = Adw.ComboRow(title=_("Ziehungstag"))
        self._day_combo.add_suffix(
            HelpButton(_("An welchem Tag die Ziehung stattfand (Samstag oder Mittwoch)."))
        )
        day_model = Gtk.StringList()
        day_labels = {
            "saturday": _("Samstag"), "wednesday": _("Mittwoch"),
            "tuesday": _("Dienstag"), "friday": _("Freitag"),
        }
        for d in self._config.draw_days:
            day_model.append(day_labels.get(d, d))
        self._day_combo.set_model(day_model)
        date_group.add(self._day_combo)

        self._date_entry = Adw.EntryRow(title=_("Datum (TT.MM.JJJJ)"))
        self._date_entry.set_text(date.today().strftime("%d.%m.%Y"))
        self._date_entry.add_suffix(
            HelpButton(_("Datum der Ziehung im Format TT.MM.JJJJ (z.B. 15.03.2025)."))
        )
        date_group.add(self._date_entry)

        # Prüfen-Button + Spinner
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
        )
        btn_box.set_margin_top(12)
        self._check_btn = Gtk.Button(label=_("Schein prüfen"))
        self._check_btn.add_css_class("suggested-action")
        self._check_btn.add_css_class("pill")
        self._check_btn.set_tooltip_text(_("Vergleicht deine Zahlen mit der Ziehung und berechnet Treffer und Gewinnklasse (1-9)."))
        self._check_btn.connect("clicked", self._on_check)
        btn_box.append(self._check_btn)

        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        btn_box.append(self._spinner)

        content.append(btn_box)

        # Ergebnis
        result_group = Adw.PreferencesGroup(title=_("Ergebnis"))
        result_group.set_header_suffix(
            HelpButton(_("Gruen markierte Kugeln = Treffer. Gewinnklasse 1 = Jackpot (6 Richtige + SZ), Klasse 9 = 2 Richtige + SZ."))
        )
        content.append(result_group)

        # NumberBallRow: Deine Zahlen mit Match-Highlighting
        self._your_balls = NumberBallRow()
        self._your_balls.set_margin_top(8)
        self._your_balls.set_margin_bottom(4)
        result_group.add(self._your_balls)

        self._your_label = Gtk.Label(label=_("Deine Zahlen"))
        self._your_label.add_css_class("dim-label")
        result_group.add(self._your_label)

        # NumberBallRow: Gezogene Zahlen
        self._drawn_balls = NumberBallRow()
        self._drawn_balls.set_margin_top(8)
        self._drawn_balls.set_margin_bottom(4)
        result_group.add(self._drawn_balls)

        self._drawn_label = Gtk.Label(label=_("Gezogene Zahlen"))
        self._drawn_label.add_css_class("dim-label")
        result_group.add(self._drawn_label)

        self._result_row = Adw.ActionRow(
            title=_("Noch nicht geprüft"),
            subtitle=_("Gib deine Zahlen ein und klicke 'Prüfen'"),
        )
        self._result_row.add_prefix(
            Gtk.Image.new_from_icon_name("emblem-default-symbolic")
        )
        result_group.add(self._result_row)

        self._matches_row = Adw.ActionRow(
            title=_("Treffer"),
            subtitle="—",
        )
        result_group.add(self._matches_row)

        self._prize_row = Adw.ActionRow(
            title=_("Gewinnklasse"),
            subtitle="—",
        )
        result_group.add(self._prize_row)

        self._prize_amount_row = Adw.ActionRow(
            title=_("Gewinnbetrag"),
            subtitle="—",
        )
        self._prize_amount_row.add_prefix(
            Gtk.Image.new_from_icon_name("wallet-symbolic")
        )
        result_group.add(self._prize_amount_row)

        # AI-Panel
        self._ai_panel = AIPanel(
            ai_analyst=self._ai_analyst, api_client=self.api_client,
            title=_("AI-Analyse"), config_manager=self.config_manager,
            db=self.db, page="checker", app_db=self.app_db,
        )
        content.append(self._ai_panel)

        # Initial: Datum-Liste für Standard-Ziehtag laden
        self._on_pred_day_changed(self._pred_day_combo)

    def _init_ai(self) -> None:
        # Standalone-AI entfernt: AI läuft immer auf dem Server
        pass

    def set_game_type(self, game_type: GameType) -> None:
        """Spieltyp wechseln — Eingabefelder und Tag-Combo neu aufbauen."""
        self._game_type = game_type
        self._config = get_config(game_type)

        # Beschreibung anpassen
        self._input_group.set_description(
            f"{self._config.main_count} " + _("Zahlen") + " "
            f"({self._config.main_min}-{self._config.main_max}) " + _("und") + " "
            f"{self._config.bonus_name} "
            f"({self._config.bonus_min}-{self._config.bonus_max}) " + _("eingeben")
        )

        # Alte Einträge entfernen
        for spin in self._number_entries:
            self._input_group.remove(spin)
        for spin in self._bonus_entries:
            self._input_group.remove(spin)

        # Neue Hauptzahlen-Felder
        self._number_entries = []
        for i in range(self._config.main_count):
            spin = Adw.SpinRow.new_with_range(
                self._config.main_min, self._config.main_max, 1,
            )
            spin.set_title(_("Zahl") + f" {i + 1}")
            spin.set_value(self._config.main_min)
            self._number_entries.append(spin)
            self._input_group.add(spin)

        # Neue Bonus-Felder
        self._bonus_entries = []
        for i in range(self._config.bonus_count):
            title = self._config.bonus_name if self._config.bonus_count == 1 else f"{self._config.bonus_name} {i + 1}"
            spin = Adw.SpinRow.new_with_range(
                self._config.bonus_min, self._config.bonus_max, 1,
            )
            spin.set_title(title)
            spin.set_value(self._config.bonus_min)
            self._bonus_entries.append(spin)
            self._input_group.add(spin)

        self._super_entry = self._bonus_entries[0] if self._bonus_entries else None

        # Tag-Combo
        day_labels = {
            "saturday": _("Samstag"), "wednesday": _("Mittwoch"),
            "tuesday": _("Dienstag"), "friday": _("Freitag"),
        }
        day_model = Gtk.StringList()
        for d in self._config.draw_days:
            day_model.append(day_labels.get(d, d))
        self._day_combo.set_model(day_model)
        self._day_combo.set_selected(0)

        # Ergebnis zurücksetzen
        self._result_row.set_title(_("Noch nicht geprüft"))
        self._result_row.set_subtitle(_("Gib deine Zahlen ein und klicke 'Prüfen'"))
        self._matches_row.set_subtitle("\u2014")
        self._prize_row.set_subtitle("\u2014")
        self._prize_amount_row.set_subtitle("\u2014")

    def set_api_client(self, client: "APIClient | None") -> None:
        """API-Client setzen."""
        super().set_api_client(client)
        self._ai_panel.api_client = client

