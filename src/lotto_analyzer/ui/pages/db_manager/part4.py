"""UI-Seite db_manager: part4 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("db_manager.part4")
import csv

from gi.repository import Gio


class Part4Mixin:
    """Part4 Mixin."""

    # ── Doppelklick zum Bearbeiten ──

    def _on_row_activated(self, column_view, position) -> None:
        if self.app_mode == "client" or self._is_readonly:
            return  # Kein Edit im Client-Modus oder für READONLY-Benutzer
        if position < len(self._rows):
            self._show_edit_dialog(self._rows[position])

    # ── CSV-Export ──

    def _on_export_csv(self, btn) -> None:
        if not self._current_table:
            return
        if self.app_mode != "client" and not self.db:
            return

        dialog = Gtk.FileDialog()
        dialog.set_initial_name(f"{self._current_table}.csv")

        csv_filter = Gtk.FileFilter()
        csv_filter.set_name(_("CSV-Dateien"))
        csv_filter.add_pattern("*.csv")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(csv_filter)
        dialog.set_filters(filters)

        root = self.get_root()
        if root:
            dialog.save(root, None, self._on_export_done)

    def _on_export_done(self, dialog, result) -> None:
        try:
            file = dialog.save_finish(result)
            if not file:
                return

            path = file.get_path()

            if self.app_mode == "client" and self.api_client:
                self._export_csv_api(path)
            elif self.db:
                self._export_csv_local(path)

        except Exception as e:
            self._status_label.set_label(f"{_('Export fehlgeschlagen')}: {e}")
            logger.error(f"Export: {e}")

    def _export_csv_api(self, path: str) -> None:
        """CSV-Export via API (alle Seiten laden)."""
        self._status_label.set_label(_("Exportiere via API..."))

        def worker():
            try:
                all_rows = []
                page = 1
                while True:
                    result = self.api_client.db_table_rows(
                        self._current_table, page=page, page_size=500,
                    )
                    rows = result.get("rows", [])
                    columns = result.get("columns", self._columns)
                    all_rows.extend(rows)
                    total = result.get("total", 0)
                    if not rows or len(all_rows) >= total:
                        break
                    page += 1
                GLib.idle_add(self._write_csv, path, columns, all_rows)
            except Exception as e:
                GLib.idle_add(self._status_label.set_label, f"{_('Export fehlgeschlagen')}: {e}")
                logger.error(f"Export API: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _export_csv_local(self, path: str) -> None:
        """CSV-Export aus lokaler DB."""
        with self.db.connection() as conn:
            rows = conn.execute(
                f'SELECT * FROM "{self._current_table}"'
            ).fetchall()
            all_rows = [dict(row) for row in rows]

        self._write_csv(path, self._columns, all_rows)

    def _write_csv(self, path: str, columns: list[str], rows: list[dict]) -> bool:
        """CSV-Datei schreiben."""
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(columns)
                for row_dict in rows:
                    writer.writerow(
                        str(row_dict.get(col, "") or "") for col in columns
                    )

            self._status_label.set_label(f"{_('Exportiert')}: {path} ({len(rows)} {_('Zeilen')})")
            logger.info(f"CSV exportiert: {path}")
        except Exception as e:
            self._status_label.set_label(f"{_('Export fehlgeschlagen')}: {e}")
            logger.error(f"Export: {e}")
        return False
