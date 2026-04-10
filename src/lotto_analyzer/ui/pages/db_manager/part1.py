"""UI-Seite db_manager: part1 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("db_manager.part1")


class Part1Mixin:
    """Part1 Mixin."""

    # ── Tabellen laden ──

    def _load_tables(self) -> bool:
        if self.app_mode == "client" and self.api_client:
            self._load_tables_api()
        elif self.db:
            self._load_tables_local()
        else:
            self._status_label.set_label(_("Keine Datenbank verfügbar."))
        return False

    def _load_tables_api(self) -> None:
        """Tabellen via API laden (Client-Modus)."""
        self._status_label.set_label(_("Lade Tabellen vom Server..."))

        def worker():
            try:
                tables = self.api_client.db_tables()
                GLib.idle_add(self._on_tables_loaded_api, tables)
            except Exception as e:
                GLib.idle_add(self._status_label.set_label, f"{_('Fehler')}: {e}")
                logger.error(f"Tabellen laden (API): {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_tables_loaded_api(self, tables: list[dict]) -> bool:
        """API-Tabellendaten in die UI eintragen."""
        self._db_info_label.set_label(f"{_('Server-DB')}\n{len(tables)} {_('Tabellen')}")
        self._populate_table_list(
            [(t["name"], t.get("row_count", 0)) for t in tables]
        )
        # Spaltentypen cachen für spätere Anzeige
        self._table_columns_cache = {
            t["name"]: t.get("columns", []) for t in tables
        }
        self._status_label.set_label(f"{len(tables)} {_('Tabellen gefunden')}")
        return False

    def _load_tables_local(self) -> None:
        """Tabellen aus lokaler DB laden (Standalone-Modus)."""
        try:
            with self.db.connection() as conn:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
                table_counts = []
                for row in rows:
                    name = row[0]
                    try:
                        cnt = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
                        table_counts.append((name, cnt[0] if cnt else 0))
                    except Exception as e:
                        logger.warning(f"Tabelle '{name}' zaehlen fehlgeschlagen: {e}")
                        table_counts.append((name, 0))

                db_size = self.db.db_path.stat().st_size if self.db.db_path.exists() else 0
                size_str = f"{db_size / 1024 / 1024:.2f} MB" if db_size > 1024*1024 else f"{db_size / 1024:.1f} KB"
                self._db_info_label.set_label(f"DB: {self.db.db_path.name}\n{_('Größe')}: {size_str}")

            self._populate_table_list(table_counts)
            self._status_label.set_label(f"{len(table_counts)} {_('Tabellen gefunden')}")

        except Exception as e:
            self._status_label.set_label(f"{_('Fehler')}: {e}")
            logger.error(f"Tabellen laden: {e}")

    def _populate_table_list(self, table_counts: list[tuple[str, int]]) -> None:
        """ListBox mit Tabellennamen und Counts fuellen."""
        child = self._table_listbox.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._table_listbox.remove(child)
            child = next_child

        prefix = self._config.db_table_prefix
        for table_name, count in table_counts:
            row = Gtk.ListBoxRow()
            row.table_name = table_name

            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_start(8)
            box.set_margin_end(8)

            is_current = table_name.startswith(prefix)
            icon_name = "starred-symbolic" if is_current else "x-office-spreadsheet-symbolic"
            icon = Gtk.Image.new_from_icon_name(icon_name)
            box.append(icon)

            lbl = Gtk.Label(label=table_name)
            lbl.set_xalign(0)
            lbl.set_hexpand(True)
            if is_current:
                lbl.add_css_class("accent")
            box.append(lbl)

            count_lbl = Gtk.Label(label=str(count))
            count_lbl.add_css_class("dim-label")
            box.append(count_lbl)

            row.set_child(box)
            self._table_listbox.append(row)

    def _on_table_selected(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row and hasattr(row, "table_name"):
            self._current_table = row.table_name
            self._page = 0
            self._search_text = ""
            self._search_entry.set_text("")
            self._undo_stack.clear()
            if self._undo_btn:
                self._undo_btn.set_sensitive(False)
            self._add_btn.set_sensitive(self.app_mode != "client" and not self._is_readonly)
            self._export_btn.set_sensitive(True)
            # Draw-Tabellen: neueste zuerst
            if self._current_table.startswith(("draws_", "ej_draws_")):
                self._sort_column = "draw_date"
                self._sort_ascending = False
            else:
                self._sort_column = None
                self._sort_ascending = True
            self._needs_column_rebuild = True
            self._load_table_data()

    # ── Tabellendaten laden ──

    def _load_table_data(self) -> None:
        if not self._current_table:
            return
        if self.app_mode == "client" and self.api_client:
            self._load_table_data_api()
        elif self.db:
            self._load_table_data_local()

    def _load_table_data_api(self) -> None:
        """Tabellendaten via API laden (Client-Modus)."""
        self._status_label.set_label(f"{_('Lade')} {self._current_table}...")
        sort_dir = "ASC" if self._sort_ascending else "DESC"

        def worker():
            try:
                result = self.api_client.db_table_rows(
                    self._current_table,
                    page=self._page + 1,  # API ist 1-basiert
                    page_size=self._page_size,
                    search=self._search_text,
                    sort_col=self._sort_column or "",
                    sort_dir=sort_dir,
                )
                GLib.idle_add(self._on_table_data_loaded_api, result)
            except Exception as e:
                GLib.idle_add(self._status_label.set_label, f"{_('Fehler')}: {e}")
                logger.error(f"Daten laden API ({self._current_table}): {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_table_data_loaded_api(self, result: dict) -> bool:
        """API-Tabellendaten in die UI eintragen."""
        self._columns = result.get("columns", [])
        self._total_rows = result.get("total", 0)
        self._rows = result.get("rows", [])

        # Spalten-Info aus Cache holen (enthaelt Typen)
        cache = getattr(self, "_table_columns_cache", {})
        col_info = cache.get(self._current_table, [])
        col_types = {c["name"]: c["type"] for c in col_info} if col_info else {}
        col_desc = ", ".join(f"{n} ({col_types.get(n, '')})" for n in self._columns)
        self._columns_label.set_label(f"{_('Spalten')}: {col_desc}")

        if getattr(self, "_needs_column_rebuild", True):
            self._needs_column_rebuild = False
            self._build_columns()
        self._update_data()
        self._update_paging()

        page_str = f"{_('Seite')} {self._page + 1}/{max(1, (self._total_rows + self._page_size - 1) // self._page_size)}"
        self._status_label.set_label(
            f"{_('Tabelle')}: {self._current_table} | {self._total_rows} {_('Datensaetze')} | {page_str}"
        )
        return False

    def _load_table_data_local(self) -> None:
        """Tabellendaten aus lokaler DB laden (Standalone-Modus)."""
        try:
            with self.db.connection() as conn:
                cursor = conn.execute(f'PRAGMA table_info("{self._current_table}")')
                col_info = cursor.fetchall()
                self._columns = [c["name"] for c in col_info]
                col_types = {c["name"]: c["type"] for c in col_info}

                col_desc = ", ".join(f"{n} ({col_types.get(n, '')})" for n in self._columns)
                self._columns_label.set_label(f"{_('Spalten')}: {col_desc}")

                where_clause = ""
                params: list = []
                if self._search_text:
                    conditions = []
                    for col in self._columns:
                        conditions.append(f'CAST("{col}" AS TEXT) LIKE ?')
                        params.append(f"%{self._search_text}%")
                    where_clause = f" WHERE {' OR '.join(conditions)}"

                count_row = conn.execute(
                    f'SELECT COUNT(*) FROM "{self._current_table}"{where_clause}',
                    params,
                ).fetchone()
                self._total_rows = count_row[0] if count_row else 0

                order = ""
                if self._sort_column and self._sort_column in self._columns:
                    direction = "ASC" if self._sort_ascending else "DESC"
                    order = f' ORDER BY "{self._sort_column}" {direction}'

                offset = self._page * self._page_size
                query_params = list(params)
                query_params.extend([self._page_size, offset])

                rows = conn.execute(
                    f'SELECT * FROM "{self._current_table}"{where_clause}{order} '
                    f'LIMIT ? OFFSET ?',
                    query_params,
                ).fetchall()
                self._rows = [dict(row) for row in rows]

            if getattr(self, "_needs_column_rebuild", True):
                self._needs_column_rebuild = False
                self._build_columns()
            self._update_data()
            self._update_paging()

            page_str = f"Seite {self._page + 1}/{max(1, (self._total_rows + self._page_size - 1) // self._page_size)}"
            self._status_label.set_label(
                f"Tabelle: {self._current_table} | {self._total_rows} Datensaetze | {page_str}"
            )

        except Exception as e:
            self._status_label.set_label(f"{_('Fehler')}: {e}")
            logger.error(f"Daten laden ({self._current_table}): {e}")

    def _build_columns(self) -> None:
        """Spalten-Struktur neu aufbauen (nur bei Tabellenwechsel)."""
        # Altes Sorter-Signal trennen
        if hasattr(self, "_sorter_handler_id") and self._sorter_handler_id:
            cv_sorter = self._column_view.get_sorter()
            if cv_sorter:
                cv_sorter.disconnect(self._sorter_handler_id)
            self._sorter_handler_id = None

        # Alte Spalten entfernen
        while self._column_view.get_columns().get_n_items() > 0:
            col = self._column_view.get_columns().get_item(0)
            self._column_view.remove_column(col)

        # Spalten erstellen mit kompakten Anzeigenamen
        for col_idx, col_name in enumerate(self._columns):
            factory = Gtk.SignalListItemFactory()
            factory.col_idx = col_idx
            factory.connect("setup", self._on_cell_setup)
            factory.connect("bind", self._on_cell_bind)

            display_name = self._column_display_name(col_name)
            column = Gtk.ColumnViewColumn(title=display_name, factory=factory)

            # Spaltenbreite: Draw-Tabellen kompakt + fest, andere flexibel
            is_draw_table = self._current_table and self._current_table.startswith(("draws_", "ej_draws_"))
            if is_draw_table:
                if col_name.startswith("number_") or col_name == "super_number" \
                        or col_name == "additional_number" \
                        or col_name.startswith("euro_"):
                    column.set_resizable(False)
                    column.set_fixed_width(45)
                elif col_name == "id":
                    column.set_resizable(False)
                    column.set_fixed_width(60)
                elif col_name == "draw_date":
                    column.set_resizable(False)
                    column.set_fixed_width(115)
                elif col_name == "source":
                    column.set_resizable(True)
                    column.set_fixed_width(80)
                else:
                    column.set_resizable(True)
                    column.set_expand(col_idx == len(self._columns) - 1)
            else:
                column.set_resizable(True)
                column.set_expand(col_idx == len(self._columns) - 1)

            # Dummy-Sorter auf jede Spalte → Header wird klickbar
            sorter = Gtk.CustomSorter.new(lambda a, b, d: 0, None)
            column.set_sorter(sorter)
            self._column_view.append_column(column)

        # Sorter-Signal einmal verbinden
        cv_sorter = self._column_view.get_sorter()
        if cv_sorter:
            self._sorter_handler_id = cv_sorter.connect("changed", self._on_column_sort_changed)

        # Initiale Sortierung setzen
        if self._sort_column and self._sort_column in self._columns:
            self._activate_column_sort(self._sort_column, self._sort_ascending)

    def _update_data(self) -> None:
        """Nur Daten im Store aktualisieren (bei Sort/Paging/Suche)."""
        self._store = Gtk.StringList()
        for row_data in self._rows:
            vals = []
            for col in self._columns:
                v = row_data.get(col, "")
                vals.append(str(v) if v is not None else "")
            self._store.append("\t".join(vals))

        self._selection_model = Gtk.MultiSelection.new(self._store)
        self._selection_model.connect("selection-changed", self._on_selection_changed)
        self._column_view.set_model(self._selection_model)
        self._delete_btn.set_sensitive(False)

    def _display_to_db_name(self, display_name: str) -> str:
        """Anzeigenamen zurück in DB-Spaltennamen umwandeln."""
        for col in self._columns:
            if self._column_display_name(col) == display_name:
                return col
        return display_name

    @staticmethod
    def _column_display_name(col_name: str) -> str:
        """DB-Spaltenname in kompakten Anzeigenamen umwandeln."""
        _MAP = {
            "id": "ID",
            "super_number": "SZ",
            "additional_number": "ZZ",
        }
        if col_name in _MAP:
            return _MAP[col_name]
        # number_1..6 → N_1..6
        if col_name.startswith("number_"):
            return "N_" + col_name[7:]
        # euro_1..2 → EU_1..2
        if col_name.startswith("euro_"):
            return "EU_" + col_name[5:]
        return col_name

    def _on_column_sort_changed(self, sorter, change) -> None:
        """ColumnView-Header geklickt → SQL-Sortierung aktualisieren."""
        if self._updating_sort_ui:
            return
        primary_col = sorter.get_primary_sort_column()
        if primary_col:
            # Display-Name → DB-Spaltenname zurück-mappen
            display_title = primary_col.get_title()
            db_col = self._display_to_db_name(display_title)
            sort_order = sorter.get_primary_sort_order()
            self._sort_column = db_col
            self._sort_ascending = (sort_order == Gtk.SortType.ASCENDING)
        else:
            self._sort_column = None
            self._sort_ascending = True
        self._page = 0
        self._load_table_data()

    def _activate_column_sort(self, col_name: str, ascending: bool) -> None:
        """Programmatisch eine Spalte als sortiert markieren."""
        self._updating_sort_ui = True
        display_name = self._column_display_name(col_name)
        columns = self._column_view.get_columns()
        for i in range(columns.get_n_items()):
            col = columns.get_item(i)
            if col.get_title() == display_name:
                # Klick simulieren: Sorter aktivieren
                sort_order = Gtk.SortType.ASCENDING if ascending else Gtk.SortType.DESCENDING
                self._column_view.sort_by_column(col, sort_order)
                break
        self._updating_sort_ui = False

    def _on_cell_setup(self, factory, list_item):
        label = Gtk.Label()
        label.set_xalign(0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(40)
        list_item.set_child(label)

    def _on_cell_bind(self, factory, list_item):
        label = list_item.get_child()
        item = list_item.get_item()
        if item:
            text = item.get_string()
            parts = text.split("\t")
            col_idx = factory.col_idx
            if col_idx < len(parts):
                label.set_label(parts[col_idx])
            else:
                label.set_label("")

    # ── Paging ──

    def _update_paging(self) -> None:
        total_pages = max(1, (self._total_rows + self._page_size - 1) // self._page_size)
        self._page_label.set_label(f"{_('Seite')} {self._page + 1} / {total_pages}")
        self._prev_btn.set_sensitive(self._page > 0)
        self._next_btn.set_sensitive(self._page < total_pages - 1)

    def _on_prev_page(self, btn) -> None:
        if self._page > 0:
            self._page -= 1
            self._load_table_data()

    def _on_next_page(self, btn) -> None:
        total_pages = max(1, (self._total_rows + self._page_size - 1) // self._page_size)
        if self._page < total_pages - 1:
            self._page += 1
            self._load_table_data()

    # ── Suche ──

    def _on_search_changed(self, entry) -> None:
        self._search_text = entry.get_text().strip()
        if self._search_timer:
            GLib.source_remove(self._search_timer)
        self._search_timer = GLib.timeout_add(300, self._do_search)

    def _do_search(self) -> bool:
        self._search_timer = None
        self._page = 0
        if self._current_table:
            self._load_table_data()
        return False  # Don't repeat

