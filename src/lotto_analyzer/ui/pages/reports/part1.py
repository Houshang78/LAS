"""UI-Seite reports: part1 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("reports.part1")



from lotto_analyzer.ui.pages.reports.part1_1 import Part1Mixin1
from lotto_analyzer.ui.pages.reports.part1_2 import Part1Mixin2


class Part1Mixin(Part1Mixin1, Part1Mixin2):
    """Part1Mixin — kombiniert aus 2 Teilen."""
    pass
