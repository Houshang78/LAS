"""Jahresbereich-Slider Widget."""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject

class YearRangeSelector(Gtk.Box):
    __gsignals__ = {"range-changed": (GObject.SignalFlags.RUN_LAST, None, (int, int))}
    def __init__(self, min_year=1955, max_year=2026):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._min = min_year
        self._max = max_year
        label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._from_label = Gtk.Label(label=f"Von: {min_year}")
        self._from_label.set_halign(Gtk.Align.START)
        self._to_label = Gtk.Label(label=f"Bis: {max_year}")
        self._to_label.set_halign(Gtk.Align.END)
        self._to_label.set_hexpand(True)
        label_box.append(self._from_label)
        label_box.append(self._to_label)
        self.append(label_box)
        self._from_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, min_year, max_year, 1)
        self._from_scale.set_value(min_year)
        self._from_scale.set_draw_value(False)
        self._from_scale.connect("value-changed", self._on_from_changed)
        self.append(self._from_scale)
        self._to_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, min_year, max_year, 1)
        self._to_scale.set_value(max_year)
        self._to_scale.set_draw_value(False)
        self._to_scale.connect("value-changed", self._on_to_changed)
        self.append(self._to_scale)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_halign(Gtk.Align.CENTER)
        _tooltips = {"5J": "Letzte 5 Jahre anzeigen", "10J": "Letzte 10 Jahre anzeigen",
                     "20J": "Letzte 20 Jahre anzeigen", "Alle": "Alle Jahre anzeigen"}
        for label, years in [("5J", 5), ("10J", 10), ("20J", 20), ("Alle", None)]:
            btn = Gtk.Button(label=label)
            btn.set_tooltip_text(_tooltips[label])
            btn.add_css_class("flat")
            btn.connect("clicked", self._on_quick, years)
            btn_box.append(btn)
        self.append(btn_box)
    @property
    def year_from(self): return int(self._from_scale.get_value())
    @property
    def year_to(self): return int(self._to_scale.get_value())
    def _on_from_changed(self, scale):
        val = int(scale.get_value())
        if val > self.year_to:
            scale.set_value(self.year_to); return
        self._from_label.set_label(f"Von: {val}")
        self.emit("range-changed", self.year_from, self.year_to)
    def _on_to_changed(self, scale):
        val = int(scale.get_value())
        if val < self.year_from:
            scale.set_value(self.year_from); return
        self._to_label.set_label(f"Bis: {val}")
        self.emit("range-changed", self.year_from, self.year_to)
    def _on_quick(self, button, years):
        if years is None:
            self._from_scale.set_value(self._min)
            self._to_scale.set_value(self._max)
        else:
            self._to_scale.set_value(self._max)
            self._from_scale.set_value(max(self._min, self._max - years))
    def set_range(self, year_from, year_to):
        self._from_scale.set_value(year_from)
        self._to_scale.set_value(year_to)
