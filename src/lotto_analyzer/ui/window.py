"""Hauptfenster mit Sidebar-Navigation und 16 Seiten."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib, Gdk

import threading
from datetime import date, timedelta

from lotto_common.config import ConfigManager
from lotto_common.i18n import _
from lotto_common.models.game_config import GameType, GAME_CONFIGS, get_config, game_for_draw_day
from lotto_analyzer.ui.widgets.task_status import TaskStatusBar
from lotto_common.utils.logging_config import get_logger

logger = get_logger("window")

# Seiten-Definition: (id, icon, titel)
PAGES = [
    ("dashboard",    "go-home-symbolic",          "Dashboard"),
    ("scraper",      "emblem-downloads-symbolic",  "Daten-Crawler"),
    ("statistics",   "utilities-system-monitor-symbolic", "Statistik"),
    ("generator",    "starred-symbolic",           "Generator"),
    ("reports",      "document-open-symbolic",     "Berichte"),
    ("pred_quality", "view-paged-symbolic",       "Qualität"),
    ("backtest",     "system-run-symbolic",       "Backtest"),
    ("ml_dashboard", "applications-science-symbolic", "ML-Dashboard"),
    ("ai_chat",      "user-available-symbolic",    "AI-Chat"),
    ("checker",      "emblem-default-symbolic",    "Schein-Prüfung"),
    ("db_manager",   "drive-harddisk-symbolic",    "Datenbank"),
    ("telegram",     "mail-send-symbolic",          "Telegram"),
    ("settings",     "emblem-system-symbolic",     "Einstellungen"),
    ("security",     "security-high-symbolic",     "Sicherheit"),
    ("server_monitor", "computer-symbolic",        "Monitor"),
    ("server_admin", "network-server-symbolic",    "Server"),
]


class MainWindow(Adw.ApplicationWindow):
    """Hauptfenster mit Sidebar + Content-Stack."""

    def __init__(
        self,
        application: Adw.Application,
        config_manager: ConfigManager,
        db: Database | None,
        app_mode: str = "client",
        server_address: str | None = None,
        profile_manager=None,
        app_db=None,
        backtest_db=None,
    ):
        super().__init__(application=application)
        self.config_manager = config_manager
        self.db = db
        self.app_db = app_db
        self.backtest_db = backtest_db
        self.app_mode = app_mode
        self.server_address = server_address
        self._pages: dict[str, Gtk.Widget] = {}
        self._current_page_id: str | None = None
        self._current_game_type: GameType = GameType.LOTTO6AUS49
        # API-Client aus ProfileManager extrahieren (Client-Modus)
        self.api_client = None
        if profile_manager and hasattr(profile_manager, 'client'):
            self.api_client = profile_manager.client

        self.set_title("LottoAnalyzer")
        cfg = self.config_manager.config
        self.set_default_size(
            getattr(cfg, "window_width", 1200),
            getattr(cfg, "window_height", 800),
        )
        self.set_icon_name("lotto-analyzer")

        self._build_ui()
        self._setup_keyboard_shortcuts()
        self.connect("close-request", self._on_close_request)
        logger.info("Hauptfenster erstellt")

    def _build_ui(self) -> None:
        """UI aufbauen: HeaderBar + SplitView (Sidebar + Content)."""
        # Aeussere Box
        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(outer_box)

        # HeaderBar
        header = Adw.HeaderBar()
        self._window_title = Adw.WindowTitle(
            title="LottoAnalyzer",
            subtitle="Lotto 6aus49 – Analyse &amp; Vorhersage",
        )
        header.set_title_widget(self._window_title)
        outer_box.append(header)

        # Sidebar-Toggle Button
        self._sidebar_button = Gtk.ToggleButton(icon_name="sidebar-show-symbolic")
        self._sidebar_button.set_tooltip_text("Seitenleiste ein/ausblenden")
        self._sidebar_button.set_active(True)
        self._sidebar_button.connect("toggled", self._on_sidebar_toggled)
        header.pack_start(self._sidebar_button)

        # Game-Type Toggle Button
        config = get_config(self._current_game_type)
        self._game_button = Gtk.Button(label=config.display_name)
        self._game_button.add_css_class("suggested-action")
        self._game_button.set_tooltip_text("Klick: Spieltyp wechseln")
        self._game_button.connect("clicked", self._on_game_button_clicked)
        header.pack_end(self._game_button)

        # Live-Uhr + Datum (rechts neben Titel, links vom Spieltyp-Button)
        clock_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._date_label = Gtk.Label()
        self._date_label.add_css_class("dim-label")
        clock_box.append(self._date_label)
        self._clock_label = Gtk.Label()
        self._clock_label.add_css_class("heading")
        clock_box.append(self._clock_label)
        header.pack_end(clock_box)
        self._update_clock()
        self._clock_timer_id = GLib.timeout_add_seconds(1, self._update_clock)

        # OverlaySplitView: Sidebar + Content
        self._split_view = Adw.OverlaySplitView()
        self._split_view.set_collapsed(False)
        self._split_view.set_show_sidebar(True)
        outer_box.append(self._split_view)

        # ── Sidebar ──
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar_box.set_size_request(220, -1)
        sidebar_box.add_css_class("navigation-sidebar")

        # ── User-Info: click avatar/name → profile popover ──
        self._user_avatar = Adw.Avatar(size=40, text="", show_initials=False)

        user_text_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2,
        )
        user_text_box.set_valign(Gtk.Align.CENTER)
        user_text_box.set_hexpand(True)

        self._user_name_label = Gtk.Label(label=_("Nicht angemeldet"))
        self._user_name_label.set_xalign(0)
        self._user_name_label.add_css_class("title-4")
        user_text_box.append(self._user_name_label)

        self._user_role_label = Gtk.Label(label="")
        self._user_role_label.set_xalign(0)
        self._user_role_label.add_css_class("dim-label")
        self._user_role_label.set_visible(False)
        user_text_box.append(self._user_role_label)

        # Click avatar/name → opens profile dialog directly (no popover)
        user_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        user_inner.append(self._user_avatar)
        user_inner.append(user_text_box)

        self._profile_menu_btn = Gtk.Button()
        self._profile_menu_btn.set_child(user_inner)
        self._profile_menu_btn.add_css_class("flat")
        self._profile_menu_btn.set_tooltip_text(_("Profil öffnen"))
        self._profile_menu_btn.set_margin_top(8)
        self._profile_menu_btn.set_margin_bottom(4)
        self._profile_menu_btn.set_margin_start(8)
        self._profile_menu_btn.set_margin_end(8)
        self._profile_menu_btn.connect("clicked", self._on_open_profile)
        self._build_profile_popover()

        sidebar_box.append(self._profile_menu_btn)
        sidebar_box.append(Gtk.Separator())

        self._listbox = Gtk.ListBox()
        self._listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._listbox.add_css_class("navigation-sidebar")
        self._listbox.connect("row-selected", self._on_page_selected)

        for page_id, icon_name, title in PAGES:
            row = self._create_sidebar_row(page_id, icon_name, title)
            self._listbox.append(row)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(self._listbox)
        sidebar_box.append(scrolled)

        self._split_view.set_sidebar(sidebar_box)

        # ── Content Stack ──
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(200)
        self._split_view.set_content(self._stack)

        # ── TaskStatusBar (am unteren Rand) ──
        self._task_status_bar = TaskStatusBar(api_client=self.api_client)
        outer_box.append(self._task_status_bar)
        if self.api_client:
            self._task_status_bar.start_polling()

        # Seiten erstellen
        self._create_pages()

        # Auto-Spieltyp basierend auf Wochentag
        self._auto_detect_game_type()

        # Letzte aktive Seite wiederherstellen (lokal oder vom Server)
        last_page = getattr(self.config_manager.config, "last_page", "dashboard")
        if self.api_client:
            try:
                prefs = self.api_client.get_preferences()
                last_page = prefs.get("last_page", last_page)
            except Exception as e:
                logger.debug(f"Preferences laden fehlgeschlagen: {e}")
        restored = False
        idx = 0
        while True:
            row = self._listbox.get_row_at_index(idx)
            if row is None:
                break
            if hasattr(row, "page_id") and row.page_id == last_page:
                self._listbox.select_row(row)
                restored = True
                break
            idx += 1
        if not restored:
            first_row = self._listbox.get_row_at_index(0)
            if first_row:
                self._listbox.select_row(first_row)

    def _create_sidebar_row(
        self, page_id: str, icon_name: str, title: str
    ) -> Gtk.ListBoxRow:
        """Eine Sidebar-Zeile erstellen."""
        row = Gtk.ListBoxRow()
        row.page_id = page_id

        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_icon_size(Gtk.IconSize.NORMAL)
        box.append(icon)

        label = Gtk.Label(label=title)
        label.set_xalign(0)
        label.set_hexpand(True)
        box.append(label)

        row.set_child(box)
        return row

    def _create_pages(self) -> None:
        """Alle Seiten erstellen und zum Stack hinzufügen.

        Im Client-Modus werden Seiten mit fehlenden Abhaengigkeiten
        (core-Module) uebersprungen statt zu crashen.
        """
        import importlib

        page_imports = [
            ("dashboard",    "lotto_analyzer.ui.pages.dashboard",    "DashboardPage"),
            ("scraper",      "lotto_analyzer.ui.pages.scraper",      "ScraperPage"),
            ("statistics",   "lotto_analyzer.ui.pages.statistics",   "StatisticsPage"),
            ("generator",    "lotto_analyzer.ui.pages.generator",    "GeneratorPage"),
            ("reports",      "lotto_analyzer.ui.pages.reports",      "ReportsPage"),
            ("pred_quality", "lotto_analyzer.ui.pages.prediction_quality", "PredictionQualityPage"),
            ("backtest",     "lotto_analyzer.ui.pages.backtest",            "BacktestPage"),
            ("ml_dashboard", "lotto_analyzer.ui.pages.ml_dashboard",       "MLDashboardPage"),
            ("ai_chat",      "lotto_analyzer.ui.pages.ai_chat",      "AIChatPage"),
            ("checker",      "lotto_analyzer.ui.pages.checker",      "CheckerPage"),
            ("db_manager",   "lotto_analyzer.ui.pages.db_manager",   "DBManagerPage"),
            ("telegram",     "lotto_analyzer.ui.pages.telegram",     "TelegramPage"),
            ("settings",     "lotto_analyzer.ui.pages.settings",     "SettingsPage"),
            ("security",     "lotto_analyzer.ui.pages.security",     "SecurityPage"),
            ("server_monitor", "lotto_analyzer.ui.pages.server_monitor", "ServerMonitorPage"),
            ("server_admin", "lotto_analyzer.ui.pages.server_admin", "ServerAdminPage"),
        ]

        for page_id, module_path, class_name in page_imports:
            try:
                module = importlib.import_module(module_path)
                page_class = getattr(module, class_name)
            except ImportError as e:
                if self.app_mode == "client":
                    logger.info(f"Seite '{page_id}' uebersprungen (Client-Modus): {e}")
                    continue
                raise

            try:
                page = page_class(
                    config_manager=self.config_manager,
                    db=self.db,
                    app_mode=self.app_mode,
                    api_client=self.api_client,
                    app_db=self.app_db,
                    backtest_db=self.backtest_db,
                )
            except Exception as e:
                logger.error(f"Seite '{page_id}' konnte nicht erstellt werden: {e}")
                continue

            self._pages[page_id] = page
            self._stack.add_named(page, page_id)

        # Sidebar-Einträge ohne geladene Seite entfernen
        rows_to_remove = []
        idx = 0
        while True:
            row = self._listbox.get_row_at_index(idx)
            if row is None:
                break
            if hasattr(row, "page_id") and row.page_id not in self._pages:
                rows_to_remove.append(row)
            idx += 1
        for row in rows_to_remove:
            self._listbox.remove(row)

    def _on_page_selected(
        self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None
    ) -> None:
        """Seite wechseln wenn Sidebar-Eintrag gewählt."""
        if row and hasattr(row, "page_id"):
            # cleanup() auf alter Seite aufrufen, falls vorhanden
            if self._current_page_id and self._current_page_id != row.page_id:
                old_page = self._pages.get(self._current_page_id)
                if old_page and hasattr(old_page, "cleanup"):
                    try:
                        old_page.cleanup()
                    except Exception as e:
                        logger.warning(f"cleanup() fehlgeschlagen für {self._current_page_id}: {e}")

            self._current_page_id = row.page_id
            self._stack.set_visible_child_name(row.page_id)
            # Auto-refresh nur wenn Seite veraltet (>5min)
            page = self._pages.get(row.page_id)
            if page and hasattr(page, "refresh"):
                try:
                    page.refresh()
                except Exception as e:
                    logger.warning(f"refresh() fehlgeschlagen für {row.page_id}: {e}")
            # Aktive Seite merken (async speichern)
            self.config_manager.config.last_page = row.page_id
            GLib.idle_add(self._save_last_page_async, row.page_id)
            logger.info(f"Seite gewechselt: {row.page_id}")

    def _save_last_page_async(self, page_id: str) -> bool:
        """Letzte Seite async speichern (blockiert UI nicht)."""
        import threading

        def worker():
            try:
                self.config_manager.save()
            except Exception as e:
                logger.warning(f"Config speichern fehlgeschlagen: {e}")
            if self.api_client:
                try:
                    self.api_client.set_preferences(last_page=page_id)
                except Exception as e:
                    logger.debug(f"Preferences speichern fehlgeschlagen: {e}")

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _update_clock(self) -> bool:
        """Live-Uhr und Datum aktualisieren (jede Sekunde)."""
        from datetime import datetime
        now = datetime.now()
        _wday = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][now.weekday()]
        self._date_label.set_label(f"{_wday} {now.strftime('%d.%m.%Y')}")
        self._clock_label.set_label(now.strftime("%H:%M:%S"))
        return True  # True = Timer wiederholen

    def _on_game_button_clicked(self, button: Gtk.Button) -> None:
        """Spieltyp per Klick durchschalten (toggle)."""
        game_types = list(GameType)
        current_idx = game_types.index(self._current_game_type)
        next_idx = (current_idx + 1) % len(game_types)
        game_type = game_types[next_idx]

        self._current_game_type = game_type
        config = get_config(game_type)

        # Button-Label aktualisieren
        button.set_label(config.display_name)

        # Subtitle aktualisieren
        self._window_title.set_subtitle(
            f"{config.display_name} – Analyse & Vorhersage"
        )

        # Alle Seiten benachrichtigen die set_game_type implementieren
        for page_id, page in self._pages.items():
            if hasattr(page, "set_game_type"):
                try:
                    page.set_game_type(game_type)
                except Exception as e:
                    logger.warning(
                        f"set_game_type fehlgeschlagen für {page_id}: {e}"
                    )

        logger.info(f"Spieltyp gewechselt: {config.display_name}")

    def _build_profile_popover(self) -> None:
        """No popover — avatar click opens profile dialog directly."""
        # Dummy popover labels (updated after login for sidebar display)
        self._pop_username = self._user_name_label
        self._pop_role = self._user_role_label
        self._pop_email = Gtk.Label()  # hidden placeholder

    def _on_open_profile(self, _btn) -> None:
        """Open full profile dialog window on avatar click."""
        if not self.api_client:
            return

        def worker():
            try:
                profile = self.api_client.get_my_profile()
            except Exception as e:
                logger.warning(f"Profile load failed: {e}")
                profile = {}
            GLib.idle_add(self._show_profile_dialog, profile)

        threading.Thread(target=worker, daemon=True).start()

    def _show_profile_dialog(self, profile: dict) -> bool:
        """Show a separate profile dialog window with all user data."""
        dialog = Adw.Dialog()
        dialog.set_title(_("Mein Profil"))
        dialog.set_content_width(500)
        dialog.set_content_height(640)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        dialog.set_child(box)

        # Header with avatar
        header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=16,
            halign=Gtk.Align.CENTER,
        )
        username = profile.get("username", "")
        avatar = Adw.Avatar(size=72, text=username, show_initials=True)
        header.append(avatar)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.set_valign(Gtk.Align.CENTER)
        name_lbl = Gtk.Label(label=username)
        name_lbl.add_css_class("title-2")
        info_box.append(name_lbl)

        role = profile.get("role", "user")
        role_lbl = Gtk.Label(label=role.capitalize())
        role_lbl.add_css_class("dim-label")
        info_box.append(role_lbl)
        header.append(info_box)
        box.append(header)

        # Scrollable form
        scroll = Gtk.ScrolledWindow(vexpand=True)
        box.append(scroll)
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroll.set_child(form)

        # Editable profile fields (user can request changes)
        from lotto_analyzer.ui.pages.settings.part4 import FIELD_RULES
        group = Adw.PreferencesGroup(title=_("Profil-Daten"))
        form.append(group)

        editable_fields = [
            "vorname", "mittelname", "nachname",
            "email", "telefon", "adresse",
        ]
        entries = {}
        for field in editable_fields:
            rules = FIELD_RULES.get(field, {})
            label = rules.get("label", field)
            value = str(profile.get(field, "") or "")
            row = Adw.EntryRow(title=label)
            row.set_text(value)
            group.add(row)
            entries[field] = (row, value)

        # Read-only info fields
        ro_group = Adw.PreferencesGroup(title=_("Konto-Informationen"))
        form.append(ro_group)

        for field, label in [
            ("username", "Username"),
            ("telegram_id", "Telegram-ID"),
            ("ausweis_id", _("Ausweis-ID")),
            ("created_at", _("Erstellt")),
            ("last_login", _("Letzter Login")),
        ]:
            val = str(profile.get(field, "") or "—")
            if field in ("created_at", "last_login"):
                val = val[:16] if val != "—" else val
            row = Adw.ActionRow(title=label, subtitle=val)
            ro_group.add(row)

        # Pending changes
        my_changes = profile.get("pending_changes", [])
        if my_changes:
            ch_group = Adw.PreferencesGroup(title=_("Ausstehende Änderungen"))
            form.append(ch_group)
            for ch in my_changes:
                ch_row = Adw.ActionRow(
                    title=ch.get("field_name", "?"),
                    subtitle=f"{ch.get('old_value', '')} → {ch.get('new_value', '')} ({ch.get('status', 'pending')})",
                )
                ch_group.add(ch_row)

        # File upload section (Foto + Ausweis)
        file_group = Adw.PreferencesGroup(title=_("Dateien"))
        form.append(file_group)

        for ftype, flabel in [("foto", _("Foto")), ("ausweis", _("Ausweis"))]:
            frow = Adw.ActionRow(title=flabel)
            existing = profile.get(f"{ftype}_path", "")
            if existing:
                frow.set_subtitle("✓ " + _("Vorhanden"))
            else:
                frow.set_subtitle(_("Nicht hochgeladen"))

            upload_btn = Gtk.Button(label=_("Hochladen"))
            upload_btn.set_valign(Gtk.Align.CENTER)

            def _on_upload(_btn, _ftype=ftype, _frow=frow):
                fd = Gtk.FileDialog()
                fd.set_title(f"{_ftype} " + _("hochladen"))
                def _on_chosen(d, result):
                    try:
                        f = d.open_finish(result)
                        if not f:
                            return
                        path = f.get_path()
                        _btn.set_sensitive(False)
                        _frow.set_subtitle(_("Wird hochgeladen..."))
                        def worker():
                            try:
                                with open(path, "rb") as fh:
                                    self.api_client._request(
                                        "POST",
                                        f"/users/{profile.get('id', 0)}/files/{_ftype}",
                                        files={"file": (f.get_basename(), fh)},
                                    )
                                GLib.idle_add(_frow.set_subtitle, "✓ " + _("Hochgeladen"))
                            except Exception as e:
                                logger.warning(f"Upload failed: {e}")
                                GLib.idle_add(_frow.set_subtitle, f"✗ {e}")
                            GLib.idle_add(_btn.set_sensitive, True)
                        threading.Thread(target=worker, daemon=True).start()
                    except GLib.Error:
                        pass
                fd.open(dialog, None, _on_chosen)

            upload_btn.connect("clicked", _on_upload)
            frow.add_suffix(upload_btn)
            file_group.add(frow)

        # Buttons
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
            halign=Gtk.Align.END,
        )
        box.append(btn_box)

        close_btn = Gtk.Button(label=_("Schließen"))
        close_btn.connect("clicked", lambda _: dialog.close())
        btn_box.append(close_btn)

        save_btn = Gtk.Button(label=_("Änderung anfragen"))
        save_btn.add_css_class("suggested-action")

        def on_save(_b):
            changes = {}
            for field, (row, old_val) in entries.items():
                new_val = row.get_text().strip()
                if new_val != old_val:
                    changes[field] = new_val
            if not changes:
                dialog.close()
                return
            save_btn.set_sensitive(False)

            def save_worker():
                for field, new_val in changes.items():
                    try:
                        self.api_client.update_my_profile(field, new_val)
                    except Exception as e:
                        logger.warning(f"Profile change request failed: {e}")
                GLib.idle_add(dialog.close)

            threading.Thread(target=save_worker, daemon=True).start()

        save_btn.connect("clicked", on_save)
        btn_box.append(save_btn)

        # Logout button at bottom of dialog
        logout_btn = Gtk.Button(label=_("Abmelden"))
        logout_btn.set_icon_name("system-log-out-symbolic")
        logout_btn.add_css_class("destructive-action")

        def on_logout(_b):
            try:
                dialog.force_close()
            except Exception:
                try:
                    dialog.close()
                except Exception:
                    pass
            GLib.idle_add(self._on_logout, None)

        logout_btn.connect("clicked", on_logout)
        btn_box.insert_child_after(logout_btn, close_btn)

        dialog.present(self)
        return False

    def _on_logout(self, _btn) -> None:
        """Logout and reset UI state. Shows login dialog (not auto-reconnect)."""
        client = self.api_client

        # Disconnect central WebSocket
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.disconnect()
        except Exception:
            pass

        if client:
            try:
                client.logout()
            except Exception as e:
                logger.warning(f"Logout failed: {e}")

        # Set force_login flag — persists across app restarts
        app = self.get_application()
        if app and hasattr(app, "config_manager"):
            app.config_manager.config.force_login = True
            app.config_manager.save()

        # Reset user display
        self._user_name_label.set_label(_("Nicht angemeldet"))
        self._user_role_label.set_visible(False)
        self._user_avatar.set_show_initials(False)
        self._current_user_info = None

        # Clear API client from all pages
        self.api_client = None
        for page_id, page in self._pages.items():
            if hasattr(page, "set_api_client"):
                try:
                    page.set_api_client(None)
                except Exception as e:
                    logger.debug(f"set_api_client(None) failed for {page_id}: {e}")

        # Show login dialog directly (NOT auto-connect which bypasses 2FA)
        app = self.get_application()
        if app and client:
            app._show_login_dialog_direct(client)

        logger.info("User logged out — login dialog shown")

    def set_api_client(self, client, user_info: dict | None = None) -> None:
        """API-Client an alle Seiten propagieren (nach Login).

        Lazy-Loading: Nur Client-Referenz setzen. Daten werden erst
        beim Tab-Wechsel geladen (nicht alle 16 Tabs gleichzeitig).
        """
        self.api_client = client

        # Client-Referenz an alle Seiten übergeben (KEIN refresh!)
        for page_id, page in self._pages.items():
            if hasattr(page, "set_api_client"):
                try:
                    page.set_api_client(client)
                except Exception as e:
                    logger.warning(f"set_api_client fehlgeschlagen für {page_id}: {e}")

        # TaskStatusBar mit Client versorgen
        self._task_status_bar.set_api_client(client)

        # Central WebSocket connection for all pages
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.connect_client(client)
        except Exception as e:
            logger.debug(f"WebSocket manager init: {e}")

        # User-Info in sidebar + popover
        if user_info:
            username = user_info.get("username", "")
            role = user_info.get("role", "")
            email = user_info.get("email", "")
            self._current_user_info = user_info
            if username:
                self._user_avatar.set_text(username)
                self._user_avatar.set_show_initials(True)
                self._user_name_label.set_label(username)
            if role:
                self._user_role_label.set_label(role.capitalize())
                self._user_role_label.set_visible(True)
                user_id = user_info.get("id", 0)
                for page_id, page in self._pages.items():
                    if hasattr(page, "set_user_role"):
                        try:
                            page.set_user_role(role)
                        except Exception as e:
                            logger.warning(f"set_user_role fehlgeschlagen für {page_id}: {e}")
                    # Pass user_id for Admin+ detection
                    if hasattr(page, "_viewer_user_id"):
                        page._viewer_user_id = user_id

        # NUR die aktive Seite refreshen
        if self._current_page_id:
            active = self._pages.get(self._current_page_id)
            if active and hasattr(active, "refresh"):
                try:
                    active.refresh()
                except Exception as e:
                    logger.warning(f"refresh() fehlgeschlagen für {self._current_page_id}: {e}")

        logger.info("API-Client propagiert, aktive Seite geladen")

    def _auto_detect_game_type(self) -> None:
        """Spieltyp anhand des Wochentags automatisch setzen."""
        _weekday_to_draw = {
            1: "tuesday", 2: "wednesday", 4: "friday", 5: "saturday",
        }
        today = date.today()
        today_wd = today.weekday()

        # An Ziehungstagen direkt den passenden Spieltyp wählen
        draw_day_str = _weekday_to_draw.get(today_wd)

        if not draw_day_str:
            # Nicht-Ziehungstag: nächsten Ziehungstag bestimmen
            for offset in range(1, 7):
                future_wd = (today_wd + offset) % 7
                if future_wd in _weekday_to_draw:
                    draw_day_str = _weekday_to_draw[future_wd]
                    break

        if draw_day_str:
            auto_config = game_for_draw_day(draw_day_str)
            if auto_config.game_type != self._current_game_type:
                self._current_game_type = auto_config.game_type
                config = get_config(self._current_game_type)
                self._game_button.set_label(config.display_name)
                self._window_title.set_subtitle(
                    f"{config.display_name} – Analyse & Vorhersage"
                )
                for page_id, page in self._pages.items():
                    if hasattr(page, "set_game_type"):
                        try:
                            page.set_game_type(self._current_game_type)
                        except Exception as e:
                            logger.warning(
                                f"Auto set_game_type fehlgeschlagen für {page_id}: {e}"
                            )
                logger.info(f"Auto-Erkennung: {config.display_name} (Wochentag {today_wd})")

    def _on_sidebar_toggled(self, button: Gtk.ToggleButton) -> None:
        """Sidebar ein-/ausblenden."""
        self._split_view.set_show_sidebar(button.get_active())

    def _setup_keyboard_shortcuts(self) -> None:
        """Globale Tastaturkuerzel registrieren (Ctrl+R, Escape)."""
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        """Tastendruck verarbeiten."""
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)

        if ctrl and keyval == Gdk.KEY_r:
            # Ctrl+R: Aktuelle Seite aktualisieren
            page = self._pages.get(self._current_page_id)
            if page and hasattr(page, "refresh"):
                try:
                    page.refresh()
                    logger.debug(f"Ctrl+R: refresh() auf {self._current_page_id}")
                except Exception as e:
                    logger.warning(f"Ctrl+R refresh fehlgeschlagen: {e}")
            return True

        if keyval == Gdk.KEY_Escape:
            # Escape: Laufende Operation abbrechen (falls Seite cancel_event hat)
            page = self._pages.get(self._current_page_id)
            if page and hasattr(page, "_cancel_event"):
                page._cancel_event.set()
                logger.debug(f"Escape: cancel_event gesetzt auf {self._current_page_id}")
                return True

        return False

    def _on_close_request(self, window) -> bool:
        """Ressourcen aufräumen und Fenstergröße speichern."""
        # Timer stoppen
        if hasattr(self, "_clock_timer_id") and self._clock_timer_id:
            GLib.source_remove(self._clock_timer_id)
            self._clock_timer_id = None

        # Seiten-Cleanup: cleanup() aufrufen + Timer und Threads stoppen
        _timer_attrs = ("_poll_timer_id", "_countdown_timer_id", "_poll_id")
        for page_id, page in self._pages.items():
            # cleanup() aufrufen, falls vorhanden
            if hasattr(page, "cleanup"):
                try:
                    page.cleanup()
                except Exception as e:
                    logger.warning(f"cleanup() fehlgeschlagen für {page_id}: {e}")
            if hasattr(page, "_cancel_event"):
                page._cancel_event.set()
            for attr in _timer_attrs:
                tid = getattr(page, attr, None)
                if tid:
                    GLib.source_remove(tid)
                    setattr(page, attr, None)

        # API-Client schliessen
        if self.api_client:
            try:
                self.api_client.close()
            except Exception as e:
                logger.debug(f"API-Client schliessen fehlgeschlagen: {e}")

        config = self.config_manager.config
        config.window_width = self.get_width()
        config.window_height = self.get_height()
        self.config_manager.save(config)
        return False  # Fenster darf schliessen

# TODO: Diese Datei ist >500Z weil: Hauptfenster mit Sidebar, Navigation, Profile-Dialog, 15 Seiten-Init
