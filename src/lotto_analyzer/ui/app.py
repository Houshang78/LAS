"""GTK4 Application – Einstiegspunkt der GUI.

Die App ist IMMER ein Client — kein Standalone-Modus.
Alle Daten kommen vom Server via API.
"""

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Gdk, Adw, Gio, GLib

from lotto_common.config import ConfigManager
from lotto_common.utils.logging_config import setup_logging, get_logger

logger = get_logger("app")


class LottoAnalyzerApp(Adw.Application):
    """Hauptanwendung – reiner Client, verbindet sich mit Server."""

    def __init__(self, server_address: str | None = None):
        super().__init__(
            application_id="de.lotto.analyzer",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.server_address = server_address
        self.config_manager = ConfigManager()
        self.window = None
        self.profile_manager = None
        self._font_css_provider: Gtk.CssProvider | None = None
        self._ssh_tunnel = None

        # App-Icon registrieren
        from pathlib import Path
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icon_data = Path(__file__).resolve().parents[3] / "data" / "icons" / "hicolor"
        installed_icon = Path("/usr/share/icons/hicolor")
        for icon_dir in [icon_data, installed_icon]:
            if icon_dir.exists():
                icon_theme.add_search_path(str(icon_dir))

        setup_logging(level="INFO")

        # i18n initialisieren (vor UI-Aufbau)
        from lotto_common.i18n import setup_i18n
        ui_lang = getattr(self.config_manager.config, "ui_language", "de")
        setup_i18n(ui_lang)

        logger.info(f"LottoAnalyzer Client gestartet (Sprache: {ui_lang})")

    def do_activate(self) -> None:
        """App-Fenster erstellen oder fokussieren."""
        if not self.window:
            self.config_manager.load()
            self._apply_font_settings()

            config = self.config_manager.config
            if config.first_run:
                self._show_setup_assistant()
            else:
                self._init_profile_manager()
                self._show_main_window()
        else:
            self.window.present()

    def _init_profile_manager(self) -> None:
        """ProfileManager initialisieren."""
        if not self.profile_manager:
            from lotto_analyzer.client.profile_manager import ProfileManager
            self.profile_manager = ProfileManager(self.config_manager)
            self.profile_manager.migrate_legacy_config()

    def _show_setup_assistant(self) -> None:
        """Setup-Assistent beim ersten Start — Server-Verbindungsdaten eingeben."""
        from lotto_analyzer.ui.setup_assistant import SetupAssistant
        assistant = SetupAssistant(
            application=self,
            config_manager=self.config_manager,
            on_complete=self._on_setup_complete,
        )
        assistant.present()
        self.window = assistant

    def _on_setup_complete(self) -> None:
        """Nach Setup-Abschluss: Verbindung zum Server herstellen."""
        config = self.config_manager.config
        config.first_run = False
        self.config_manager.save(config)
        logger.info("Setup abgeschlossen")

        self._init_profile_manager()

        if self.window:
            self.window.close()
        self._show_main_window()

    def _show_main_window(self) -> None:
        """Hauptfenster öffnen und Verbindung zum Server herstellen."""
        from lotto_analyzer.ui.window import MainWindow
        self.window = MainWindow(
            application=self,
            config_manager=self.config_manager,
            db=None,
            app_db=None,
            backtest_db=None,
            app_mode="client",
            server_address=self.server_address,
            profile_manager=self.profile_manager,
        )
        self.window.present()

        # Verbindung zum Server herstellen
        self._auto_connect()

    def _auto_connect(self) -> None:
        """Automatic connection to server.

        Uses default profile if available, otherwise falls back to config.
        Connection order: SSH-Tunnel (primary) → Localhost → HTTPS (fallback).
        """

        def worker():
            from lotto_analyzer.client.api_client import APIClient
            from lotto_common.models.ai_config import ServerConfig
            config = self.config_manager.config

            # Use default profile if available
            profile = None
            if self.profile_manager:
                profile = self.profile_manager.get_default_profile()

            if profile:
                host = profile.host or "localhost"
                port = profile.port or 8049
                api_key = profile.api_key or config.server.api_key
                use_https = profile.use_https
                use_ssh = profile.use_ssh
                ssh_user = profile.ssh_user
                ssh_host = profile.ssh_host or host
                ssh_port = profile.ssh_port or 22
                ssh_key = profile.ssh_key_path
                logger.info(f"Using profile: {profile.name}")
            else:
                host = config.server.host or "127.0.0.1"
                port = config.server.port or 8049
                api_key = config.server.api_key
                use_https = config.server.use_https
                use_ssh = bool(getattr(config.server, "ssh_user", ""))
                ssh_user = getattr(config.server, "ssh_user", "")
                ssh_host = getattr(config.server, "ssh_host", host)
                ssh_port = getattr(config.server, "ssh_port", 22)
                ssh_key = getattr(config.server, "ssh_key_path", "")

            client = None
            ok, msg = False, ""

            # 1. SSH-Tunnel (primary)
            if use_ssh and ssh_user and host.lower() not in ("localhost", "127.0.0.1", "::1", ""):
                try:
                    from lotto_analyzer.client.ssh_tunnel import SSHTunnel
                    local_port = port + 1000
                    tunnel = SSHTunnel(
                        ssh_host=ssh_host,
                        ssh_user=ssh_user,
                        remote_port=port,
                        local_port=local_port,
                        ssh_port=ssh_port,
                        ssh_key_path=ssh_key,
                    )
                    if tunnel.start():
                        sc = ServerConfig(
                            host="127.0.0.1", port=local_port,
                            api_key=api_key, use_https=False,
                        )
                        c = APIClient(sc)
                        ok, msg = c.test_connection()
                        if ok:
                            client = c
                            self._ssh_tunnel = tunnel
                            logger.info(
                                f"Connected via SSH tunnel: "
                                f"{ssh_user}@{ssh_host}:{ssh_port} → localhost:{local_port}"
                            )
                        else:
                            tunnel.stop()
                            c.close()
                            logger.warning(f"SSH tunnel up, but API unreachable: {msg}")
                    else:
                        logger.warning("SSH tunnel could not be started")
                except Exception as e:
                    logger.warning(f"SSH tunnel failed: {e}")

            # 2. Localhost direct (HTTPS with retry)
            if not client and host.lower() in ("localhost", "127.0.0.1", "::1", ""):
                import time as _time
                for attempt in range(3):
                    try:
                        sc = ServerConfig(
                            host="127.0.0.1", port=port,
                            api_key=api_key, use_https=True,
                        )
                        c = APIClient(sc)
                        ok, msg = c.test_connection()
                        if ok:
                            client = c
                            logger.info(f"Connected via localhost:{port} (HTTPS)")
                            break
                        c.close()
                    except Exception as e:
                        msg = str(e)
                    if not client and attempt < 2:
                        logger.info(f"Localhost attempt {attempt + 1}/3 failed, retry in 2s...")
                        _time.sleep(2)

            # 3. Remote direct (HTTPS or configured protocol)
            if not client and host.lower() not in ("localhost", "127.0.0.1", "::1", ""):
                try:
                    sc = ServerConfig(host=host, port=port, api_key=api_key, use_https=use_https)
                    c = APIClient(sc)
                    ok, msg = c.test_connection()
                    if ok:
                        client = c
                        logger.info(f"Connected via {'HTTPS' if use_https else 'HTTP'}: {host}:{port}")
                    else:
                        c.close()
                except Exception as e:
                    msg = str(e)

            # Trust on First Use: fetch and cache server's public cert
            if client:
                client.fetch_and_trust_server_cert()

            GLib.idle_add(self._on_auto_connect_result, ok, msg, client)

        threading.Thread(target=worker, daemon=True).start()

    def _on_auto_connect_result(self, ok: bool, msg: str, client) -> bool:
        """Ergebnis des Verbindungsaufbaus (Main-Thread)."""
        if ok and client:
            logger.info(f"Verbunden: {msg}")
            self._show_login_dialog(client)
        else:
            logger.error(f"Verbindung fehlgeschlagen: {msg}")
            self._show_connection_error(msg)
        return False

    def _show_connection_error(self, message: str) -> None:
        """Dialog bei fehlgeschlagener Verbindung — Server-Daten bearbeiten."""
        from lotto_analyzer.ui.dialogs.connection_dialog import ConnectionErrorDialog
        dialog = ConnectionErrorDialog(
            config_manager=self.config_manager,
            error_message=message,
            on_connected=self._show_login_dialog,
        )
        if self.window:
            dialog.present(self.window)

    def _show_login_dialog(self, client) -> None:
        """Login — auto-login only if user didn't explicitly log out."""
        if not client:
            return
        # Check if user explicitly logged out — if so, show login dialog
        if getattr(self.config_manager.config, "force_login", False):
            logger.info("User logged out previously — showing login dialog")
            self._show_login_dialog_direct(client)
            return
        self._localhost_trust_login(client)

    def _localhost_trust_login(self, client) -> None:
        """Passwortloser Login für localhost-Verbindungen."""
        import getpass
        system_user = getpass.getuser()
        self._pending_client = client

        def worker():
            try:
                result = client.login_local(system_user)
                GLib.idle_add(self._on_login_success, result)
            except Exception as e:
                logger.warning(f"Trust-Login fehlgeschlagen: {e} — zeige Login-Dialog")
                GLib.idle_add(self._show_login_dialog_direct, client)

        threading.Thread(target=worker, daemon=True).start()

    def _show_login_dialog_direct(self, client) -> None:
        """Login-Dialog anzeigen (SSH-Key, Zertifikat, Passwort)."""
        if not client:
            return
        self._pending_client = client

        from lotto_analyzer.ui.dialogs.login_dialog import LoginDialog
        dialog = LoginDialog(
            client=client,
            on_success=self._on_login_success,
            config_manager=self.config_manager,
        )
        dialog.present(self.window)

    def _on_login_success(self, result: dict) -> None:
        """Login erfolgreich — API-Client an alle Seiten übergeben."""
        logger.info(f"Angemeldet als: {result.get('username')}")
        # Clear force_login flag (user is now authenticated)
        self.config_manager.config.force_login = False
        self.config_manager.save()
        client = getattr(self, "_pending_client", None)
        if client and self.window:
            self.window.set_api_client(client, user_info=result)

    def _apply_font_settings(self) -> None:
        """Globale Schrift-CSS initial anwenden (nur bei Nicht-Defaults)."""
        config = self.config_manager.config
        if config.font_size == 11 and not config.font_bold:
            return
        self._set_font_css(config.font_size, config.font_bold)

    def apply_font_settings(self) -> None:
        """Schrift-CSS live aktualisieren (nach Einstellungsänderung)."""
        display = Gdk.Display.get_default()
        if self._font_css_provider:
            Gtk.StyleContext.remove_provider_for_display(display, self._font_css_provider)
            self._font_css_provider = None
        config = self.config_manager.config
        if config.font_size == 11 and not config.font_bold:
            return
        self._set_font_css(config.font_size, config.font_bold)

    def _set_font_css(self, size: int, bold: bool) -> None:
        """CssProvider erstellen und global anwenden."""
        weight = "bold" if bold else "normal"
        css = f"* {{ font-size: {size}pt; font-weight: {weight}; }}"
        provider = Gtk.CssProvider()
        provider.load_from_string(css)
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self._font_css_provider = provider

    def do_shutdown(self) -> None:
        """App beenden — SSH-Tunnel aufräumen."""
        if self._ssh_tunnel:
            self._ssh_tunnel.stop()
            logger.info("SSH-Tunnel beim Beenden gestoppt")
        if self.profile_manager:
            self.profile_manager.disconnect()
        Adw.Application.do_shutdown(self)
