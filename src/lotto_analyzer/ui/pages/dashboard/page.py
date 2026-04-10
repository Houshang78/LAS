"""Dashboard-Seite: Übersicht, letzte Ziehung, Status."""

from __future__ import annotations

import sqlite3
import threading

import gi

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config

logger = get_logger("dashboard_page")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio

from lotto_common.config import ConfigManager
from lotto_analyzer.ui.ui_helpers import show_toast
from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from lotto_analyzer.ui.widgets.chart_view import ChartView
from lotto_analyzer.ui.widgets.help_button import HelpButton


_DAY_NAMES = {
    "saturday": _("Samstag"),
    "wednesday": _("Mittwoch"),
    "tuesday": _("Dienstag"),
    "friday": _("Freitag"),
}


from lotto_analyzer.ui.pages.dashboard.part1 import Part1Mixin
from lotto_analyzer.ui.pages.dashboard.part2 import Part2Mixin
from lotto_analyzer.ui.pages.dashboard.part3 import Part3Mixin


class DashboardPage(Part1Mixin, Part2Mixin, Part3Mixin, BasePage):
    """Hauptseite mit Übersicht aller Daten."""

    COUNTDOWN_INTERVAL = 60  # Sekunden zwischen Countdown-Updates

    def __init__(self, config_manager: ConfigManager, db: Database | None, app_mode: str, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager, db, app_mode, api_client, app_db=app_db, backtest_db=backtest_db)
        self._game_type: GameType = GameType.LOTTO6AUS49
        self._config = get_config(self._game_type)
        self._ai_analyst = None
        self._countdown_timer_id: int = 0
        self._init_ai()
        self._build_ui()

    def _init_ai(self) -> None:
        # Standalone-AI entfernt: AI läuft immer auf dem Server
        pass

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

        # Titel
        title = Gtk.Label(label=_("Dashboard"))
        title.add_css_class("title-1")
        content.append(title)

        # Letzte Ziehungen
        self._draws_group = Adw.PreferencesGroup(
            title=_("Letzte Ziehungen"),
            description=self._config.display_name,
        )
        self._draws_group.set_header_suffix(
            HelpButton(_("Zeigt die neueste Ziehung pro Wochentag mit Datum und Zahlen."))
        )
        content.append(self._draws_group)

        # DB-Integrität
        self._integrity_group = Adw.PreferencesGroup(
            title=_("DB-Integrität"),
            description=_("Vollständigkeitspruefung"),
        )
        self._integrity_group.set_header_suffix(
            HelpButton(_("Prüft ob alle Ziehungen seit 1956 lueckenlos in der Datenbank vorhanden sind. Lücken = fehlende Jahre."))
        )
        content.append(self._integrity_group)
        self._integrity_row = Adw.ActionRow(
            title=_("Status"), subtitle=_("Wird geprüft..."),
        )
        self._integrity_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        self._integrity_row.add_prefix(self._integrity_icon)
        self._integrity_group.add(self._integrity_row)
        self._integrity_details: list[Adw.ActionRow] = []

        # DB-Status
        self._status_group = Adw.PreferencesGroup(title=_("Datenbank-Status"))
        self._status_group.set_header_suffix(
            HelpButton(_("Anzahl der gespeicherten Ziehungen pro Wochentag."))
        )
        content.append(self._status_group)

        # Dynamische Zeilen für Ziehungstage
        self._draw_rows: dict[str, Adw.ActionRow] = {}
        self._count_rows: dict[str, Adw.ActionRow] = {}
        self._build_day_rows()

        # ── Server & System Status ──
        self._build_server_status_section(content)

        # ── Strategie-Performance ──
        self._perf_group = Adw.PreferencesGroup(
            title=_("Strategie-Performance"),
            description=_("Durchschnittliche Treffer pro Strategie"),
        )
        self._perf_group.set_header_suffix(
            HelpButton(_("Zeigt die durchschnittliche Trefferanzahl und Gewinnrate jeder Generierungs-Strategie."))
        )
        content.append(self._perf_group)

        self._perf_chart = ChartView(figsize=(8, 3))
        self._perf_group.add(self._perf_chart)

        self._perf_summary_row = Adw.ActionRow(
            title=_("Beste Strategie"),
            subtitle=_("Wird geladen..."),
        )
        self._perf_summary_row.add_prefix(
            Gtk.Image.new_from_icon_name("trophy-symbolic")
        )
        self._perf_group.add(self._perf_summary_row)

        # Kaufempfehlungen — pro Tag getrennte Gruppen
        rec_header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        rec_label = Gtk.Label(label=_("Kaufempfehlungen"))
        rec_label.add_css_class("title-3")
        rec_label.set_halign(Gtk.Align.START)
        rec_label.set_hexpand(True)
        rec_header_box.append(rec_label)
        rec_header_box.append(
            HelpButton(_("Automatisch berechnete Tipp-Empfehlungen basierend auf Strategie-Scores. Hoehere Scores = bessere historische Trefferquote."))
        )
        content.append(rec_header_box)

        self._rec_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.append(self._rec_container)
        self._rec_day_groups: list[Gtk.Widget] = []

        # Aktualisieren-Button
        btn_box = Gtk.Box(halign=Gtk.Align.CENTER, spacing=8)
        btn_box.set_margin_top(12)
        refresh_btn = Gtk.Button(label=_("Jetzt aktualisieren"))
        refresh_btn.set_tooltip_text(_("Dashboard-Daten vom Server neu laden"))
        refresh_btn.add_css_class("suggested-action")
        refresh_btn.add_css_class("pill")
        refresh_btn.connect("clicked", self._on_refresh)
        btn_box.append(refresh_btn)
        btn_box.append(
            HelpButton(_("Laedt alle Dashboard-Daten neu vom Server bzw. aus der Datenbank."))
        )
        content.append(btn_box)

        # AI-Panel
        self._ai_panel = AIPanel(
            ai_analyst=self._ai_analyst, api_client=self.api_client,
            title=_("AI-Analyse"), config_manager=self.config_manager,
            db=self.db, page="dashboard", app_db=self.app_db,
        )
        content.append(self._ai_panel)

        # Daten laden
        self._load_data()

