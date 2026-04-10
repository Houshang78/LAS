"""UI-Seite db_manager: part2 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("db_manager.part2")

from lotto_analyzer.ui.ui_helpers import show_error_toast


class Part2Mixin:
    """Part2 Mixin."""

    # ── Refresh ──

    def _on_refresh(self, btn) -> None:
        self._load_tables()
        if self._current_table:
            self._needs_column_rebuild = True
            self._load_table_data()

    # ── Neuer Datensatz ──

    def _on_add_row(self, btn) -> None:
        if not self._current_table or not self._columns:
            return
        if self.app_mode == "client" or self._is_readonly:
            return  # Kein Add im Client-Modus oder für READONLY-Benutzer
        self._show_edit_dialog(None)

    def _show_edit_dialog(self, existing_row: dict | None) -> None:
        """Dialog zum Erstellen oder Bearbeiten eines Datensatzes."""
        is_edit = existing_row is not None
        dialog_title = _("Datensatz bearbeiten") if is_edit else _("Neuer Datensatz")

        dialog = Adw.Dialog()
        dialog.set_title(dialog_title)
        dialog.set_content_width(500)
        dialog.set_content_height(600)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        group = Adw.PreferencesGroup(title=self._current_table)

        entries: dict[str, Gtk.Entry] = {}
        for col in self._columns:
            if col == "id" and not is_edit:
                continue  # Auto-Increment

            row = Adw.EntryRow(title=col)
            if existing_row and col in existing_row:
                val = existing_row[col]
                row.set_text(str(val) if val is not None else "")
            if col == "id":
                row.set_editable(False)
            group.add(row)
            entries[col] = row

        content.append(group)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.END)
        btn_box.set_margin_top(12)

        cancel_btn = Gtk.Button(label=_("Abbrechen"))
        cancel_btn.set_tooltip_text(_("Bearbeitung abbrechen"))
        cancel_btn.connect("clicked", lambda b: dialog.close())
        btn_box.append(cancel_btn)

        save_btn = Gtk.Button(label=_("Speichern"))
        save_btn.set_tooltip_text(_("Änderungen speichern"))
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", lambda b: self._on_save_row(dialog, entries, existing_row))
        btn_box.append(save_btn)

        content.append(btn_box)

        scrolled.set_child(content)
        toolbar_view.set_content(scrolled)
        dialog.set_child(toolbar_view)

        root = self.get_root()
        if root:
            dialog.present(root)

    def _on_save_row(self, dialog, entries: dict, existing_row: dict | None) -> None:
        """Datensatz speichern (INSERT oder UPDATE)."""
        if self.app_mode == "client":
            # Client-Modus: kein Add/Edit (nur Lesen + Löschen)
            dialog.close()
            return
        if not self.db or not self._current_table:
            return

        try:
            values = {}
            for col, entry in entries.items():
                text = entry.get_text().strip()
                if text == "":
                    values[col] = None
                else:
                    values[col] = text

            with self.db.connection() as conn:
                if existing_row and "id" in existing_row:
                    # UPDATE
                    set_parts = []
                    params = []
                    for col, val in values.items():
                        if col == "id":
                            continue
                        set_parts.append(f'"{col}" = ?')
                        params.append(val)
                    params.append(existing_row["id"])
                    conn.execute(
                        f'UPDATE "{self._current_table}" SET {", ".join(set_parts)} WHERE id = ?',
                        params,
                    )
                    logger.info(f"Datensatz aktualisiert in {self._current_table}, id={existing_row['id']}")
                else:
                    # INSERT
                    cols = [c for c in values if c != "id"]
                    vals = [values[c] for c in cols]
                    placeholders = ", ".join("?" * len(cols))
                    col_names = ", ".join(f'"{c}"' for c in cols)
                    conn.execute(
                        f'INSERT INTO "{self._current_table}" ({col_names}) VALUES ({placeholders})',
                        vals,
                    )
                    logger.info(f"Neuer Datensatz in {self._current_table}")

            dialog.close()
            self._load_table_data()
            self._load_tables()  # Counts aktualisieren

        except Exception as e:
            logger.error(f"Speichern fehlgeschlagen: {e}")
            show_error_toast(self, str(e))

    # ── Löschen ──

    def _on_delete_rows(self, btn) -> None:
        if not self._current_table or self._is_readonly:
            return
        if self.app_mode == "client" and not self.api_client:
            return
        if self.app_mode != "client" and not self.db:
            return

        # Ausgewählte Zeilen ermitteln
        selected_indices = []
        bitset = self._selection_model.get_selection()
        for i in range(self._store.get_n_items()):
            if bitset.contains(i):
                selected_indices.append(i)

        if not selected_indices:
            self._status_label.set_label(_("Keine Datensaetze ausgewählt."))
            return

        # Bestätigungsdialog
        n = len(selected_indices)
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Datensaetze löschen?"))
        dialog.set_body(f"{n} {_('Datensatz/Datensaetze aus')} '{self._current_table}' {_('löschen')}?")
        dialog.add_response("cancel", _("Abbrechen"))
        dialog.add_response("delete", _("Löschen"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_delete_confirmed, selected_indices)

        root = self.get_root()
        if root:
            dialog.present(root)

    def _on_delete_confirmed(self, dialog, response: str, selected_indices: list[int]) -> None:
        if response != "delete":
            return

        if self.app_mode == "client" and self.api_client:
            self._delete_rows_api(selected_indices)
        elif self.db:
            self._delete_rows_local(selected_indices)

    def _delete_rows_api(self, selected_indices: list[int]) -> None:
        """Zeilen via API löschen (Client-Modus, nutzt ROWID)."""
        # Save rows for undo BEFORE deleting
        undo_entry: dict = {"table": self._current_table, "rows": []}
        for idx in selected_indices:
            if idx < len(self._rows):
                undo_entry["rows"].append(dict(self._rows[idx]))
        if undo_entry["rows"]:
            self._undo_stack.append(undo_entry)
            if len(self._undo_stack) > 10:
                self._undo_stack = self._undo_stack[-10:]
            self._undo_btn.set_sensitive(True)

        rowids = []
        for idx in selected_indices:
            if idx < len(self._rows) and "rowid" in self._rows[idx]:
                rowids.append(self._rows[idx]["rowid"])
        if not rowids:
            self._status_label.set_label(_("Keine loesbaren Datensaetze ausgewählt."))
            return

        self._status_label.set_label(f"{_('Loesche')} {len(rowids)} {_('Datensaetze')}...")

        def worker():
            errors = []
            for rowid in rowids:
                try:
                    self.api_client.db_delete_row(self._current_table, rowid)
                except Exception as e:
                    errors.append(str(e))
            GLib.idle_add(self._on_delete_done_api, len(rowids), errors)

        threading.Thread(target=worker, daemon=True).start()

    def _on_delete_done_api(self, count: int, errors: list[str]) -> bool:
        if errors:
            self._status_label.set_label(f"{_('Löschen teils fehlgeschlagen')}: {errors[0]}")
            logger.error(f"Löschen API: {errors}")
        else:
            logger.info(f"{count} Datensaetze aus {self._current_table} gelöscht (API)")
        self._load_table_data()
        self._load_tables()
        return False

    def _delete_rows_local(self, selected_indices: list[int]) -> None:
        """Zeilen aus lokaler DB löschen (Standalone-Modus)."""
        try:
            # Save rows for undo BEFORE deleting
            undo_entry: dict = {"table": self._current_table, "rows": []}
            for idx in selected_indices:
                if idx < len(self._rows):
                    undo_entry["rows"].append(dict(self._rows[idx]))

            ids_to_delete = []
            for idx in selected_indices:
                if idx < len(self._rows) and "id" in self._rows[idx]:
                    ids_to_delete.append(self._rows[idx]["id"])

            if not ids_to_delete and "id" not in self._columns:
                with self.db.connection() as conn:
                    rows = conn.execute(
                        f'SELECT rowid, * FROM "{self._current_table}" '
                        f'LIMIT ? OFFSET ?',
                        [self._page_size, self._page * self._page_size],
                    ).fetchall()
                    for idx in selected_indices:
                        if idx < len(rows):
                            rowid = rows[idx]["rowid"]
                            conn.execute(
                                f'DELETE FROM "{self._current_table}" WHERE rowid = ?',
                                (rowid,),
                            )
            elif ids_to_delete:
                with self.db.connection() as conn:
                    placeholders = ", ".join("?" * len(ids_to_delete))
                    conn.execute(
                        f'DELETE FROM "{self._current_table}" WHERE id IN ({placeholders})',
                        ids_to_delete,
                    )

            # Push to undo stack (max 10 entries)
            if undo_entry["rows"]:
                self._undo_stack.append(undo_entry)
                if len(self._undo_stack) > 10:
                    self._undo_stack = self._undo_stack[-10:]
                self._undo_btn.set_sensitive(True)

            logger.info(f"{len(selected_indices)} Datensaetze aus {self._current_table} gelöscht")
            self._load_table_data()
            self._load_tables()

        except Exception as e:
            self._status_label.set_label(f"{_('Löschen fehlgeschlagen')}: {e}")
            logger.error(f"Löschen: {e}")

    # ── Undo ──

    def _on_undo(self, btn) -> None:
        """Letzte Loeschung rückgängig machen (re-insert)."""
        if not self._undo_stack:
            return
        entry = self._undo_stack.pop()
        table = entry["table"]
        rows = entry["rows"]

        if self.app_mode == "client" and self.api_client:
            from lotto_analyzer.ui.ui_helpers import show_toast
            show_toast(self, _("Undo im Client-Modus nicht verfügbar"))
            self._undo_btn.set_sensitive(bool(self._undo_stack))
            return

        if self.db:
            try:
                with self.db.connection() as conn:
                    for row_data in rows:
                        cols = [c for c in row_data.keys() if c != "rowid"]
                        vals = [row_data[c] for c in cols]
                        placeholders = ", ".join("?" * len(cols))
                        col_names = ", ".join(f'"{c}"' for c in cols)
                        conn.execute(
                            f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})',
                            vals,
                        )
                self._load_table_data()
                self._load_tables()
                from lotto_analyzer.ui.ui_helpers import show_toast
                show_toast(self, f"{len(rows)} {_('Zeile(n) wiederhergestellt')}")
                logger.info(f"Undo: {len(rows)} Zeilen in {table} wiederhergestellt")
            except Exception as e:
                show_error_toast(self, str(e))
                logger.error(f"Undo fehlgeschlagen: {e}")

        self._undo_btn.set_sensitive(bool(self._undo_stack))

