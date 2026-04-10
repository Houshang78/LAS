"""UI-Seite dashboard: part2."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("dashboard.part2")



from lotto_analyzer.ui.pages.dashboard.part2_1 import Part2Mixin1
from lotto_analyzer.ui.pages.dashboard.part2_2 import Part2Mixin2


class Part2Mixin(Part2Mixin1, Part2Mixin2):
    """Part2Mixin — kombiniert aus 2 Teilen."""
    pass
