"""UI-Seite dashboard: part1."""

from __future__ import annotations

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from lotto_analyzer.ui.widgets.chart_view import ChartView
from lotto_analyzer.ui.pages.dashboard.page import _DAY_NAMES
from lotto_common.config import ConfigManager
from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config


logger = get_logger("dashboard.part1")

from lotto_analyzer.ui.widgets.help_button import HelpButton

import sqlite3


class Part1Mixin:
    """Part1 Mixin."""

    def _build_day_rows(self) -> None:
        """Dynamische Zeilen für die Ziehungstage aufbauen."""
        # Alte Zeilen entfernen
        for row in self._draw_rows.values():
            self._draws_group.remove(row)
        for row in self._count_rows.values():
            self._status_group.remove(row)
        self._draw_rows.clear()
        self._count_rows.clear()

        # Neue Zeilen erstellen
        for day_str in self._config.draw_days:
            name = _DAY_NAMES.get(day_str, day_str)

            draw_row = Adw.ActionRow(title=name, subtitle=_("Laden..."))
            draw_row.add_prefix(Gtk.Image.new_from_icon_name("starred-symbolic"))
            self._draws_group.add(draw_row)
            self._draw_rows[day_str] = draw_row

            count_row = Adw.ActionRow(title=_("%s-Ziehungen") % name, subtitle="0")
            self._status_group.add(count_row)
            self._count_rows[day_str] = count_row

    def set_game_type(self, game_type: GameType) -> None:
        """Spieltyp wechseln — Dashboard-Daten neu laden."""
        self._game_type = game_type
        self._config = get_config(game_type)

        self._draws_group.set_description(self._config.display_name)
        self._build_day_rows()
        self._build_jackpot_rows()
        self._load_data()

    def set_api_client(self, client: "APIClient | None") -> None:
        """API-Client setzen."""
        super().set_api_client(client)
        self._ai_panel.api_client = client

    def refresh(self) -> None:
        """Dashboard-Daten nur neu laden wenn veraltet (>5min)."""
        if self.is_stale():
            self._load_data()

    def _load_data(self) -> None:
        """Dashboard-Daten aus DB oder via API laden."""
        if self.db:
            self._load_server_status()
            self._load_data_db()
            self._load_integrity_db()
            self._load_recommendations()
        elif self.api_client:
            self._load_server_status()
            self._load_data_api()
            self._load_integrity_api()
            self._load_recommendations_api()
        elif self.app_mode == "client":
            # Noch keine Verbindung — Platzhalter anzeigen
            for day_str in self._config.draw_days:
                row = self._draw_rows.get(day_str)
                if row:
                    row.set_subtitle(_("Warte auf Verbindung..."))
                cr = self._count_rows.get(day_str)
                if cr:
                    cr.set_subtitle("—")
            self._integrity_row.set_subtitle(_("Warte auf Verbindung..."))
            self._server_row.set_subtitle(_("Verbinde..."))
            self._telegram_row.set_subtitle("—")
            self._ml_quick_row.set_subtitle("—")
            self._tasks_row.set_subtitle("—")
            self._next_draw_row.set_subtitle("—")

    def _load_data_db(self) -> None:
        """Dashboard-Daten direkt aus der lokalen DB laden."""
        for day_str in self._config.draw_days:
            day = DrawDay(day_str)
            draw_row = self._draw_rows.get(day_str)
            count_row = self._count_rows.get(day_str)
            if not draw_row or not count_row:
                continue

            latest = self.db.get_latest_draw(day)
            count = self.db.get_draw_count(day)
            count_row.set_subtitle(str(count))
            if latest:
                nums = " - ".join(str(n) for n in latest.sorted_numbers)
                if latest.is_eurojackpot and latest.bonus_numbers:
                    ez = " - ".join(str(n) for n in sorted(latest.bonus_numbers))
                    bonus_str = f"  EZ: {ez}"
                elif latest.super_number is not None:
                    bonus_str = f"  SZ: {latest.super_number}"
                else:
                    bonus_str = ""
                draw_row.set_subtitle(f"{latest.draw_date}: {nums}{bonus_str}")
            else:
                draw_row.set_subtitle(_("Keine Daten"))

    def _load_data_api(self) -> None:
        """Dashboard-Daten via API-Client vom Server laden."""
        def worker():
            try:
                results = {}
                for day_str in self._config.draw_days:
                    try:
                        latest = self.api_client.get_latest_draw(day_str)
                        if not isinstance(latest, dict):
                            logger.warning("get_latest_draw(%s): unerwarteter Typ %s", day_str, type(latest))
                            latest = None
                        results[day_str] = latest
                    except Exception as e:
                        logger.warning(f"Letzte Ziehung laden fehlgeschlagen ({day_str}): {e}")
                        results[day_str] = None
                db_stats = {}
                try:
                    db_stats = self.api_client.get_db_stats()
                    if not isinstance(db_stats, dict):
                        logger.warning("get_db_stats: unerwarteter Typ %s", type(db_stats))
                        db_stats = {}
                except Exception as e:
                    logger.warning(f"DB-Stats laden fehlgeschlagen: {e}")
                GLib.idle_add(self._on_api_data_loaded, results, db_stats)
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning(f"API-Daten laden fehlgeschlagen: {e}")
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler beim API-Daten laden: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_api_data_loaded(self, results: dict, db_stats: dict) -> bool:
        """API-Daten im Main-Thread anzeigen."""
        # Mapping: draw_day -> DB-Tabellenname für Counts
        _day_to_table = {
            "saturday": "draws_saturday",
            "wednesday": "draws_wednesday",
            "tuesday": "ej_draws_tuesday",
            "friday": "ej_draws_friday",
        }

        for day_str, data in results.items():
            draw_row = self._draw_rows.get(day_str)
            if not draw_row:
                continue
            if data:
                nums = " - ".join(str(n) for n in data.get("numbers", []))
                bonus = data.get("bonus_numbers", [])
                sz = data.get("super_number")
                if bonus:
                    ez = " - ".join(str(n) for n in bonus)
                    bonus_str = f"  EZ: {ez}"
                elif sz is not None:
                    bonus_str = f"  SZ: {sz}"
                else:
                    bonus_str = ""
                draw_row.set_subtitle(f"{data.get('draw_date', '?')}: {nums}{bonus_str}")
            else:
                draw_row.set_subtitle(_("Keine Daten"))

        # DB-Stats anzeigen (Zaehlungen)
        if db_stats:
            for day_str in self._config.draw_days:
                cr = self._count_rows.get(day_str)
                if cr:
                    table_key = _day_to_table.get(day_str, "")
                    count = db_stats.get(table_key, 0)
                    cr.set_subtitle(str(count))
        return False

    def _load_integrity_db(self) -> None:
        """DB-Integrität prüfen (Standalone-Modus)."""
        logger.warning("DB-Integritätsprüfung nur via API verfügbar (core-Import entfernt)")
        self._integrity_row.set_subtitle(_("Nur im Server-Modus verfügbar"))

