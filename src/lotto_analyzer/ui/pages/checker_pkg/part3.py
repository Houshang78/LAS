"""Checker Teil 3."""

import threading
from gi.repository import Gtk, Adw, GLib
from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
import time

logger = get_logger("checker.part3")


class Part3Mixin:
    pass

    def _on_pred_tab_changed(self, btn) -> None:
        """Tab gewechselt → gegenueberliegenden Button deaktivieren + Datum-Liste neu laden."""
        if not btn.get_active():
            return
        # Gegenseitiges Ausschliessen
        if btn is self._pred_tab_mine:
            self._pred_tab_all.set_active(False)
        else:
            self._pred_tab_mine.set_active(False)
        # Datum-Liste neu laden
        self._on_pred_day_changed(self._pred_day_combo)

    def _is_mine_tab(self) -> bool:
        """Ist der 'Meine Tipps' Tab aktiv?"""
        return self._pred_tab_mine.get_active()

    def _on_pred_day_changed(self, combo) -> None:
        """Ziehtag gewechselt → Datum-Liste für Predictions laden."""
        draw_day = combo.get_active_text()
        if not draw_day:
            return
        mine = self._is_mine_tab()

        def _fetch():
            try:
                if mine:
                    weeks = self.config_manager.config.auto_generation.purchased_visible_weeks
                    if self.app_mode == "client" and self.api_client:
                        dates = self.api_client.get_purchased_dates(draw_day)
                    elif self.db:
                        dates = self.db.get_purchased_dates_within(draw_day, weeks)
                    else:
                        dates = []
                else:
                    if self.app_mode == "client" and self.api_client:
                        dates = self.api_client.get_prediction_dates(draw_day)
                    elif self.db:
                        dates = self.db.get_prediction_dates(draw_day)
                    else:
                        dates = []
            except Exception as e:
                logger.error(f"Prediction-Daten laden: {e}")
                dates = []
            GLib.idle_add(self._populate_pred_dates, dates)

        threading.Thread(target=_fetch, daemon=True).start()

    def _populate_pred_dates(self, dates: list[str]) -> None:
        """Datum-ComboBox mit Werten fuellen."""
        self._pred_date_combo.remove_all()
        for d in dates:
            self._pred_date_combo.append_text(d)
        if dates:
            self._pred_date_combo.set_active(0)

    def _on_load_predictions(self, btn) -> None:
        """Predictions für gewählten Ziehtag + Datum laden (gekauft oder alle)."""
        draw_day = self._pred_day_combo.get_active_text()
        draw_date = self._pred_date_combo.get_active_text()
        if not draw_day or not draw_date:
            self._pred_status.set_text(_("Bitte Ziehtag und Datum wählen."))
            return

        self._pred_load_btn.set_sensitive(False)
        mine = self._is_mine_tab()
        label = _("Lade meine Tipps...") if mine else _("Lade Vorhersagen...")
        self._pred_status.set_text(label)

        def _fetch():
            try:
                if mine:
                    if self.app_mode == "client" and self.api_client:
                        data = self.api_client.get_purchased_predictions(
                            draw_day, draw_date,
                        )
                        items = data.get("predictions", [])
                    elif self.db:
                        items = self.db.get_purchased_predictions(
                            draw_day, draw_date,
                        )
                    else:
                        items = []
                else:
                    if self.app_mode == "client" and self.api_client:
                        data = self.api_client.get_predictions(
                            draw_day, draw_date, 0, self._PREDICTION_PAGE_SIZE,
                        )
                        items = data.get("predictions", [])
                    elif self.db:
                        items = self.db.get_predictions_paginated(
                            draw_day, draw_date, 0, self._PREDICTION_PAGE_SIZE,
                        )
                    else:
                        items = []
            except Exception as e:
                logger.error(f"Predictions laden: {e}")
                items = []
            GLib.idle_add(self._on_predictions_loaded, items, draw_day, draw_date)

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_predictions_loaded(
        self, items: list[dict], draw_day: str, draw_date: str,
    ) -> None:
        """Prediction-ComboBox mit geladenen Vorhersagen fuellen."""
        self._pred_load_btn.set_sensitive(True)
        self._pred_items = items

        self._pred_select_combo.remove_all()
        if not items:
            self._pred_select_combo.append_text(_("— Keine Vorhersagen gefunden —"))
            self._pred_select_combo.set_active(0)
            self._pred_fill_btn.set_sensitive(False)
            self._pred_status.set_text(_("Keine Vorhersagen für dieses Datum."))
            return

        for i, pred in enumerate(items, start=1):
            nums = pred.get("predicted_numbers", "")
            if isinstance(nums, list):
                nums_str = " ".join(str(n) for n in nums)
            else:
                nums_str = str(nums).replace(",", " ")
            strategy = pred.get("strategy", "?")
            conf = pred.get("ml_confidence", 0)
            matches = pred.get("matches")
            label = f"#{i}: {nums_str} [{strategy}] ({conf:.0%})"
            if matches is not None and matches != "":
                label += f" | {matches} " + _("Treffer")
            self._pred_select_combo.append_text(label)

        self._pred_select_combo.set_active(0)
        self._pred_fill_btn.set_sensitive(True)
        self._pred_status.set_text(f"{len(items)} " + _("Vorhersagen geladen."))

    def _on_fill_prediction(self, btn) -> None:
        """Gewaehlte Vorhersage in die Schein-Felder eintragen."""
        idx = self._pred_select_combo.get_active()
        if idx < 0 or idx >= len(self._pred_items):
            return

        pred = self._pred_items[idx]

        # Zahlen parsen
        nums_raw = pred.get("predicted_numbers", "")
        if isinstance(nums_raw, list):
            numbers = sorted(int(n) for n in nums_raw)
        else:
            parts = str(nums_raw).replace(",", " ").split()
            numbers = sorted(int(p) for p in parts if p.strip().isdigit())

        # In SpinRows eintragen
        for i, spin in enumerate(self._number_entries):
            if i < len(numbers):
                spin.set_value(numbers[i])

        # Bonus-Zahlen eintragen (Superzahl / Eurozahlen)
        bonus_raw = pred.get("predicted_bonus")
        if bonus_raw is not None:
            if isinstance(bonus_raw, list):
                for i, spin in enumerate(self._bonus_entries):
                    if i < len(bonus_raw):
                        spin.set_value(int(bonus_raw[i]))
            elif isinstance(bonus_raw, (int, float)):
                if self._bonus_entries:
                    self._bonus_entries[0].set_value(int(bonus_raw))
            elif isinstance(bonus_raw, str) and bonus_raw.strip():
                parts = bonus_raw.replace(",", " ").split()
                for i, spin in enumerate(self._bonus_entries):
                    if i < len(parts) and parts[i].strip().isdigit():
                        spin.set_value(int(parts[i]))

        # Datum eintragen (draw_date ist ISO: YYYY-MM-DD)
        draw_date = pred.get("draw_date", "")
        if draw_date:
            try:
                dt = datetime.strptime(draw_date, "%Y-%m-%d")
                self._date_entry.set_text(dt.strftime("%d.%m.%Y"))
            except ValueError:
                pass

        # Ziehtag eintragen
        draw_day = pred.get("draw_day", "")
        if draw_day:
            draw_days = self._config.draw_days
            for di, d in enumerate(draw_days):
                if d == draw_day:
                    self._day_combo.set_selected(di)
                    break

        strategy = pred.get("strategy", "?")
        self._pred_status.set_text(
            _("Vorhersage") + f" #{idx + 1} ({strategy}) " + _("eingetragen. Klicke 'Schein prüfen'.")
        )
