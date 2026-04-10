"""UI-Seite security: part3 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("security.part3")



from lotto_analyzer.ui.pages.security.part3_1 import Part3Mixin1
from lotto_analyzer.ui.pages.security.part3_2 import Part3Mixin2
from lotto_analyzer.ui.pages.security.part3_3 import Part3Mixin3


class Part3Mixin(Part3Mixin1, Part3Mixin2, Part3Mixin3):
    """Part3Mixin — kombiniert aus 3 Teilen."""
    pass
