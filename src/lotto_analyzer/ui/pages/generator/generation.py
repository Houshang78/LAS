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



from lotto_analyzer.ui.pages.generator.generation_1 import GenerationMixin1
from lotto_analyzer.ui.pages.generator.generation_2 import GenerationMixin2
from lotto_analyzer.ui.pages.generator.generation_3 import GenerationMixin3
from lotto_analyzer.ui.pages.generator.generation_4 import MassGenMixin


class GenerationMixin(GenerationMixin1, GenerationMixin2, GenerationMixin3, MassGenMixin):
    """GenerationMixin — kombiniert aus 4 Teilen (inkl. Mass-Gen)."""
    pass
