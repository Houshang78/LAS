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
        """Dashboard-Daten via API laden.

        D2: Architektur-Sauberkeit — der Client greift NICHT mehr direkt
        auf die DB zu. Wenn kein api_client da ist (Verbindung nicht
        aufgebaut), Platzhalter anzeigen statt local-DB-Fallback.
        """
        if self.api_client:
            self._load_server_status()
            self._load_data_api()
            self._load_integrity_api()
            self._load_recommendations_api()
        else:
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

    # D2: _load_data_db entfernt — Direct-DB-Access verstößt gegen das
    # UI-only-Architekturprinzip. Funktion durch _load_data_api ersetzt,
    # die nur HTTP-API spricht.

    def _load_data_api(self) -> None:
        """Dashboard-Daten via API-Client vom Server laden.

        D2: Nutzt jetzt /draws/count/{day} statt /stats/db + Table-
        Mapping. Server kapselt Tabellennamen (Lotto vs EJ), Client
        kennt nur die DrawDay-Strings.
        """
        def worker():
            try:
                latest_per_day: dict = {}
                count_per_day: dict = {}
                for day_str in self._config.draw_days:
                    try:
                        latest = self.api_client.get_latest_draw(day_str)
                        if latest is not None and not isinstance(latest, dict):
                            logger.warning("get_latest_draw(%s): unerwarteter Typ %s", day_str, type(latest))
                            latest = None
                        latest_per_day[day_str] = latest
                    except Exception as e:
                        logger.warning(f"Letzte Ziehung laden fehlgeschlagen ({day_str}): {e}")
                        latest_per_day[day_str] = None
                    try:
                        count_per_day[day_str] = self.api_client.get_draw_count(day_str)
                    except Exception as e:
                        logger.warning(f"Draw-Count laden fehlgeschlagen ({day_str}): {e}")
                        count_per_day[day_str] = 0
                GLib.idle_add(self._on_api_data_loaded, latest_per_day, count_per_day)
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning(f"API-Daten laden fehlgeschlagen: {e}")
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler beim API-Daten laden: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_api_data_loaded(self, results: dict, count_per_day: dict) -> bool:
        """API-Daten im Main-Thread anzeigen."""
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

        # Counts pro Tag (D2: /draws/count statt /stats/db + Table-Mapping)
        for day_str, cnt in count_per_day.items():
            cr = self._count_rows.get(day_str)
            if cr:
                cr.set_subtitle(str(cnt))
        return False

    def _load_integrity_db(self) -> None:
        """DB-Integrität prüfen (Standalone-Modus)."""
        logger.warning("DB-Integritätsprüfung nur via API verfügbar (core-Import entfernt)")
        self._integrity_row.set_subtitle(_("Nur im Server-Modus verfügbar"))

