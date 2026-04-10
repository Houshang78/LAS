"""Schein-Prüfung: Zahlen eingeben, Gewinnklasse berechnen."""

from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.config import ConfigManager
from lotto_common.i18n import _
from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config
from lotto_common.models.ticket import LottoTicket
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from lotto_analyzer.ui.widgets.help_button import HelpButton
from lotto_analyzer.ui.widgets.number_ball import NumberBallRow
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config

logger = get_logger("checker_page")


from lotto_analyzer.ui.pages.checker_pkg.part1 import Part1Mixin
from lotto_analyzer.ui.pages.checker_pkg.part2 import Part2Mixin
from lotto_analyzer.ui.pages.checker_pkg.part3 import Part3Mixin


class CheckerPage(Part1Mixin, Part2Mixin, Part3Mixin, BasePage):
    """Lotto-Schein prüfen: Treffer + Gewinnklasse."""

    _TIP_COSTS = {"lotto6aus49": 1.20, "eurojackpot": 2.00}
    _PREDICTION_PAGE_SIZE = 200
