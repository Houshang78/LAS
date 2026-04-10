"""Crawler-Seite: Daten crawlen, manuell eingeben, AI-Verifikation."""

from __future__ import annotations

import sqlite3
import threading
from collections import Counter
from datetime import date, datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.config import ConfigManager
from lotto_common.models.draw import DrawDay, LottoDraw
from lotto_common.models.game_config import GameType, get_config
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_analyzer.ui.widgets.draw_input import DrawInput
from lotto_common.i18n import _
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from lotto_analyzer.ui.widgets.help_button import HelpButton
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config

logger = get_logger("scraper_page")

DAY_LABELS = {
    "saturday": _("Samstag"),
    "wednesday": _("Mittwoch"),
    "tuesday": _("Dienstag"),
    "friday": _("Freitag"),
}


from lotto_analyzer.ui.pages.scraper.part1 import Part1Mixin
from lotto_analyzer.ui.pages.scraper.part2 import Part2Mixin
from lotto_analyzer.ui.pages.scraper.part3 import Part3Mixin
from lotto_analyzer.ui.pages.scraper.part4 import CrawlMonitorMixin


class ScraperPage(Part1Mixin, Part2Mixin, Part3Mixin, CrawlMonitorMixin, BasePage):
    """Web-Crawler Steuerung, CSV-Import und AI-Datenverifikation."""

    POLL_INTERVAL = 30      # Fallback-Polling (WS pushes instant updates)
    MAX_POLLS = 10          # Max Polls (~5 Minuten bei 30s)

    def __init__(self, config_manager: ConfigManager, db: Database | None, app_mode: str, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager=config_manager, db=db, app_mode=app_mode, api_client=api_client,
                         app_db=app_db, backtest_db=backtest_db)
        self._crawling = False
        self._ai_analyst = None
        self._game_type: GameType = GameType.LOTTO6AUS49
        self._config = get_config(self._game_type)
        # Letzte Crawl/Import-Daten für Verifikation merken
        self._last_source_draws: list[LottoDraw] = []
        self._last_source_label: str = ""

        self._init_ai()
        self._build_ui()

    def cleanup(self) -> None:
        """Timer und WS-Listener aufräumen."""
        super().cleanup()
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("task_update", self._on_ws_crawl_task)
        except Exception:
            pass
        self._cleanup_crawl_monitor()

    def _init_ai(self) -> None:
        """AI-Analyst initialisieren — im Client-Modus via Server."""
        # Standalone-AI entfernt: AI läuft immer auf dem Server
        pass

