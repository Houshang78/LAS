"""Einstellungen: AI, Server, Verbindungsprofile, Claude CLI, Allgemein."""

from __future__ import annotations

import os
import subprocess
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.config import ConfigManager
from lotto_common.i18n import _
from lotto_common.models.ai_config import AIMode, AIModel, ServerConfig, resolve_cli_path
from lotto_common.models.user import ConnectionProfile
from lotto_analyzer.client.api_client import APIClient
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_analyzer.ui.widgets.help_button import HelpButton
from lotto_analyzer.ui.ui_helpers import show_error_toast
from lotto_common.utils.logging_config import get_logger

logger = get_logger("settings")


from lotto_analyzer.ui.pages.settings.part1 import Part1Mixin
from lotto_analyzer.ui.pages.settings.part2 import Part2Mixin
from lotto_analyzer.ui.pages.settings.part3 import Part3Mixin
from lotto_analyzer.ui.pages.settings.part4 import Part4Mixin


class SettingsPage(Part1Mixin, Part2Mixin, Part3Mixin, Part4Mixin, BasePage):
    """App-Einstellungen: AI, Server, Profile, Theme, Crawl-Zeitplan."""

    def __init__(self, config_manager: ConfigManager, db: Database | None, app_mode: str, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager, db, app_mode, api_client, app_db=app_db, backtest_db=backtest_db)

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

        title = Gtk.Label(label=_("Einstellungen"))
        title.add_css_class("title-1")
        content.append(title)

        config = self.config_manager.config

        # ── AI-Einstellungen ──
        ai_group = Adw.PreferencesGroup(
            title=_("AI-Konfiguration"),
            description=_("Claude für Analyse und Chat"),
        )
        ai_group.set_header_suffix(HelpButton(
            _("Claude AI für Chat, Analyse und Self-Improvement. "
              "API braucht einen Anthropic-Key, CLI eine lokale Claude-Installation.")
        ))
        content.append(ai_group)

        # Modus
        self._ai_mode = Adw.ComboRow(title=_("AI-Modus"))
        mode_model = Gtk.StringList()
        mode_model.append("API (Anthropic)")
        mode_model.append("CLI (Lokal)")
        self._ai_mode.set_model(mode_model)
        self._ai_mode.set_selected(0 if config.ai.mode == AIMode.API else 1)
        ai_group.add(self._ai_mode)

        # Modell
        self._model_combo = Adw.ComboRow(title=_("Claude-Modell"))
        model_list = Gtk.StringList()
        self._model_values = []
        selected_idx = 0
        for i, (model_id, display) in enumerate(AIModel.display_names().items()):
            model_list.append(display)
            self._model_values.append(model_id)
            if model_id == config.ai.model:
                selected_idx = i
        self._model_combo.set_model(model_list)
        self._model_combo.set_selected(selected_idx)
        ai_group.add(self._model_combo)

        # API-Key
        self._api_key = Adw.PasswordEntryRow(title=_("API-Schlüssel"))
        if config.ai.api_key:
            self._api_key.set_text(config.ai.api_key)
        ai_group.add(self._api_key)

        # ── Claude CLI ──
        cli_group = Adw.PreferencesGroup(
            title=_("Claude CLI"),
            description=_("Lokale Claude-CLI-Installation"),
        )
        cli_group.set_header_suffix(HelpButton(
            _("Lokale Claude-Ausfuehrung ohne API-Key. "
              "Muss installiert und authentifiziert sein (claude auth login).")
        ))
        content.append(cli_group)

        self._cli_path = Adw.EntryRow(title=_("CLI-Pfad"))
        self._cli_path.set_text(config.ai.cli_path)
        cli_group.add(self._cli_path)

        cli_test_btn = Gtk.Button(label=_("Testen"))
        cli_test_btn.set_valign(Gtk.Align.CENTER)
        cli_test_btn.connect("clicked", self._on_test_cli)
        self._cli_test_row = Adw.ActionRow(
            title=_("CLI-Test"),
            subtitle=_("Server-seitig") if self.app_mode == "client" else _("claude --version prüfen"),
        )
        self._cli_test_row.add_suffix(cli_test_btn)
        cli_group.add(self._cli_test_row)

        detect_btn = Gtk.Button(label=_("Auto-Detect"))
        detect_btn.set_tooltip_text(_("Claude CLI automatisch suchen"))
        detect_btn.set_valign(Gtk.Align.CENTER)
        detect_btn.connect("clicked", self._on_auto_detect_cli)
        self._cli_test_row.add_suffix(detect_btn)

        # Client-Modus: lokale CLI-Tests deaktivieren (CLI läuft auf dem Server)
        if self.app_mode == "client":
            cli_test_btn.set_sensitive(False)
            detect_btn.set_sensitive(False)

        # Client-Modus: Server-Einstellungen laden
        if self.app_mode == "client" and self.api_client:
            self._load_server_settings()

        # ── Verbindungsprofile ──
        profile_group = Adw.PreferencesGroup(
            title=_("Verbindungsprofile"),
            description=_("Gespeicherte Server-Verbindungen"),
        )
        content.append(profile_group)

        # Profil-Auswahl
        self._profile_combo = Adw.ComboRow(title=_("Aktives Profil"))
        profile_list = Gtk.StringList()
        self._profile_names = []
        profiles = config.connection_profiles
        selected_profile = 0
        for i, p in enumerate(profiles):
            label = f"{p.name} ({p.host}:{p.port})"
            if p.use_ssh:
                label += f" [{_('SSH')}]"
            if p.is_default:
                label += f" [{_('Standard')}]"
                selected_profile = i
            profile_list.append(label)
            self._profile_names.append(p.name)
        if not profiles:
            profile_list.append(_("Kein Profil"))
        self._profile_combo.set_model(profile_list)
        if profiles:
            self._profile_combo.set_selected(selected_profile)
        profile_group.add(self._profile_combo)

        # Profil-Buttons
        profile_btn_row = Adw.ActionRow(title=_("Profil-Verwaltung"))
        for label, handler in [
            (_("Neu"), self._on_add_profile),
            (_("Bearbeiten"), self._on_edit_profile),
            (_("Löschen"), self._on_delete_profile),
        ]:
            btn = Gtk.Button(label=label)
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect("clicked", handler)
            profile_btn_row.add_suffix(btn)
        profile_group.add(profile_btn_row)

        # ── Server-Einstellungen (Fallback) ──
        server_group = Adw.PreferencesGroup(
            title=_("Server-Verbindung"),
            description=_("Direkte Verbindung (ohne Profil)"),
        )
        server_group.set_header_suffix(HelpButton(
            _("Direkte Verbindung zum LottoAnalyzer-Server wenn kein Profil gewählt ist.")
        ))
        content.append(server_group)

        self._server_host = Adw.EntryRow(title=_("Server-IP"))
        self._server_host.set_text(config.server.host)
        server_group.add(self._server_host)

        self._server_port = Adw.SpinRow.new_with_range(1024, 65535, 1)
        self._server_port.set_title("Port")
        self._server_port.set_value(config.server.port)
        server_group.add(self._server_port)

        self._server_https = Adw.SwitchRow(
            title=_("HTTPS"),
            subtitle=_("Server nutzt TLS-Verschlüsselung"),
        )
        self._server_https.set_active(config.server.use_https)
        server_group.add(self._server_https)

        self._test_btn = Gtk.Button(label=_("Verbindung testen"))
        self._test_btn.set_tooltip_text(_("Verbindung zum Server testen"))
        self._test_btn.set_valign(Gtk.Align.CENTER)
        self._test_btn.connect("clicked", self._on_test_connection)
        self._test_row = Adw.ActionRow(
            title=_("Verbindungstest"),
            subtitle=_("Prüfen ob der Server erreichbar ist"),
        )
        self._test_row.add_suffix(self._test_btn)
        server_group.add(self._test_row)

        # ── Auto-Crawl ──
        crawl_group = Adw.PreferencesGroup(
            title=_("Auto-Crawl Zeitplan"),
            description=_("Automatische Prüfung auf neue Ziehungen"),
        )
        crawl_group.set_header_suffix(HelpButton(
            _("Automatische Prüfung auf neue Ziehungen nach offiziellem Ziehungstermin. "
              "Bei Misserfolg wird alle X Stunden erneut versucht.")
        ))
        content.append(crawl_group)

        self._crawl_enabled = Adw.SwitchRow(
            title=_("Auto-Crawl aktiviert"),
            subtitle=_("6aus49: Mi+Sa | EuroJackpot: Di+Fr"),
        )
        self._crawl_enabled.set_active(config.crawl_schedule.enabled)
        crawl_group.add(self._crawl_enabled)

        self._retry_interval = Adw.SpinRow.new_with_range(1, 12, 1)
        self._retry_interval.set_title(_("Retry-Intervall (Stunden)"))
        self._retry_interval.set_value(config.crawl_schedule.retry_interval_hours)
        crawl_group.add(self._retry_interval)

        # ── Lern-Engine ──
        learn_group = Adw.PreferencesGroup(
            title=_("Lern-Engine"),
            description=_("Automatische Optimierung aus Erfahrungswerten"),
        )
        learn_group.set_header_suffix(HelpButton(
            _("Das Lernsystem optimiert ML-Modelle, Crawl-Timing und "
              "Strategie-Gewichte automatisch aus Erfahrungswerten.")
        ))
        content.append(learn_group)

        self._learn_enabled = Adw.SwitchRow(
            title=_("Lern-Engine aktiv"),
            subtitle=_("Hauptschalter für alle Lernfunktionen"),
        )
        self._learn_enabled.set_active(config.learning.enabled)
        learn_group.add(self._learn_enabled)

        self._auto_retrain = Adw.SwitchRow(
            title=_("Auto-Retrain nach Ziehung"),
            subtitle=_("ML-Modelle nach neuer Ziehung nachtrainieren"),
        )
        self._auto_retrain.set_active(config.learning.auto_retrain_after_draw)
        learn_group.add(self._auto_retrain)

        self._train_on_startup = Adw.SwitchRow(
            title=_("Training bei Server-Start"),
            subtitle=_("Fehlende/veraltete Modelle beim Start trainieren"),
        )
        self._train_on_startup.set_active(config.learning.auto_train_on_startup)
        learn_group.add(self._train_on_startup)

        self._self_improve = Adw.SwitchRow(
            title=_("Self-Improvement (AI)"),
            subtitle=_("Claude schlaegt Features vor und testet in Sandbox"),
        )
        self._self_improve.set_active(config.learning.auto_self_improve)
        learn_group.add(self._self_improve)

        self._crawl_timing = Adw.SwitchRow(
            title=_("Crawl-Timing lernen"),
            subtitle=_("Crawl-Zeiten aus Erfahrung optimieren"),
        )
        self._crawl_timing.set_active(config.learning.crawl_timing_learning)
        learn_group.add(self._crawl_timing)

        self._strategy_weights = Adw.SwitchRow(
            title=_("Strategie-Gewichte lernen"),
            subtitle=_("Gewichtung anhand Trefferquoten anpassen"),
        )
        self._strategy_weights.set_active(config.learning.strategy_weight_learning)
        learn_group.add(self._strategy_weights)

        self._eval_window = Adw.SpinRow.new_with_range(10, 200, 10)
        self._eval_window.set_title(_("Bewertungsfenster"))
        self._eval_window.set_value(config.learning.evaluation_window)
        learn_group.add(self._eval_window)

        self._max_model_age = Adw.SpinRow.new_with_range(1, 30, 1)
        self._max_model_age.set_title(_("Max Modell-Alter (Tage)"))
        self._max_model_age.set_value(config.learning.max_model_age_days)
        learn_group.add(self._max_model_age)

        # HelpButtons für Lern-Engine Rows
        for row, text in [
            (self._learn_enabled, _("Hauptschalter: Deaktiviert alle Lernfunktionen auf einmal.")),
            (self._auto_retrain, _("Nach jeder neuen Ziehung werden RF-, GB- und LSTM-Modelle mit den neuen Daten nachtrainiert.")),
            (self._train_on_startup, _("Beim Serverstart wird geprüft ob ML-Modelle fehlen oder veraltet sind — falls ja, automatisches Training.")),
            (self._self_improve, _("Claude schlaegt neue Features und Strategien vor, testet sie in einer Sandbox und uebernimmt nur Verbesserungen. Braucht API-Key oder CLI.")),
            (self._crawl_timing, _("Lernt aus vergangenen Crawls wann Ergebnisse online verfügbar sind und passt die Crawl-Zeiten automatisch an.")),
            (self._strategy_weights, _("Passt Gewichtung der Strategien (hot/cold/ml/avoid/...) automatisch anhand der Trefferquoten an.")),
            (self._eval_window, _("Anzahl der letzten Vorhersagen die für die Gewichtsberechnung herangezogen werden.")),
            (self._max_model_age, _("Modelle aelter als X Tage werden beim nächsten Zyklus automatisch neu trainiert.")),
        ]:
            row.add_suffix(HelpButton(text))

        # ── Auto-Generierung ──
        autogen_group = Adw.PreferencesGroup(
            title=_("Auto-Generierung"),
            description=_("Automatische Vorhersage-Erzeugung nach Crawl/Training"),
        )
        autogen_group.set_header_suffix(HelpButton(
            _("Automatische Vorhersage-Erzeugung: Nach jeder Ziehung werden Tipps generiert, "
              "mit Ergebnissen verglichen und schlechte Tipps gelöscht.")
        ))
        content.append(autogen_group)

        self._autogen_enabled = Adw.SwitchRow(
            title=_("Auto-Generierung aktiv"),
            subtitle=_("Automatisch Vorhersagen nach jedem Crawl erzeugen"),
        )
        self._autogen_enabled.set_active(config.auto_generation.enabled)
        autogen_group.add(self._autogen_enabled)

        self._gen_after_train = Adw.SwitchRow(
            title=_("Generieren nach Training"),
            subtitle=_("Nach ML-Retrain sofort neue Vorhersagen erzeugen"),
        )
        self._gen_after_train.set_active(config.auto_generation.generate_after_train)
        autogen_group.add(self._gen_after_train)

        self._auto_compare = Adw.SwitchRow(
            title=_("Auto-Vergleich"),
            subtitle=_("Alte Vorhersagen mit Ziehungsergebnissen vergleichen"),
        )
        self._auto_compare.set_active(config.auto_generation.auto_compare)
        autogen_group.add(self._auto_compare)

        self._count_per_strategy = Adw.SpinRow.new_with_range(50, 500, 10)
        self._count_per_strategy.set_title(_("Tipps pro Strategie"))
        self._count_per_strategy.set_value(config.auto_generation.count_per_strategy)
        autogen_group.add(self._count_per_strategy)

        self._purchase_count = Adw.SpinRow.new_with_range(1, 20, 1)
        self._purchase_count.set_title(_("Kaufanzahl (Telegram)"))
        self._purchase_count.set_value(config.auto_generation.purchase_count)
        autogen_group.add(self._purchase_count)

        # HelpButtons für Auto-Generierung Rows
        for row, text in [
            (self._autogen_enabled, _("Server generiert automatisch ~1000 Vorhersagen pro Ziehungstag nach jedem Crawl-Zyklus.")),
            (self._gen_after_train, _("Sofort nach ML-Retrain neue Vorhersagen erzeugen (nutzt die frisch trainierten Modelle).")),
            (self._auto_compare, _("Alte Vorhersagen automatisch mit Ziehungsergebnissen vergleichen. Grundlage für das Lernsystem und Telegram-Treffer-Alarm.")),
            (self._count_per_strategy, _("Anzahl Vorhersagen pro Strategie pro Ziehung. Bei 7 Strategien x 170 = ~1190 Tipps.")),
            (self._purchase_count, _("Anzahl der besten Tipps die beim Kauf markiert und an Telegram gesendet werden.")),
        ]:
            row.add_suffix(HelpButton(text))

        # ── Audio / Sprache ──
        audio_group = Adw.PreferencesGroup(
            title=_("Audio / Sprache"),
            description=_("Text-to-Speech (gTTS) und Spracheingabe (OpenAI Whisper)"),
        )
        audio_group.set_header_suffix(HelpButton(
            _("Text-to-Speech liest AI-Antworten vor. "
              "Spracheingabe nutzt OpenAI Whisper (braucht separaten API-Key).")
        ))
        content.append(audio_group)

        self._tts_enabled = Adw.SwitchRow(
            title=_("Vorlesen aktiviert"),
            subtitle=_("AI-Antworten per gTTS vorlesen"),
        )
        self._tts_enabled.set_active(config.audio.tts_enabled)
        audio_group.add(self._tts_enabled)

        self._tts_lang = Adw.ComboRow(title=_("Sprache"))
        lang_model = Gtk.StringList()
        self._lang_codes = ["de", "en", "fr", "es", "it", "tr"]
        lang_labels = ["Deutsch", "English", "Francais", "Espanol", "Italiano", "Tuerkce"]
        for lbl in lang_labels:
            lang_model.append(lbl)
        self._tts_lang.set_model(lang_model)
        try:
            lang_idx = self._lang_codes.index(config.audio.tts_language)
        except ValueError:
            lang_idx = 0
        self._tts_lang.set_selected(lang_idx)
        audio_group.add(self._tts_lang)

        self._stt_enabled = Adw.SwitchRow(
            title=_("Spracheingabe aktiviert"),
            subtitle=_("Mikrofon-Eingabe per OpenAI Whisper"),
        )
        self._stt_enabled.set_active(config.audio.stt_enabled)
        audio_group.add(self._stt_enabled)

        self._openai_key = Adw.PasswordEntryRow(title=_("OpenAI API-Key"))
        if config.audio.openai_api_key:
            self._openai_key.set_text(config.audio.openai_api_key)
        audio_group.add(self._openai_key)

        # ── Allgemein ──
        general_group = Adw.PreferencesGroup(title=_("Allgemein"))
        content.append(general_group)

        # UI-Sprache
        self._ui_lang_combo = Adw.ComboRow(title=_("Sprache / Language"))
        ui_lang_model = Gtk.StringList()
        self._ui_lang_codes = ["de", "fa", "en"]
        ui_lang_labels = ["Deutsch", "فارسی (Persisch)", "English"]
        for lbl in ui_lang_labels:
            ui_lang_model.append(lbl)
        self._ui_lang_combo.set_model(ui_lang_model)
        current_lang = getattr(config, "ui_language", "de")
        try:
            self._ui_lang_combo.set_selected(self._ui_lang_codes.index(current_lang))
        except ValueError:
            self._ui_lang_combo.set_selected(0)
        general_group.add(self._ui_lang_combo)

        self._theme_combo = Adw.ComboRow(title=_("Theme"))
        theme_model = Gtk.StringList()
        for t in [_("System"), _("Hell"), _("Dunkel")]:
            theme_model.append(t)
        self._theme_combo.set_model(theme_model)
        themes = {"system": 0, "light": 1, "dark": 2}
        self._theme_combo.set_selected(themes.get(config.theme, 0))
        general_group.add(self._theme_combo)

        # Schriftgröße
        self._font_size_spin = Adw.SpinRow.new_with_range(8, 24, 1)
        self._font_size_spin.set_title(_("Schriftgröße (pt)"))
        self._font_size_spin.set_value(config.font_size)
        general_group.add(self._font_size_spin)

        # Fettschrift
        self._font_bold_switch = Adw.SwitchRow(
            title=_("Fettschrift"),
            subtitle=_("Alle Texte fett darstellen"),
        )
        self._font_bold_switch.set_active(config.font_bold)
        general_group.add(self._font_bold_switch)

        # Popup-Schriftgröße
        self._popup_font_spin = Adw.SpinRow.new_with_range(8, 32, 1)
        self._popup_font_spin.set_title(_("Popup-Schriftgröße (pt)"))
        self._popup_font_spin.set_value(config.popup_font_size)
        general_group.add(self._popup_font_spin)

        # Speichern-Button
        btn_box = Gtk.Box(halign=Gtk.Align.CENTER)
        btn_box.set_margin_top(24)
        self._save_btn = Gtk.Button(label=_("Einstellungen speichern"))
        self._save_btn.set_tooltip_text(_("Alle Einstellungen speichern"))
        self._save_btn.add_css_class("suggested-action")
        self._save_btn.add_css_class("pill")
        self._save_btn.connect("clicked", self._on_save)
        self.register_readonly_button(self._save_btn)
        btn_box.append(self._save_btn)
        content.append(btn_box)

        # User management (admin/owner only, built by Part4Mixin)
        self._build_user_management_section(content)
        self._user_role = None
        self._viewer_user_id = None

