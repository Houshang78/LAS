"""Wiederverwendbarer (?)-Button mit Popover-Erklärung."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw


class HelpButton(Gtk.MenuButton):
    """Kleiner (?)-Button der beim Klick einen Popover mit Erklärungstext zeigt."""

    def __init__(self, text: str):
        super().__init__()
        self.set_icon_name("dialog-information-symbolic")
        self.add_css_class("flat")
        self.add_css_class("circular")
        self.set_valign(Gtk.Align.CENTER)
        self.set_tooltip_text("Hilfe")

        # Popover mit Label
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        label = Gtk.Label(label=text)
        label.set_wrap(True)
        label.set_max_width_chars(40)
        label.set_xalign(0)
        box.append(label)

        popover.set_child(box)
        self.set_popover(popover)
