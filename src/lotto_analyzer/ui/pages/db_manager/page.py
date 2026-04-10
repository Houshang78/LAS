"""DB-Manager: Tabellen anzeigen, Datensaetze bearbeiten, löschen, hinzufügen."""

from __future__ import annotations

import csv
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib, Gdk, Pango

from lotto_common.config import ConfigManager
from lotto_common.i18n import _
from lotto_common.models.game_config import GameType, get_config
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_analyzer.ui.ui_helpers import show_error_toast
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from lotto_analyzer.ui.widgets.help_button import HelpButton
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
import time

logger = get_logger("db_manager")


from lotto_analyzer.ui.pages.db_manager.part1 import Part1Mixin
from lotto_analyzer.ui.pages.db_manager.part2 import Part2Mixin
from lotto_analyzer.ui.pages.db_manager.part3 import Part3Mixin
from lotto_analyzer.ui.pages.db_manager.part4 import Part4Mixin


class DBManagerPage(Part1Mixin, Part2Mixin, Part3Mixin, Part4Mixin, BasePage):
    """Datenbank-Browser: Tabellen, Spalten, Datensaetze bearbeiten."""

    PAGE_SIZE = 100           # Datensaetze pro Seite
    SEARCH_DEBOUNCE_MS = 300  # Millisekunden Verzoegerung bei Suche
    CSV_EXPORT_BATCH = 500    # Zeilen pro API-Abfrage beim CSV-Export

    def __init__(self, config_manager: ConfigManager, db: Database | None, app_mode: str, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager=config_manager, db=db, app_mode=app_mode, api_client=api_client,
                         app_db=app_db, backtest_db=backtest_db)
        self._current_table: str | None = None
        self._columns: list[str] = []
        self._rows: list[dict] = []
        self._sort_column: str | None = None
        self._sort_ascending: bool = True
        self._updating_sort_ui: bool = False
        self._game_type: GameType = GameType.LOTTO6AUS49
        self._config = get_config(self._game_type)
        self._ai_analyst = None
        self._table_columns_cache = {}
        self._sorter_handler_id = None
        self._search_timer = None
        self._undo_stack: list[dict] = []  # [{table, rows: [{col: val}]}]
        self._undo_btn = None  # Created in _build_ui
        self._init_ai()
        self._build_ui()

    def _init_ai(self) -> None:
        # Standalone-AI entfernt: AI läuft immer auf dem Server
        pass

    def cleanup(self) -> None:
        """Timer aufräumen (Search-Debounce)."""
        if self._search_timer:
            GLib.source_remove(self._search_timer)
            self._search_timer = None
        super().cleanup()

    def set_api_client(self, client: "APIClient | None") -> None:
        """API-Client setzen."""
        super().set_api_client(client)
        if hasattr(self, "_ai_panel"):
            self._ai_panel.api_client = client

    def refresh(self) -> None:
        """Tabellen nur neu laden wenn Daten veraltet (>5min)."""
        if self.is_stale() and (self.db or self.api_client):
            self._load_tables()

    def _build_ui(self) -> None:
        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_box.set_margin_top(16)
        header_box.set_margin_start(16)
        header_box.set_margin_end(16)

        title = Gtk.Label(label=_("Datenbank-Manager"))
        title.add_css_class("title-1")
        header_box.append(title)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header_box.append(spacer)

        # Refresh
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_("Aktualisieren"))
        refresh_btn.connect("clicked", self._on_refresh)
        header_box.append(refresh_btn)

        self.append(header_box)

        # Status-Zeile
        self._status_label = Gtk.Label(label="")
        self._status_label.set_xalign(0)
        self._status_label.set_margin_start(16)
        self._status_label.set_margin_top(4)
        self._status_label.add_css_class("dim-label")
        self.append(self._status_label)

        # Haupt-Split: links Tabellen-Liste, rechts Daten
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_margin_top(12)
        paned.set_margin_bottom(12)
        paned.set_margin_start(12)
        paned.set_margin_end(12)
        paned.set_position(260)
        paned.set_shrink_start_child(False)
        self.append(paned)

        # AI-Panel
        self._ai_panel = AIPanel(
            ai_analyst=self._ai_analyst, api_client=self.api_client,
            title="AI-Analyse", config_manager=self.config_manager,
            db=self.db, page="db_manager", app_db=self.app_db,
        )
        self._ai_panel.set_margin_start(12)
        self._ai_panel.set_margin_end(12)
        self._ai_panel.set_margin_bottom(12)
        self.append(self._ai_panel)

        # ── Linke Seite: Tabellen-Liste ──
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left_box.set_size_request(260, -1)

        left_header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        left_header_lbl = Gtk.Label(label=_("Tabellen"))
        left_header_lbl.add_css_class("heading")
        left_header_lbl.set_hexpand(True)
        left_header_lbl.set_xalign(0)
        left_header_box.append(left_header_lbl)
        left_header_box.append(
            HelpButton(_("Alle Datenbank-Tabellen. Klicke auf eine Tabelle um deren Inhalt anzuzeigen."))
        )
        left_header_box.set_margin_top(8)
        left_box.append(left_header_box)

        left_scroll = Gtk.ScrolledWindow()
        left_scroll.set_vexpand(True)
        left_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._table_listbox = Gtk.ListBox()
        self._table_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._table_listbox.add_css_class("navigation-sidebar")
        self._table_listbox.connect("row-selected", self._on_table_selected)
        left_scroll.set_child(self._table_listbox)
        left_box.append(left_scroll)

        # DB-Info
        self._db_info_label = Gtk.Label(label="")
        self._db_info_label.set_wrap(True)
        self._db_info_label.set_xalign(0)
        self._db_info_label.set_margin_start(8)
        self._db_info_label.set_margin_bottom(8)
        self._db_info_label.add_css_class("dim-label")
        left_box.append(self._db_info_label)

        paned.set_start_child(left_box)

        # ── Rechte Seite: Daten-Ansicht ──
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        # Toolbar: Suche + Aktionen
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.set_margin_start(8)
        toolbar.set_margin_end(8)
        toolbar.set_margin_top(8)

        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text(_("Suche in Tabelle..."))
        self._search_entry.set_hexpand(True)
        self._search_entry.set_tooltip_text(_("Filtert die Tabellenzeilen nach dem eingegebenen Suchbegriff (durchsucht alle Spalten)."))
        self._search_entry.connect("search-changed", self._on_search_changed)
        toolbar.append(self._search_entry)

        self._add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Fuegt eine neue Zeile in die ausgewählte Tabelle ein."))
        self._add_btn.add_css_class("suggested-action")
        self._add_btn.connect("clicked", self._on_add_row)
        self._add_btn.set_sensitive(False)
        self.register_readonly_button(self._add_btn)
        toolbar.append(self._add_btn)

        self._delete_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("Löscht die ausgewählten Zeilen aus der Tabelle."))
        self._delete_btn.add_css_class("destructive-action")
        self._delete_btn.connect("clicked", self._on_delete_rows)
        self._delete_btn.set_sensitive(False)
        self.register_readonly_button(self._delete_btn)
        toolbar.append(self._delete_btn)

        self._undo_btn = Gtk.Button(icon_name="edit-undo-symbolic")
        self._undo_btn.set_tooltip_text(_("Letzte Loeschung rückgängig machen"))
        self._undo_btn.connect("clicked", self._on_undo)
        self._undo_btn.set_sensitive(False)
        self.register_readonly_button(self._undo_btn)
        toolbar.append(self._undo_btn)

        self._bulk_edit_btn = Gtk.Button(icon_name="document-edit-symbolic")
        self._bulk_edit_btn.set_tooltip_text(_("Spalte für alle ausgewählten Zeilen ändern"))
        self._bulk_edit_btn.connect("clicked", self._on_bulk_edit)
        self._bulk_edit_btn.set_sensitive(False)
        self.register_readonly_button(self._bulk_edit_btn)
        toolbar.append(self._bulk_edit_btn)

        self._copy_btn = Gtk.Button(icon_name="edit-copy-symbolic")
        self._copy_btn.set_tooltip_text(_("Ausgewählte Zeilen in Zwischenablage kopieren"))
        self._copy_btn.connect("clicked", self._on_copy_rows)
        self._copy_btn.set_sensitive(False)
        toolbar.append(self._copy_btn)

        self._export_btn = Gtk.Button(icon_name="document-save-symbolic", tooltip_text=_("Exportiert die gesamte Tabelle als CSV-Datei."))
        self._export_btn.connect("clicked", self._on_export_csv)
        self._export_btn.set_sensitive(False)
        toolbar.append(self._export_btn)

        right_box.append(toolbar)

        # Spalten-Info
        self._columns_label = Gtk.Label(label="")
        self._columns_label.set_xalign(0)
        self._columns_label.set_margin_start(8)
        self._columns_label.add_css_class("dim-label")
        self._columns_label.set_ellipsize(Pango.EllipsizeMode.END)
        right_box.append(self._columns_label)

        # Daten-Tabelle (ColumnView)
        data_scroll = Gtk.ScrolledWindow()
        data_scroll.set_vexpand(True)
        data_scroll.set_hexpand(True)
        data_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._column_view = Gtk.ColumnView()
        self._column_view.set_show_row_separators(True)
        self._column_view.set_show_column_separators(True)
        self._column_view.set_reorderable(False)
        self._column_view.connect("activate", self._on_row_activated)

        # Tastaturkuerzel für ColumnView (Ctrl+C, Delete)
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_table_key_pressed)
        self._column_view.add_controller(key_controller)

        # Selection model
        self._selection_model = Gtk.MultiSelection()
        self._store = Gtk.StringList()
        self._selection_model.set_model(self._store)
        self._column_view.set_model(self._selection_model)

        data_scroll.set_child(self._column_view)
        right_box.append(data_scroll)

        # Paging
        page_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        page_box.set_halign(Gtk.Align.CENTER)
        page_box.set_margin_bottom(8)

        self._prev_btn = Gtk.Button(label=_("Zurück"))
        self._prev_btn.set_tooltip_text(_("Vorherige Seite"))
        self._prev_btn.connect("clicked", self._on_prev_page)
        self._prev_btn.set_sensitive(False)
        page_box.append(self._prev_btn)

        self._page_label = Gtk.Label(label="")
        page_box.append(self._page_label)

        self._next_btn = Gtk.Button(label=_("Weiter"))
        self._next_btn.set_tooltip_text(_("Nächste Seite"))
        self._next_btn.connect("clicked", self._on_next_page)
        self._next_btn.set_sensitive(False)
        page_box.append(self._next_btn)

        right_box.append(page_box)

        paned.set_end_child(right_box)

        # Paging state
        self._page = 0
        self._page_size = self.PAGE_SIZE
        self._total_rows = 0
        self._search_text = ""

        # Tabellen laden
        GLib.idle_add(self._load_tables)

    def set_game_type(self, game_type: GameType) -> None:
        """Spieltyp wechseln — Tabellenliste aktualisieren."""
        self._game_type = game_type
        self._config = get_config(game_type)

        # Tabellen-Liste und Daten neu laden
        self._load_tables()

        # Relevante Tabelle automatisch selektieren
        prefix = self._config.db_table_prefix
        self._status_label.set_label(
            f"{_('Spieltyp')}: {self._config.display_name} "
            f"({_('Tabellen-Prefix')}: {prefix})"
        )

