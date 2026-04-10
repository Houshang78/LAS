"""Ziehungstag-Auswahl Widget."""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject
from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config

# DrawDay-Wert -> deutscher Anzeigename
_DAY_LABELS = {
    "saturday": "Samstag",
    "wednesday": "Mittwoch",
    "tuesday": "Dienstag",
    "friday": "Freitag",
    "both": "Beide",
}


class DaySelector(Gtk.Box):
    __gsignals__ = {"day-changed": (GObject.SignalFlags.RUN_LAST, None, (str,))}

    def __init__(self, show_both=True):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add_css_class("linked")
        self._buttons = {}
        self._current = "saturday"
        self._show_both = show_both
        self._game_type = GameType.LOTTO6AUS49
        self._build_buttons()

    def _build_buttons(self) -> None:
        """Buttons (neu) aufbauen basierend auf aktuellem Spieltyp."""
        # Alte Buttons entfernen
        for btn in list(self._buttons.values()):
            self.remove(btn)
        self._buttons.clear()

        config = get_config(self._game_type)
        items = [(day, _DAY_LABELS.get(day, day)) for day in config.draw_days]
        if self._show_both:
            items.append(("both", "Beide"))

        _full_names = {
            "saturday": "Samstag", "wednesday": "Mittwoch",
            "tuesday": "Dienstag", "friday": "Freitag",
            "both": "Beide Ziehungstage anzeigen",
        }
        for day_id, label in items:
            btn = Gtk.ToggleButton(label=label)
            btn.set_tooltip_text(_full_names.get(day_id, label))
            btn.connect("toggled", self._on_toggled, day_id)
            self._buttons[day_id] = btn
            self.append(btn)

        # Default: ersten Ziehungstag auswählen
        first_day = config.draw_days[0] if config.draw_days else "saturday"
        self._current = first_day
        if first_day in self._buttons:
            self._buttons[first_day].set_active(True)

    def set_game_type(self, game_type: GameType) -> None:
        """Spieltyp wechseln — Buttons neu aufbauen."""
        if game_type == self._game_type:
            return
        self._game_type = game_type
        self._build_buttons()

    @property
    def selected_day(self):
        return self._current

    def get_draw_day(self):
        if self._current == "both":
            return None
        return DrawDay(self._current)

    def _on_toggled(self, button, day_id):
        if button.get_active():
            self._current = day_id
            for did, btn in self._buttons.items():
                if did != day_id:
                    btn.set_active(False)
            self.emit("day-changed", day_id)

    def set_day(self, day_id):
        if day_id in self._buttons:
            self._buttons[day_id].set_active(True)
