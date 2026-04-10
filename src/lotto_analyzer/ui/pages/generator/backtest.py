"""Generator-Seite: Backtest Mixin."""

import threading
from datetime import date, datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
try:
    from lotto_analyzer.ui.widgets.chart_view import ChartView
except ImportError:
    ChartView = None
from lotto_common.models.analysis import PredictionRecord

logger = get_logger("generator.backtest")



try:
    from lotto_analyzer.ui.pages.generator.page import STRATEGY_COLORS, _apply_css
except ImportError:
    STRATEGY_COLORS = {}
    def _apply_css(w, c): pass

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



from lotto_analyzer.ui.pages.generator.backtest_1 import BacktestMixin1
from lotto_analyzer.ui.pages.generator.backtest_2 import BacktestMixin2


class BacktestMixin(BacktestMixin1, BacktestMixin2):
    """BacktestMixin — kombiniert aus 2 Teilen."""
    pass
