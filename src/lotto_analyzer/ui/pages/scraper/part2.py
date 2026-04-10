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

import sqlite3


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

        # Client-Modus: Aktualisierung via API (jetzt Task-basiert)
        if self.api_client and not self.db:
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
            return

        if not self.db:
            with self._op_lock:
                self._crawling = False
            return

        self._set_crawl_controls(False)
        self._status_row.set_subtitle(_("Pruefe neue Ziehungen..."))
        self._crawl_result.set_visible(False)

        # Standalone: Refresh nur via API verfügbar
        logger.warning("Refresh nur via API verfügbar (core-Import entfernt)")
        with self._op_lock:
            self._crawling = False
        self._set_crawl_controls(True)
        self._status_row.set_subtitle(_("Nur im Server-Modus verfügbar"))

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

        if self.app_mode == "client" and self.api_client:
            # Client-Modus: Training via Server-API
            def retrain_worker():
                try:
                    self.api_client.train_ml()
                    logger.info("Auto-Retrain via Server gestartet.")
                except Exception as e:
                    logger.warning(f"Auto-Retrain via Server fehlgeschlagen: {e}")

            threading.Thread(target=retrain_worker, daemon=True).start()
            return

        if not self.db:
            return

        # Standalone: Auto-Retrain nur via API verfügbar
        logger.warning("Auto-Retrain nur via API verfügbar (core-Import entfernt)")

    # ═══════════════════════════════════════════
    # CSV-Import
    # ═══════════════════════════════════════════

    def _on_csv_import(self, button: Gtk.Button) -> None:
        if not self.db and not self.api_client:
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

        if self.app_mode == "client" and self.api_client and not self.db:
            # Client-Modus: Datei lesen und an Server senden
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
            return

        # Standalone: CSV-Import nur via API verfügbar
        logger.warning("CSV-Import nur via API verfügbar (core-Import entfernt)")
        self._csv_result.set_label(_("Nur im Server-Modus verfügbar"))
        self._csv_result.set_visible(True)

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

        if self.app_mode == "client" and self.api_client and not self.db:
            # Client-Modus: via API eintragen
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
            return

        if not self.db:
            return
        try:
            self.db.insert_draw(draw)
        except Exception as e:
            widget._status.set_label(f"DB-Fehler: {e}")

    # ═══════════════════════════════════════════
    # AI-Kontrolle 1: Quelle ↔ DB Verifikation
    # ═══════════════════════════════════════════

    def _verify_source_vs_db(self) -> str:
        """Vergleich: was wurde gescrapt/importiert vs was steht in der DB."""
        if not self._last_source_draws or not self.db:
            return _("Keine Quelldaten zum Vergleichen vorhanden.")

        report = [f"=== VERIFIKATION: {self._last_source_label} ===\n"]
        source = self._last_source_draws
        ok_count = 0
        mismatch = []
        missing_in_db = []

        # Stichproben (max 50 oder alle wenn weniger)
        sample = source if len(source) <= 50 else (
            source[:15] + source[len(source)//2-5:len(source)//2+5] + source[-15:]
        )

        for draw in sample:
            db_draws = self.db.get_draws(draw.draw_day)
            db_match = None
            for db_d in db_draws:
                if db_d.draw_date == draw.draw_date:
                    db_match = db_d
                    break

            if db_match is None:
                missing_in_db.append(draw)
                continue

            # Zahlen vergleichen
            src_nums = sorted(draw.numbers)
            db_nums = sorted(db_match.numbers)
            if src_nums == db_nums and draw.super_number == db_match.super_number:
                ok_count += 1
            else:
                mismatch.append({
                    "date": draw.draw_date,
                    "source_nums": src_nums,
                    "db_nums": db_nums,
                    "source_sz": draw.super_number,
                    "db_sz": db_match.super_number,
                })

        report.append(f"Geprüft: {len(sample)} von {len(source)} Ziehungen")
        report.append(f"Uebereinstimmend: {ok_count}/{len(sample)}")

        if mismatch:
            report.append(f"\n⚠️ ABWEICHUNGEN ({len(mismatch)}):")
            for m in mismatch[:10]:
                report.append(
                    f"  {m['date']}:"
                    f"\n    Quelle: {m['source_nums']} SZ={m['source_sz']}"
                    f"\n    DB:     {m['db_nums']} SZ={m['db_sz']}"
                )

        if missing_in_db:
            report.append(f"\n⚠️ FEHLEN IN DB ({len(missing_in_db)}):")
            for d in missing_in_db[:10]:
                report.append(f"  {d.draw_date} {d.draw_day.value}: {sorted(d.numbers)}")

        if not mismatch and not missing_in_db:
            report.append("\n✅ Alle geprüften Ziehungen stimmen überein!")

        # Stichproben-Details anzeigen
        report.append(f"\nStichproben-Details (erste 5):")
        for draw in sample[:5]:
            report.append(
                f"  {draw.draw_date} ({draw.draw_day.value}): "
                f"{sorted(draw.numbers)} SZ={draw.super_number}"
            )

        return "\n".join(report)

