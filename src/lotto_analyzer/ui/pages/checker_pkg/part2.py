"""Checker Teil 2."""

from __future__ import annotations

import threading
from gi.repository import Gtk, Adw, GLib
from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
import time
from lotto_common.config import ConfigManager
from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config


logger = get_logger("checker.part2")
from lotto_common.models.ticket import LottoTicket

import sqlite3


class Part2Mixin:
    pass

    def _lookup_prize_amount(self, draw_day: str, draw_date_iso: str, prize_class: int | None) -> None:
        """Gewinnquoten asynchron laden und anzeigen."""
        if not prize_class:
            self._prize_amount_row.set_subtitle(_("Kein Gewinn"))
            return

        # Einsatz pro Tipp (aus Spieltyp-Konfiguration)
        is_ej = draw_day in ("tuesday", "friday")
        game_type_val = "eurojackpot" if is_ej else "lotto6aus49"
        tip_cost = self._TIP_COSTS.get(game_type_val, 1.20)

        def _fetch():
            try:
                if self.api_client and not self.db:
                    data = self.api_client.get_draw_prizes(draw_day, draw_date_iso)
                    prizes = data.get("prizes", [])
                elif self.db:
                    prizes = self.db.get_draw_prizes(draw_day, draw_date_iso)
                else:
                    prizes = []
            except Exception as e:
                logger.error(f"Gewinnquoten laden: {e}")
                prizes = []
            GLib.idle_add(self._on_prizes_loaded, prizes, prize_class, tip_cost)

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_prizes_loaded(self, prizes: list[dict], prize_class: int, tip_cost: float) -> bool:
        """Gewinnquoten-Ergebnis anzeigen (Main-Thread)."""
        if not prizes:
            self._prize_amount_row.set_subtitle(
                _("Gewinnquoten nicht verfügbar") + f" | {_('Einsatz')}: {tip_cost:.2f} EUR {_('pro Tipp')}"
            )
            return False

        # Passende Gewinnklasse finden
        matched = None
        for p in prizes:
            if p.get("class_number") == prize_class:
                matched = p
                break

        if not matched:
            self._prize_amount_row.set_subtitle(
                _("Gewinnklasse") + f" {prize_class} " + _("nicht in Quoten gefunden") + f" | {_('Einsatz')}: {tip_cost:.2f} EUR {_('pro Tipp')}"
            )
            return False

        amount = matched.get("prize_amount", 0)
        winners = matched.get("winner_count", 0)
        desc = matched.get("description", "")

        if amount:
            amount_str = f"{amount:,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")
            profit = amount - tip_cost
            profit_str = f"{profit:,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")
            subtitle = _("Gewinnklasse") + f" {prize_class}: {amount_str}"
            if winners is not None:
                subtitle += f" ({winners:,} " + _("Gewinner") + ")".replace(",", ".")
            subtitle += f" | {_('Einsatz')}: {tip_cost:.2f} EUR → {_('Gewinn')}: {profit_str}"
        else:
            subtitle = _("Gewinnklasse") + f" {prize_class}: " + _("Betrag nicht verfügbar") + f" | {_('Einsatz')}: {tip_cost:.2f} EUR {_('pro Tipp')}"

        self._prize_amount_row.set_subtitle(subtitle)
        return False

    def _on_check(self, button: Gtk.Button) -> None:
        """Schein prüfen."""
        with self._op_lock:
            if self._checking:
                return
            self._checking = True

        if not self.db and not self.api_client:
            with self._op_lock:
                self._checking = False
            return

        # Zahlen lesen und validieren
        numbers = [int(spin.get_value()) for spin in self._number_entries]
        bonus_numbers = [int(spin.get_value()) for spin in self._bonus_entries]

        # Duplikate prüfen
        if len(set(numbers)) != self._config.main_count:
            self._result_row.set_title(_("Fehler"))
            self._result_row.set_subtitle(_("Doppelte Zahlen eingegeben!"))
            with self._op_lock:
                self._checking = False
            return

        # Datum parsen
        date_text = self._date_entry.get_text().strip()
        try:
            draw_date = datetime.strptime(date_text, "%d.%m.%Y").date()
        except ValueError:
            self._result_row.set_title(_("Fehler"))
            self._result_row.set_subtitle(_("Ungültiges Datum (TT.MM.JJJJ erwartet)"))
            with self._op_lock:
                self._checking = False
            return

        day_idx = self._day_combo.get_selected()
        draw_days = self._config.draw_days
        if day_idx < len(draw_days):
            draw_day = DrawDay(draw_days[day_idx])
        else:
            draw_day = DrawDay(draw_days[0])

        # Ticket erstellen
        is_ej = draw_day in (DrawDay.TUESDAY, DrawDay.FRIDAY)
        try:
            if is_ej:
                ticket = LottoTicket(
                    numbers=sorted(numbers),
                    bonus_numbers=sorted(bonus_numbers),
                    draw_date=draw_date,
                    draw_day=draw_day,
                )
            else:
                ticket = LottoTicket(
                    numbers=sorted(numbers),
                    super_number=bonus_numbers[0] if bonus_numbers else 0,
                    draw_date=draw_date,
                    draw_day=draw_day,
                )
        except ValueError as e:
            self._result_row.set_title(_("Fehler"))
            self._result_row.set_subtitle(str(e))
            with self._op_lock:
                self._checking = False
            return
        self._check_btn.set_sensitive(False)
        self._spinner.set_visible(True)
        self._spinner.start()
        self._result_row.set_title(_("Pruefe..."))
        self._result_row.set_subtitle("")

        if self.api_client and not self.db:
            # Client-Modus: Prüfung via API
            def api_worker():
                try:
                    check_params = dict(
                        numbers=sorted(numbers),
                        draw_day=draw_day.value,
                        draw_date=draw_date.isoformat(),
                    )
                    if is_ej:
                        check_params["bonus_numbers"] = sorted(bonus_numbers)
                    else:
                        check_params["super_number"] = bonus_numbers[0] if bonus_numbers else 0
                    data = self.api_client.check_ticket(**check_params)
                    GLib.idle_add(self._on_api_check_done, ticket, data, None)
                except (ConnectionError, TimeoutError, OSError) as e:
                    GLib.idle_add(self._on_api_check_done, ticket, None, str(e))
                except Exception as e:
                    logger.exception(f"Unerwarteter Fehler bei API-Scheinpruefung: {e}")
                    GLib.idle_add(self._on_api_check_done, ticket, None, str(e))

            threading.Thread(target=api_worker, daemon=True).start()
        else:
            # Standalone: Scheinprüfung nur via API verfügbar
            logger.warning("Scheinprüfung nur via API verfügbar (core-Import entfernt)")
            GLib.idle_add(self._on_check_done, ticket, None, _("Nur im Server-Modus verfügbar"))
            return

    def _on_check_done(self, ticket, result, error: str | None) -> bool:
        """Prüfung abgeschlossen (Main-Thread)."""
        with self._op_lock:
            self._checking = False
        self._check_btn.set_sensitive(True)
        self._spinner.stop()
        self._spinner.set_visible(False)

        if error:
            self._result_row.set_title(_("Fehler"))
            self._result_row.set_subtitle(error)
            self._prize_amount_row.set_subtitle("\u2014")
            return False

        if result is None:
            self._result_row.set_title(_("Keine Ziehung gefunden"))
            self._result_row.set_subtitle(
                _("Für") + f" {ticket.draw_day.value} " + _("am") + f" {ticket.draw_date} "
                + _("wurde keine Ziehung in der Datenbank gefunden.")
            )
            # Deine Zahlen trotzdem anzeigen (ohne Matching)
            self._your_balls.set_numbers(
                ticket.numbers, super_number=ticket.super_number,
            )
            self._prize_amount_row.set_subtitle("\u2014")
            return False

        # Matching-Zahlen
        matching = result.matching_numbers

        # Deine Zahlen mit Match-Highlighting
        self._your_balls.set_numbers(
            ticket.numbers,
            super_number=ticket.super_number,
            matching=matching,
        )

        # Gezogene Zahlen
        self._drawn_balls.set_numbers(
            result.draw.numbers,
            super_number=result.draw.super_number,
            matching=matching,
        )

        # Treffer
        match_text = (
            f"{result.match_count} " + _("Richtige") + ": "
            f"{', '.join(str(n) for n in matching)}"
            if matching else "0 " + _("Richtige")
        )
        sz_text = _("Superzahl: Treffer!") if result.super_number_match else _("Superzahl: Kein Treffer")
        self._matches_row.set_subtitle(f"{match_text} | {sz_text}")

        # Gewinnklasse
        if result.is_winner:
            self._result_row.set_title(_("Gewinnklasse") + f" {result.prize_class}")
            from lotto_common.models.generation import PRIZE_DESCRIPTIONS
            desc = PRIZE_DESCRIPTIONS.get(result.prize_class, "")
            self._result_row.set_subtitle(desc)
            self._prize_row.set_subtitle(_("Klasse") + f" {result.prize_class}: {desc}")
        else:
            self._result_row.set_title(_("Kein Gewinn"))
            self._result_row.set_subtitle(_("Leider kein Treffer in einer Gewinnklasse."))
            self._prize_row.set_subtitle("—")

        # Gewinnbetrag nachschlagen
        draw_day_str = result.draw.draw_day.value
        draw_date_iso = result.draw.draw_date.isoformat()
        self._lookup_prize_amount(draw_day_str, draw_date_iso, result.prize_class if result.is_winner else None)

        return False

    def _on_api_check_done(self, ticket, data: dict | None, error: str | None) -> bool:
        """API-Prüfung abgeschlossen (Client-Modus, Main-Thread)."""
        with self._op_lock:
            self._checking = False
        self._check_btn.set_sensitive(True)
        self._spinner.stop()
        self._spinner.set_visible(False)

        if error:
            self._result_row.set_title(_("Fehler"))
            self._result_row.set_subtitle(error)
            self._prize_amount_row.set_subtitle("\u2014")
            return False

        if not data:
            self._result_row.set_title(_("Keine Ziehung gefunden"))
            self._result_row.set_subtitle(_("Server konnte keine passende Ziehung finden."))
            self._prize_amount_row.set_subtitle("\u2014")
            return False

        # Treffer
        match_count = data.get("match_count", 0)
        matching = data.get("matching_numbers", [])
        sz_match = data.get("super_number_match", False)

        # Deine Zahlen mit Match-Highlighting
        self._your_balls.set_numbers(
            ticket.numbers, super_number=ticket.super_number,
            matching=matching,
        )

        # Gezogene Zahlen aus API-Response anzeigen
        drawn_numbers = data.get("drawn_numbers", [])
        drawn_sz = data.get("drawn_super_number")
        if drawn_numbers:
            self._drawn_balls.set_numbers(
                drawn_numbers, super_number=drawn_sz,
                matching=matching,
            )

        match_text = (
            f"{match_count} " + _("Richtige") + f": {', '.join(str(n) for n in matching)}"
            if matching else "0 " + _("Richtige")
        )
        if ticket.is_eurojackpot:
            bonus_matches = data.get("bonus_matches", 0)
            bonus_text = _("Eurozahlen") + f": {bonus_matches}/2 " + _("Treffer")
        else:
            bonus_text = _("Superzahl: Treffer!") if sz_match else _("Superzahl: Kein Treffer")
        self._matches_row.set_subtitle(f"{match_text} | {bonus_text}")

        # Gewinnklasse
        prize_class = data.get("prize_class")
        prize_name = data.get("prize_class_name", "")
        if prize_class:
            self._result_row.set_title(_("Gewinnklasse") + f" {prize_class}")
            self._result_row.set_subtitle(prize_name)
            self._prize_row.set_subtitle(_("Klasse") + f" {prize_class}: {prize_name}")
        else:
            self._result_row.set_title(_("Kein Gewinn"))
            self._result_row.set_subtitle(_("Leider kein Treffer in einer Gewinnklasse."))
            self._prize_row.set_subtitle("—")

        # Gewinnbetrag nachschlagen
        draw_day_str = data.get("draw_day", ticket.draw_day.value)
        draw_date_iso = data.get("draw_date", ticket.draw_date.isoformat())
        self._lookup_prize_amount(draw_day_str, draw_date_iso, prize_class)

        return False

    # ══════════════════════════════════════════════
    # Vorhersage laden + eintragen
    # ══════════════════════════════════════════════

