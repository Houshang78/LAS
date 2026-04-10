"""Manuelle Ziehungseingabe Widget."""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject
from datetime import date, datetime
from lotto_common.models.draw import DrawDay, LottoDraw
from lotto_common.models.game_config import GameType, get_config
from lotto_common.utils.validators import validate_numbers, validate_super_number, validate_bonus

_DAY_LABELS = {"saturday": "Samstag", "wednesday": "Mittwoch", "tuesday": "Dienstag", "friday": "Freitag"}

class DrawInput(Gtk.Box):
    __gsignals__ = {"draw-submitted": (GObject.SignalFlags.RUN_LAST, None, ())}
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self._game_type = GameType.LOTTO6AUS49
        self._config = get_config(self._game_type)
        title = Gtk.Label(label="Neue Ziehung eintragen")
        title.add_css_class("heading")
        self.append(title)
        date_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        date_box.append(Gtk.Label(label="Datum:"))
        self._date_entry = Gtk.Entry()
        self._date_entry.set_text(date.today().strftime("%d.%m.%Y"))
        self._date_entry.set_max_width_chars(12)
        date_box.append(self._date_entry)
        self.append(date_box)
        day_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        day_box.append(Gtk.Label(label="Tag:"))
        self._day_dropdown = Gtk.DropDown()
        self._day_model = Gtk.StringList()
        for d in self._config.draw_days:
            self._day_model.append(_DAY_LABELS.get(d, d))
        self._day_dropdown.set_model(self._day_model)
        self._auto_select_day()
        day_box.append(self._day_dropdown)
        self.append(day_box)

        # Hauptzahlen
        self._nums_label = Gtk.Label(
            label=f"{self._config.main_count} Zahlen ({self._config.main_min}-{self._config.main_max}):",
            halign=Gtk.Align.START,
        )
        self.append(self._nums_label)
        self._nums_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._number_spins = []
        for i in range(self._config.main_count):
            spin = Gtk.SpinButton.new_with_range(self._config.main_min, self._config.main_max, 1)
            spin.set_value(self._config.main_min + i * 8)
            self._number_spins.append(spin)
            self._nums_box.append(spin)
        self.append(self._nums_box)

        # Bonus (Superzahl oder Eurozahlen)
        self._bonus_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._bonus_label = Gtk.Label(label=f"{self._config.bonus_name} ({self._config.bonus_min}-{self._config.bonus_max}):")
        self._bonus_box.append(self._bonus_label)
        self._bonus_spins = []
        for i in range(self._config.bonus_count):
            spin = Gtk.SpinButton.new_with_range(self._config.bonus_min, self._config.bonus_max, 1)
            self._bonus_spins.append(spin)
            self._bonus_box.append(spin)
        self.append(self._bonus_box)

        btn_box = Gtk.Box(halign=Gtk.Align.CENTER)
        self._submit_btn = Gtk.Button(label="Speichern")
        self._submit_btn.set_tooltip_text("Manuell eingegebene Ziehung speichern")
        self._submit_btn.add_css_class("suggested-action")
        self._submit_btn.connect("clicked", self._on_submit)
        btn_box.append(self._submit_btn)
        self.append(btn_box)
        self._status = Gtk.Label(label="")
        self._status.add_css_class("dim-label")
        self.append(self._status)
        self._last_draw = None

    def _auto_select_day(self) -> None:
        """Wochentag-Dropdown automatisch auf heutigen Tag setzen."""
        weekday = date.today().weekday()  # 0=Mo, 1=Di, 2=Mi, 3=Do, 4=Fr, 5=Sa, 6=So
        day_map = {
            "saturday": 5, "wednesday": 2,
            "tuesday": 1, "friday": 4,
        }
        for idx, d in enumerate(self._config.draw_days):
            if day_map.get(d) == weekday:
                self._day_dropdown.set_selected(idx)
                return

    def set_game_type(self, game_type: GameType) -> None:
        """Spieltyp wechseln — Eingabefelder anpassen."""
        self._game_type = game_type
        self._config = get_config(game_type)

        # Tag-Dropdown aktualisieren
        model = Gtk.StringList()
        for d in self._config.draw_days:
            model.append(_DAY_LABELS.get(d, d))
        self._day_dropdown.set_model(model)
        self._auto_select_day()

        # Hauptzahlen-Label
        self._nums_label.set_label(
            f"{self._config.main_count} Zahlen ({self._config.main_min}-{self._config.main_max}):"
        )

        # Hauptzahlen-Spins anpassen
        current = len(self._number_spins)
        needed = self._config.main_count
        if current > needed:
            for spin in self._number_spins[needed:]:
                self._nums_box.remove(spin)
            self._number_spins = self._number_spins[:needed]
        elif current < needed:
            for i in range(current, needed):
                spin = Gtk.SpinButton.new_with_range(self._config.main_min, self._config.main_max, 1)
                spin.set_value(self._config.main_min + i * 8)
                self._number_spins.append(spin)
                self._nums_box.append(spin)
        for spin in self._number_spins:
            adj = spin.get_adjustment()
            adj.set_lower(self._config.main_min)
            adj.set_upper(self._config.main_max)

        # Bonus-Label + Spins anpassen
        self._bonus_label.set_label(
            f"{self._config.bonus_name} ({self._config.bonus_min}-{self._config.bonus_max}):"
        )
        current_bonus = len(self._bonus_spins)
        needed_bonus = self._config.bonus_count
        if current_bonus > needed_bonus:
            for spin in self._bonus_spins[needed_bonus:]:
                self._bonus_box.remove(spin)
            self._bonus_spins = self._bonus_spins[:needed_bonus]
        elif current_bonus < needed_bonus:
            for _ in range(current_bonus, needed_bonus):
                spin = Gtk.SpinButton.new_with_range(self._config.bonus_min, self._config.bonus_max, 1)
                self._bonus_spins.append(spin)
                self._bonus_box.append(spin)
        for spin in self._bonus_spins:
            adj = spin.get_adjustment()
            adj.set_lower(self._config.bonus_min)
            adj.set_upper(self._config.bonus_max)
            adj.set_value(self._config.bonus_min)

    def get_draw(self): return self._last_draw

    def _on_submit(self, button):
        numbers = [int(spin.get_value()) for spin in self._number_spins]
        valid, msg = validate_numbers(numbers, self._config)
        if not valid: self._status.set_label(f"Fehler: {msg}"); return

        try:
            draw_date = datetime.strptime(self._date_entry.get_text().strip(), "%d.%m.%Y").date()
        except ValueError:
            self._status.set_label("Fehler: Datum TT.MM.JJJJ"); return

        day_idx = self._day_dropdown.get_selected()
        draw_days = self._config.draw_days
        if day_idx < 0 or day_idx >= len(draw_days):
            self._status.set_label("Fehler: Kein gültiger Tag ausgewählt")
            return
        draw_day = DrawDay(draw_days[day_idx])

        if self._config.bonus_count > 1:
            # EuroJackpot: Eurozahlen
            bonus = [int(spin.get_value()) for spin in self._bonus_spins]
            valid_b, msg_b = validate_bonus(bonus, self._config)
            if not valid_b: self._status.set_label(f"Fehler: {msg_b}"); return
            self._last_draw = LottoDraw(
                draw_date=draw_date, draw_day=draw_day,
                numbers=sorted(numbers), bonus_numbers=sorted(bonus),
                source="manual",
            )
        else:
            # 6aus49: Superzahl
            sz = int(self._bonus_spins[0].get_value())
            valid_sz, msg_sz = validate_super_number(sz, self._config)
            if not valid_sz: self._status.set_label(f"Fehler: {msg_sz}"); return
            self._last_draw = LottoDraw(
                draw_date=draw_date, draw_day=draw_day,
                numbers=sorted(numbers), super_number=sz,
                source="manual",
            )

        self._status.set_label(f"OK: {self._last_draw}")
        self.emit("draw-submitted")
