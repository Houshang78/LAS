"""UI-Seite scraper: part2."""

from __future__ import annotations

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_analyzer.ui.widgets.draw_input import DrawInput
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_analyzer.ui.widgets.draw_input import DrawInput
from lotto_common.config import ConfigManager
from lotto_analyzer.ui.widgets.draw_input import DrawInput
from lotto_analyzer.ui.widgets.draw_input import DrawInput
from lotto_common.models.draw import DrawDay
from lotto_analyzer.ui.widgets.draw_input import DrawInput
from lotto_common.models.game_config import GameType, get_config
from lotto_analyzer.ui.widgets.draw_input import DrawInput


logger = get_logger("scraper.part2")



class Part2Mixin:
    """Part2 Mixin."""

    def _on_crawl_done(self, source_draws: list, inserted: int, error: str | None) -> bool:
        with self._op_lock:
            self._crawling = False
        self._set_crawl_controls(True)
        self._progress.set_fraction(1.0)

        found = len(source_draws)
        if error:
            self._status_row.set_subtitle(_("Fehler: %s") % error)
            self._crawl_result.set_label(_("Crawl fehlgeschlagen: %s") % error)
        else:
            self._status_row.set_subtitle(_("Bereit"))
            self._crawl_result.set_label(
                _("Crawl abgeschlossen: %d Ziehungen gefunden, %d neu eingefuegt.") % (found, inserted)
            )
            # Daten für Verifikation merken
            self._last_source_draws = source_draws
            self._last_source_label = f"Web-Crawl ({found} Ziehungen)"
            self._verify_btn.set_sensitive(found > 0)
            # Auto-Retrain bei neuen Daten
            self._trigger_auto_retrain(inserted)

        self._crawl_result.set_visible(True)
        return False

    def _on_refresh(self, button: Gtk.Button) -> None:
        with self._op_lock:
            if self._crawling:
                return
            self._crawling = True

        # API-only: Aktualisierung via Server (Task-basiert)
        if not self.api_client:
            with self._op_lock:
                self._crawling = False
            self._status_row.set_subtitle(_("Server nicht verbunden."))
            return

        self._set_crawl_controls(False)
        self._status_row.set_subtitle(_("Aktualisierung via Server..."))
        self._crawl_result.set_visible(False)

        def api_worker():
            try:
                data = self.api_client.crawl_latest()
                task_id = data.get("task_id")
                if task_id:
                    self._poll_crawl_task(task_id)
                else:
                    GLib.idle_add(self._on_api_crawl_done, data, None)
            except (ConnectionError, TimeoutError, OSError) as e:
                GLib.idle_add(self._on_api_crawl_done, None, str(e))
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler beim API-Refresh: {e}")
                GLib.idle_add(self._on_api_crawl_done, None, str(e))

        threading.Thread(target=api_worker, daemon=True).start()

    def _on_refresh_done(self, new_count: int, all_draws: list) -> bool:
        with self._op_lock:
            self._crawling = False
        self._set_crawl_controls(True)

        if new_count > 0:
            msg = _("%d neue Ziehung(en) gefunden und gespeichert.") % new_count
        else:
            msg = _("Keine neuen Ziehungen gefunden.")

        self._status_row.set_subtitle(_("Bereit"))
        self._crawl_result.set_label(msg)
        self._crawl_result.set_visible(True)

        # Daten merken
        if all_draws:
            self._last_source_draws = all_draws
            self._last_source_label = f"Aktualisierung ({len(all_draws)} Ziehungen)"
            self._verify_btn.set_sensitive(True)
        # Auto-Retrain bei neuen Daten
        self._trigger_auto_retrain(new_count)
        return False

    def _on_api_crawl_done(self, result: dict | None, error: str | None) -> bool:
        """API-Crawl abgeschlossen (Client-Modus, Main-Thread)."""
        # WS-Listener entfernen (Crawl ist fertig)
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("task_update", self._on_ws_crawl_task)
        except Exception:
            pass
        with self._op_lock:
            self._crawling = False
        self._set_crawl_controls(True)
        self._status_row.set_subtitle(_("Bereit"))

        if error:
            self._crawl_result.set_label(_("Fehler: %s") % error)
        elif result:
            imported = result.get("imported", 0)
            days = result.get("days", [])
            self._crawl_result.set_label(
                _("Server-Crawl: %d Ziehungen importiert (%s)") % (imported, ", ".join(days))
            )
        else:
            self._crawl_result.set_label(_("Keine Ergebnisse vom Server."))
        self._crawl_result.set_visible(True)
        return False

    # ═══════════════════════════════════════════
    # Auto-Retrain nach neuen Daten
    # ═══════════════════════════════════════════

    def _trigger_auto_retrain(self, inserted: int) -> None:
        """Nach Crawl mit neuen Daten ML-Retraining anstossen."""
        if inserted <= 0:
            return
        try:
            config = self.config_manager.config
            if not config.learning.auto_retrain_after_draw:
                return
        except Exception as e:
            logger.warning(f"Auto-Retrain Config-Prüfung fehlgeschlagen: {e}")
            return

        logger.info(f"Auto-Retrain: {inserted} neue Ziehungen, starte ML-Training...")

        if not self.api_client:
            logger.warning("Auto-Retrain: kein api_client.")
            return

        def retrain_worker():
            try:
                self.api_client.train_ml()
                logger.info("Auto-Retrain via Server gestartet.")
            except Exception as e:
                logger.warning(f"Auto-Retrain via Server fehlgeschlagen: {e}")

        threading.Thread(target=retrain_worker, daemon=True).start()

    # ═══════════════════════════════════════════
    # CSV-Import
    # ═══════════════════════════════════════════

    def _on_csv_import(self, button: Gtk.Button) -> None:
        if not self.api_client:
            self._csv_result.set_label(_("Server nicht verbunden."))
            self._csv_result.set_visible(True)
            return
        from gi.repository import Gio
        dialog = Gtk.FileDialog()
        dialog.set_title(_("CSV-Datei importieren"))
        csv_filter = Gtk.FileFilter()
        csv_filter.set_name(_("CSV-Dateien (*.csv, *.txt)"))
        csv_filter.add_pattern("*.csv")
        csv_filter.add_pattern("*.txt")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(csv_filter)
        dialog.set_filters(filters)
        root = self.get_root()
        if root:
            dialog.open(root, None, self._on_csv_file_selected)

    def _on_csv_file_selected(self, dialog, result) -> None:
        try:
            file = dialog.open_finish(result)
        except Exception as e:
            logger.warning(f"CSV-Dateidialog abgebrochen oder fehlgeschlagen: {e}")
            return
        if not file:
            return
        path = file.get_path()
        csv_day_idx = self._csv_day_combo.get_selected()
        csv_draw_days = self._config.draw_days
        if csv_day_idx < len(csv_draw_days):
            draw_day = DrawDay(csv_draw_days[csv_day_idx])
        else:
            draw_day = DrawDay(csv_draw_days[0])
        self._csv_result.set_label(_("Importiere %s...") % path)
        self._csv_result.set_visible(True)

        # API-only: Datei lesen und an Server senden
        def api_worker():
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    csv_content = f.read()
                data = self.api_client.import_csv(draw_day.value, csv_content)
                found = data.get("found", 0)
                inserted = data.get("inserted", 0)
                GLib.idle_add(self._on_csv_import_done, [None] * found, inserted, path)
            except Exception as e:
                GLib.idle_add(self._csv_result.set_label, f"Fehler: {e}")
                GLib.idle_add(self._csv_result.set_visible, True)

        threading.Thread(target=api_worker, daemon=True).start()

    def _on_csv_import_done(self, source_draws: list, inserted: int, path: str) -> bool:
        import os
        filename = os.path.basename(path)
        found = len(source_draws)
        self._csv_result.set_label(
            _("CSV '%s': %d Ziehungen gelesen, %d neu eingefuegt.") % (filename, found, inserted)
        )
        self._csv_result.set_visible(True)

        # Daten merken
        self._last_source_draws = source_draws
        self._last_source_label = f"CSV '{filename}' ({found} Ziehungen)"
        self._verify_btn.set_sensitive(found > 0)
        return False

    # ═══════════════════════════════════════════
    # Manuelle Eingabe
    # ═══════════════════════════════════════════

    def _on_draw_submitted(self, widget: DrawInput) -> None:
        draw = widget.get_draw()
        if not draw:
            return

        if not self.api_client:
            widget._status.set_label(_("Server nicht verbunden."))
            return

        def api_worker():
            try:
                self.api_client.manual_draw_entry(
                    draw_date=draw.draw_date.isoformat(),
                    numbers=sorted(draw.numbers),
                    super_number=draw.super_number or 0,
                    draw_day=draw.draw_day.value,
                )
                GLib.idle_add(widget._status.set_label, _("Erfolgreich gespeichert (Server)."))
            except Exception as e:
                GLib.idle_add(widget._status.set_label, f"Server-Fehler: {e}")

        threading.Thread(target=api_worker, daemon=True).start()

    # _verify_source_vs_db entfernt (C.2). Verifikation läuft jetzt
    # serverseitig: DBIntegrityChecker bei jedem Crawl, Endpoint
    # GET /db/integrity. UI ruft api_client.db_integrity() statt lokal
    # zu vergleichen — Quelle der Wahrheit ist der Server.

