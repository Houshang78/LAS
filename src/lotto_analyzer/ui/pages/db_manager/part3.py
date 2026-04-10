"""UI-Seite db_manager: part3 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("db_manager.part3")
from gi.repository import Gdk

from lotto_analyzer.ui.ui_helpers import show_error_toast


class Part3Mixin:
    """Part3 Mixin."""

    # ── Bulk-Edit ──

    def _on_bulk_edit(self, btn) -> None:
        """Dialog: Spalte für alle ausgewählten Zeilen ändern."""
        if not self._current_table or not self._columns or self._is_readonly:
            return
        if self.app_mode == "client":
            from lotto_analyzer.ui.ui_helpers import show_toast
            show_toast(self, _("Bulk-Edit im Client-Modus nicht verfügbar"))
            return

        # Ausgewählte Zeilen ermitteln
        selected_indices = []
        bitset = self._selection_model.get_selection()
        for i in range(self._store.get_n_items()):
            if bitset.contains(i):
                selected_indices.append(i)

        if not selected_indices:
            return

        n = len(selected_indices)

        # Dialog aufbauen
        dialog = Adw.Dialog()
        dialog.set_title(_("Bulk-Edit: %d Zeile(n)") % n)
        dialog.set_content_width(450)
        dialog.set_content_height(350)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        # Info
        info = Gtk.Label(
            label=_("%d ausgewählte Zeilen in '%s' bearbeiten") % (n, self._current_table),
        )
        info.set_wrap(True)
        info.add_css_class("dim-label")
        content.append(info)

        # Spalten-Auswahl (ohne 'id' und 'rowid')
        group = Adw.PreferencesGroup(title=_("Spalte und Wert"))

        editable_cols = [c for c in self._columns if c.lower() not in ("id", "rowid")]
        if not editable_cols:
            from lotto_analyzer.ui.ui_helpers import show_toast
            show_toast(self, _("Keine editierbaren Spalten"))
            return

        col_combo = Adw.ComboRow(title=_("Spalte"))
        col_model = Gtk.StringList()
        for c in editable_cols:
            col_model.append(c)
        col_combo.set_model(col_model)
        group.add(col_combo)

        value_entry = Adw.EntryRow(title=_("Neuer Wert"))
        value_entry.set_tooltip_text(
            _("Leeres Feld = NULL setzen. Wert wird für alle ausgewählten Zeilen gesetzt."),
        )
        group.add(value_entry)

        content.append(group)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.END)
        btn_box.set_margin_top(12)

        cancel_btn = Gtk.Button(label=_("Abbrechen"))
        cancel_btn.connect("clicked", lambda b: dialog.close())
        btn_box.append(cancel_btn)

        apply_btn = Gtk.Button(label=_("Auf %d Zeilen anwenden") % n)
        apply_btn.add_css_class("destructive-action")
        apply_btn.connect(
            "clicked",
            lambda b: self._on_bulk_edit_apply(
                dialog, editable_cols, col_combo, value_entry, selected_indices,
            ),
        )
        btn_box.append(apply_btn)

        content.append(btn_box)

        toolbar_view.set_content(content)
        dialog.set_child(toolbar_view)

        root = self.get_root()
        if root:
            dialog.present(root)

    def _on_bulk_edit_apply(
        self, dialog, editable_cols, col_combo, value_entry, selected_indices,
    ) -> None:
        """Bulk-Edit ausführen: UPDATE für alle ausgewählten Zeilen."""
        col_idx = col_combo.get_selected()
        if col_idx < 0 or col_idx >= len(editable_cols):
            return

        column = editable_cols[col_idx]
        new_value = value_entry.get_text().strip()
        if new_value == "":
            new_value = None  # NULL

        if not self.db:
            return

        try:
            # Undo-Daten sichern
            undo_entry: dict = {"table": self._current_table, "rows": []}
            for idx in selected_indices:
                if idx < len(self._rows):
                    undo_entry["rows"].append(dict(self._rows[idx]))

            updated = 0
            with self.db.connection() as conn:
                # IDs oder rowids der ausgewählten Zeilen sammeln
                if "id" in self._columns:
                    ids = []
                    for idx in selected_indices:
                        if idx < len(self._rows) and "id" in self._rows[idx]:
                            ids.append(self._rows[idx]["id"])
                    if ids:
                        placeholders = ", ".join("?" * len(ids))
                        conn.execute(
                            f'UPDATE "{self._current_table}" SET "{column}" = ? '
                            f'WHERE id IN ({placeholders})',
                            [new_value] + ids,
                        )
                        updated = len(ids)
                else:
                    # Fallback: rowid-basiert
                    rows = conn.execute(
                        f'SELECT rowid, * FROM "{self._current_table}" '
                        f'LIMIT ? OFFSET ?',
                        [self._page_size, self._page * self._page_size],
                    ).fetchall()
                    for idx in selected_indices:
                        if idx < len(rows):
                            rowid = rows[idx]["rowid"]
                            conn.execute(
                                f'UPDATE "{self._current_table}" SET "{column}" = ? '
                                f'WHERE rowid = ?',
                                (new_value, rowid),
                            )
                            updated += 1

            # Undo-Stack
            if undo_entry["rows"]:
                self._undo_stack.append(undo_entry)
                if len(self._undo_stack) > 10:
                    self._undo_stack = self._undo_stack[-10:]
                self._undo_btn.set_sensitive(True)

            dialog.close()
            self._load_table_data()

            display_val = new_value if new_value is not None else "NULL"
            self._status_label.set_label(
                _("%d Zeile(n) aktualisiert: %s = %s") % (updated, column, display_val),
            )
            logger.info(
                f"Bulk-Edit: {updated} Zeilen in {self._current_table}.{column} = {display_val}",
            )

        except Exception as e:
            show_error_toast(self, str(e))
            logger.error(f"Bulk-Edit fehlgeschlagen: {e}")

    # ── Selektion ──

    def _on_selection_changed(self, model, position, n_items) -> None:
        bitset = model.get_selection()
        has_selection = not bitset.is_empty()
        self._delete_btn.set_sensitive(has_selection and not self._is_readonly)
        self._bulk_edit_btn.set_sensitive(has_selection and not self._is_readonly)
        self._copy_btn.set_sensitive(has_selection)

    # ── Tastaturkuerzel für Tabelle ──

    def _on_table_key_pressed(self, controller, keyval, keycode, state) -> bool:
        """Tastendruck in der ColumnView verarbeiten (Ctrl+C, Delete)."""
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)

        if ctrl and keyval == Gdk.KEY_c:
            self._on_copy_rows(None)
            return True

        if keyval == Gdk.KEY_Delete:
            self._on_delete_rows(None)
            return True

        if ctrl and keyval == Gdk.KEY_z:
            self._on_undo(None)
            return True

        if ctrl and keyval == Gdk.KEY_e:
            self._on_bulk_edit(None)
            return True

        return False

    # ── Zeilen kopieren ──

    def _on_copy_rows(self, btn) -> None:
        """Ausgewählte Zeilen als Tab-separierter Text in Zwischenablage kopieren."""
        selected_indices = []
        bitset = self._selection_model.get_selection()
        for i in range(self._store.get_n_items()):
            if bitset.contains(i):
                selected_indices.append(i)

        if not selected_indices:
            return

        lines = ["\t".join(self._columns)]  # Header
        for idx in selected_indices:
            if idx < len(self._rows):
                row = self._rows[idx]
                values = [str(row.get(col, "")) for col in self._columns]
                lines.append("\t".join(values))

        text = "\n".join(lines)
        clipboard = self.get_display().get_clipboard()
        clipboard.set(text)

        from lotto_analyzer.ui.ui_helpers import show_toast
        show_toast(self, f"{len(selected_indices)} {_('Zeile(n) kopiert')}")

