"""Bericht-Seite: Zyklus-Berichte lesen, filtern, per Telegram senden."""

from __future__ import annotations

import re
import sqlite3
import threading
import json
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio, Pango

from lotto_common.config import ConfigManager
from lotto_common.i18n import _
from lotto_common.models.game_config import GameType, get_config
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_analyzer.ui.widgets.number_ball import NumberBallRow
from lotto_analyzer.ui.ui_helpers import format_eur
from lotto_common.utils.logging_config import get_logger

logger = get_logger("reports_page")


# Draw-Day Labels
DAY_LABELS = {
    "saturday": _("Samstag"),
    "wednesday": _("Mittwoch"),
    "tuesday": _("Dienstag"),
    "friday": _("Freitag"),
}


from lotto_analyzer.ui.pages.reports.part1 import Part1Mixin
from lotto_analyzer.ui.pages.reports.part2 import Part2Mixin
from lotto_analyzer.ui.pages.reports.part3 import Part3Mixin
from lotto_analyzer.ui.pages.reports.part4 import Part4Mixin
from lotto_analyzer.ui.pages.reports.part5 import Part5Mixin


class ReportsPage(Part1Mixin, Part2Mixin, Part3Mixin, Part4Mixin, Part5Mixin, BasePage):
    """Zyklus-Berichte anzeigen und per Telegram versenden."""

    CACHE_TTL = 300  # 5 Minuten Cache-Gültigkeitsdauer

    def __init__(self, config_manager: ConfigManager, db: Database | None, app_mode: str, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager, db, app_mode, api_client, app_db=app_db, backtest_db=backtest_db)
        self._game_type: GameType = GameType.LOTTO6AUS49
        self._config = get_config(self._game_type)
        self._reports: list[dict] = []
        self._selected_report: dict | None = None
        self._loading = False
        # Cache für geladene Hits pro Kategorie — Einträge als (timestamp, data)
        self._hits_cache: dict[str, tuple[float, list[dict]]] = {}
        self._accuracy_cache: dict[str, tuple[float, dict]] = {}

        self._build_ui()

