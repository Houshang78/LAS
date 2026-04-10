"""Setup-Assistent beim ersten Start der App."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from lotto_common.config import ConfigManager
from lotto_common.models.ai_config import AIMode, AIModel, AppMode
from lotto_common.utils.logging_config import get_logger

logger = get_logger("setup")

_LOCALHOST_NAMES = ("localhost", "127.0.0.1", "::1", "")


class SetupAssistant(Adw.Window):
    """Wizard für den ersten Start: Verbindung, DB, AI konfigurieren."""

    def __init__(
        self,
        application: Adw.Application,
        config_manager: ConfigManager,
        on_complete: callable,
    ):
        super().__init__(
            application=application,
            title="LottoAnalyzer – Einrichtung",
            default_width=600,
            default_height=500,
            modal=True,
        )
        self.config_manager = config_manager
        self.on_complete = on_complete
        self._current_step = 0

        self._build_ui()

    def _is_localhost(self) -> bool:
        """Prüft ob die eingegebene Adresse localhost ist."""
        host = self._host_entry.get_text().strip().lower()
        return host in _LOCALHOST_NAMES

    def _get_steps(self) -> list[str]:
        """Aktuelle Schritt-Liste basierend auf Host."""
        if self._is_localhost():
            return ["step_connection", "step_db", "step_ai", "step_done"]
        else:
            return ["step_connection", "step_ai", "step_done"]

    def _build_ui(self) -> None:
        """UI aufbauen: HeaderBar + Stack für Schritte."""
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(outer)

        # HeaderBar
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(
            title="Einrichtung",
            subtitle="Schritt 1 von 4",
        ))
        self._header_title = header.get_title_widget()
        outer.append(header)

        # Stack für Schritte
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        outer.append(self._stack)

        # Schritt 1: Verbindung
        self._stack.add_named(self._build_step_connection(), "step_connection")
        # Schritt 2: DB-Info (nur bei localhost)
        self._stack.add_named(self._build_step_db(), "step_db")
        # Schritt 3: AI-Einstellungen
        self._stack.add_named(self._build_step_ai(), "step_ai")
        # Schritt 4: Fertig
        self._stack.add_named(self._build_step_done(), "step_done")

        # Navigation-Buttons
        nav_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.END,
        )
        nav_box.set_margin_top(12)
        nav_box.set_margin_bottom(12)
        nav_box.set_margin_end(12)

        self._btn_back = Gtk.Button(label="Zurück")
        self._btn_back.connect("clicked", self._on_back)
        self._btn_back.set_sensitive(False)
        nav_box.append(self._btn_back)

        self._btn_next = Gtk.Button(label="Weiter")
        self._btn_next.add_css_class("suggested-action")
        self._btn_next.connect("clicked", self._on_next)
        nav_box.append(self._btn_next)

        outer.append(nav_box)

    def _build_step_connection(self) -> Gtk.Widget:
        """Schritt 1: Verbindung konfigurieren."""
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Verbindung",
            description="Wohin soll sich LottoAnalyzer verbinden?",
        )
        page.add(group)

        # Server-Adresse
        self._host_entry = Adw.EntryRow(title="Server-Adresse")
        self._host_entry.set_text("localhost")
        group.add(self._host_entry)

        # HTTPS Switch
        self._https_switch = Adw.SwitchRow(
            title="HTTPS verwenden",
            subtitle="Verschlüsselte Verbindung zum Server",
        )
        self._https_switch.set_active(False)
        group.add(self._https_switch)

        # Port
        port_adj = Gtk.Adjustment(
            value=8049,
            lower=1,
            upper=65535,
            step_increment=1,
            page_increment=100,
        )
        self._port_spin = Adw.SpinRow(
            title="Port",
            adjustment=port_adj,
        )
        self._port_spin.set_digits(0)
        group.add(self._port_spin)

        # Info-Label
        info_group = Adw.PreferencesGroup()
        page.add(info_group)
        self._info_label = Gtk.Label(
            label="localhost = Lokaler Betrieb ohne Login (Admin-Modus)",
            wrap=True,
        )
        self._info_label.add_css_class("dim-label")
        self._info_label.set_margin_top(8)
        self._info_label.set_margin_bottom(8)
        self._info_label.set_margin_start(12)
        self._info_label.set_halign(Gtk.Align.START)
        info_group.add(self._info_label)

        # Host-Änderung: Info-Label aktualisieren
        self._host_entry.connect("changed", self._on_host_changed)

        return page

    def _on_host_changed(self, entry: Adw.EntryRow) -> None:
        """Info-Label aktualisieren wenn Host sich aendert."""
        if self._is_localhost():
            self._info_label.set_label(
                "localhost = Lokaler Betrieb ohne Login (Admin-Modus)"
            )
        else:
            self._info_label.set_label(
                "Remote-Server: Login mit Passwort/API-Key/Zertifikat erforderlich"
            )
        # Schritt-Zaehler aktualisieren
        steps = self._get_steps()
        self._header_title.set_subtitle(
            f"Schritt {self._current_step + 1} von {len(steps)}"
        )

    def _build_step_db(self) -> Gtk.Widget:
        """Schritt 2: Datenbank wird erstellt (nur bei localhost)."""
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Datenbank",
            description="SQLite-Datenbank wird automatisch erstellt.",
        )
        page.add(group)

        info = Adw.ActionRow(
            title="Speicherort",
            subtitle=str(self.config_manager.db_path),
        )
        info.add_prefix(Gtk.Image.new_from_icon_name("drive-harddisk-symbolic"))
        group.add(info)

        # Initialer Crawl
        crawl_group = Adw.PreferencesGroup(
            title="Historische Daten",
            description="Sollen alle Ziehungen ab 1955 geladen werden?",
        )
        page.add(crawl_group)

        self._crawl_switch = Adw.SwitchRow(
            title="Initialer Crawl nach Einrichtung",
            subtitle="Alle Samstags- und Mittwochs-Ziehungen herunterladen",
        )
        self._crawl_switch.set_active(True)
        crawl_group.add(self._crawl_switch)

        return page

    def _build_step_ai(self) -> Gtk.Widget:
        """Schritt 3: AI-Einstellungen."""
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="AI-Konfiguration",
            description="Claude für Analyse, Chat und Vorhersagen",
        )
        page.add(group)

        # AI-Modus
        self._ai_mode_api = Gtk.CheckButton()
        row_api = Adw.ActionRow(
            title="API-Modus",
            subtitle="Anthropic API mit Schlüssel (empfohlen)",
        )
        self._ai_mode_api.set_active(True)
        row_api.add_prefix(self._ai_mode_api)
        row_api.set_activatable_widget(self._ai_mode_api)
        group.add(row_api)

        self._ai_mode_cli = Gtk.CheckButton()
        self._ai_mode_cli.set_group(self._ai_mode_api)
        row_cli = Adw.ActionRow(
            title="CLI-Modus",
            subtitle="Lokale Claude-CLI verwenden",
        )
        row_cli.add_prefix(self._ai_mode_cli)
        row_cli.set_activatable_widget(self._ai_mode_cli)
        group.add(row_cli)

        # API-Key
        self._api_key_entry = Adw.PasswordEntryRow(
            title="API-Schlüssel",
        )
        group.add(self._api_key_entry)

        # Modell-Auswahl
        model_group = Adw.PreferencesGroup(title="Modell")
        page.add(model_group)

        self._model_dropdown = Adw.ComboRow(title="Claude-Modell")
        model_names = Gtk.StringList()
        self._model_values = []
        for model_id, display in AIModel.display_names().items():
            model_names.append(display)
            self._model_values.append(model_id)
        self._model_dropdown.set_model(model_names)
        self._model_dropdown.set_selected(2)  # Sonnet 4 als Default
        model_group.add(self._model_dropdown)

        return page

    def _build_step_done(self) -> Gtk.Widget:
        """Letzter Schritt: Zusammenfassung + Fertig."""
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Einrichtung abgeschlossen!",
            description="LottoAnalyzer ist bereit.",
        )
        page.add(group)

        self._summary_label = Gtk.Label(
            label="Konfiguration wird gespeichert...",
            wrap=True,
        )
        self._summary_label.set_margin_top(24)
        self._summary_label.set_margin_bottom(24)

        row = Adw.ActionRow(title="Bereit")
        row.add_prefix(Gtk.Image.new_from_icon_name("emblem-ok-symbolic"))
        row.set_subtitle("Klicke 'Fertig' um zu starten")
        group.add(row)

        return page

    def _on_next(self, button: Gtk.Button) -> None:
        """Nächster Schritt oder Fertig."""
        steps = self._get_steps()
        self._current_step += 1

        if self._current_step >= len(steps):
            self._finish_setup()
            return

        self._stack.set_visible_child_name(steps[self._current_step])
        self._header_title.set_subtitle(
            f"Schritt {self._current_step + 1} von {len(steps)}"
        )
        self._btn_back.set_sensitive(True)

        if self._current_step == len(steps) - 1:
            self._btn_next.set_label("Fertig")
            self._btn_next.remove_css_class("suggested-action")
            self._btn_next.add_css_class("suggested-action")
        else:
            self._btn_next.set_label("Weiter")

    def _on_back(self, button: Gtk.Button) -> None:
        """Vorheriger Schritt."""
        steps = self._get_steps()
        if self._current_step > 0:
            self._current_step -= 1
            self._stack.set_visible_child_name(steps[self._current_step])
            self._header_title.set_subtitle(
                f"Schritt {self._current_step + 1} von {len(steps)}"
            )
            self._btn_next.set_label("Weiter")
            if self._current_step == 0:
                self._btn_back.set_sensitive(False)

    def _finish_setup(self) -> None:
        """Konfiguration speichern und Setup beenden."""
        config = self.config_manager.config

        # Verbindung
        host = self._host_entry.get_text().strip() or "localhost"
        config.server.host = host
        config.server.port = int(self._port_spin.get_value())
        config.server.use_https = self._https_switch.get_active()

        # Modus: immer Client (Server laeuft separat)
        config.app_mode = AppMode.CLIENT

        # AI
        if self._ai_mode_api.get_active():
            config.ai.mode = AIMode.API
        else:
            config.ai.mode = AIMode.CLI

        config.ai.api_key = self._api_key_entry.get_text()

        idx = self._model_dropdown.get_selected()
        if 0 <= idx < len(self._model_values):
            config.ai.model = self._model_values[idx]

        config.first_run = False
        self.config_manager.save(config)

        logger.info(f"Setup abgeschlossen: Modus={config.app_mode.value}, Host={host}")
        self.on_complete()
