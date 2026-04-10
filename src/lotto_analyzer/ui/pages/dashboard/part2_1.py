"""UI-Seite dashboard: part2."""

from __future__ import annotations

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_analyzer.ui.pages.dashboard.page import _DAY_NAMES
from lotto_common.config import ConfigManager
from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config


logger = get_logger("dashboard.part2")



import sqlite3


class Part2Mixin1:
    """Teil 1 von Part2Mixin."""

    def _update_integrity_ui(self, report) -> bool:
        """Integritäts-Status im UI aktualisieren."""
        # Alte Detail-Zeilen entfernen
        for row in self._integrity_details:
            self._integrity_group.remove(row)
        self._integrity_details.clear()

        if report.overall_complete:
            self._integrity_row.set_subtitle(_("Alle Daten vollständig"))
            if self._integrity_icon and self._integrity_icon.get_parent():
                self._integrity_row.remove(self._integrity_icon)
            self._integrity_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            self._integrity_row.add_prefix(self._integrity_icon)
        else:
            gaps = len(report.needs_crawl)
            self._integrity_row.set_subtitle(
                _("%d Ziehungstag(e) mit Lücken") % gaps
            )
            if self._integrity_icon and self._integrity_icon.get_parent():
                self._integrity_row.remove(self._integrity_icon)
            self._integrity_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
            self._integrity_row.add_prefix(self._integrity_icon)

        # Detail-Zeilen für jeden Ziehungstag
        for status in report.statuses:
            name = _DAY_NAMES.get(status.draw_day, status.draw_day)
            if status.is_complete:
                subtitle = _("%d Ziehungen") % status.total_draws + " — %.0f%%" % status.coverage_pct
            else:
                years = ", ".join(str(y) for y in status.missing_years[:5])
                if len(status.missing_years) > 5:
                    years += f" (+{len(status.missing_years) - 5})"
                subtitle = _("Lücken: %s") % years
            row = Adw.ActionRow(title=name, subtitle=subtitle)
            self._integrity_group.add(row)
            self._integrity_details.append(row)

        return False

    def _load_integrity_api(self) -> None:
        """DB-Integrität via API prüfen (Client-Modus)."""
        def worker():
            try:
                data = self.api_client.db_integrity()
                GLib.idle_add(self._update_integrity_api_ui, data)
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning(f"API-Integritätspruefung fehlgeschlagen: {e}")
                GLib.idle_add(
                    self._integrity_row.set_subtitle, _("Fehler bei Prüfung")
                )

        threading.Thread(target=worker, daemon=True).start()

    def _update_integrity_api_ui(self, data: dict) -> bool:
        """Integritäts-Daten vom Server im UI anzeigen."""
        for row in self._integrity_details:
            self._integrity_group.remove(row)
        self._integrity_details.clear()

        overall_complete = data.get("overall_complete", True)
        needs_crawl = data.get("needs_crawl", [])
        statuses = data.get("statuses", [])

        if overall_complete:
            self._integrity_row.set_subtitle(_("Alle Daten vollständig"))
            if self._integrity_icon and self._integrity_icon.get_parent():
                self._integrity_row.remove(self._integrity_icon)
            self._integrity_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            self._integrity_row.add_prefix(self._integrity_icon)
        else:
            gaps = len(needs_crawl)
            self._integrity_row.set_subtitle(
                _("%d Ziehungstag(e) mit Lücken") % gaps
            )
            if self._integrity_icon and self._integrity_icon.get_parent():
                self._integrity_row.remove(self._integrity_icon)
            self._integrity_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
            self._integrity_row.add_prefix(self._integrity_icon)

        for status in statuses:
            dd = status.get("draw_day", "?")
            name = _DAY_NAMES.get(dd, dd)
            is_complete = status.get("is_complete", True)
            total_draws = status.get("total_draws", 0)
            coverage = status.get("coverage_pct", 0)
            if is_complete:
                subtitle = _("%d Ziehungen") % total_draws + " — %.0f%%" % coverage
            else:
                missing = status.get("missing_years", [])
                years = ", ".join(str(y) for y in missing[:5])
                if len(missing) > 5:
                    years += f" (+{len(missing) - 5})"
                subtitle = _("Lücken: %s") % years
            row = Adw.ActionRow(title=name, subtitle=subtitle)
            self._integrity_group.add(row)
            self._integrity_details.append(row)

        return False

    def _load_recommendations(self) -> None:
        """Kaufempfehlungen aus DB laden (Standalone) — nur via API verfügbar."""
        logger.warning("Kaufempfehlungen nur via API verfügbar (core-Import entfernt)")
        GLib.idle_add(self._update_recommendations_ui, {})

    def _load_recommendations_api(self) -> None:
        """Kaufempfehlungen via API laden."""
        def worker():
            try:
                recs = {}
                for day_str in self._config.draw_days:
                    try:
                        rec = self.api_client.recommendations(day_str, count=0)
                        recs[day_str] = rec
                    except Exception as e:
                        logger.warning(f"Empfehlung laden fehlgeschlagen ({day_str}): {e}")
                        recs[day_str] = None
                GLib.idle_add(self._update_recommendations_ui, recs)
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning(f"API-Empfehlungen laden fehlgeschlagen: {e}")
                GLib.idle_add(self._update_recommendations_ui, {})
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler beim API-Empfehlungen laden: {e}")
                GLib.idle_add(self._update_recommendations_ui, {})
        threading.Thread(target=worker, daemon=True).start()

