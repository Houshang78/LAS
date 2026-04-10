"""Login-Dialog: Zwei-Phasen-Login mit optionaler 2FA."""

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio

from lotto_analyzer.client.api_client import APIClient
from lotto_common.utils.logging_config import get_logger

logger = get_logger("login_dialog")

# Auth-Methoden-Index ↔ ConnectionProfile.auth_method
_AUTH_INDEX = {0: "password", 1: "api_key", 2: "ssh_key", 3: "certificate"}
_AUTH_REVERSE = {v: k for k, v in _AUTH_INDEX.items()}


class LoginDialog(Adw.Dialog):
    """Modal-Dialog für Benutzer-Login mit optionaler 2FA."""

    POLL_INTERVAL_MS = 10000  # 10s fallback (WS pushes instant 2FA updates)

    def __init__(self, client: APIClient, on_success=None, config_manager=None):
        super().__init__()
        self.set_title("Anmeldung")
        self.set_content_width(480)
        self.set_content_height(500)

        self._client = client
        self._on_success = on_success
        self._config_manager = config_manager
        self._challenge_id: str | None = None
        self._poll_timer_id: int | None = None
        self._polling_active = False

        self._build_ui()
        self._restore_saved_credentials()

    def _build_ui(self) -> None:
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        self._stack.set_transition_duration(300)
        self.set_child(self._stack)

        # ── Phase 1: Passwort ──
        self._stack.add_named(self._build_password_page(), "password")

        # ── Phase 2: 2FA-Code ──
        self._stack.add_named(self._build_2fa_page(), "twofa")

        self._stack.set_visible_child_name("password")

    def _build_password_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)

        title = Gtk.Label(label="Server-Anmeldung")
        title.add_css_class("title-2")
        box.append(title)

        group = Adw.PreferencesGroup()
        box.append(group)

        self._username = Adw.EntryRow(title="Benutzername")
        group.add(self._username)

        # Auth-Methode: Passwort, API-Key, SSH-Schlüssel, Zertifikat
        self._auth_method = Adw.ComboRow(title="Authentifizierung")
        auth_list = Gtk.StringList()
        auth_list.append("Passwort")
        auth_list.append("API-Key")
        auth_list.append("SSH-Schlüssel")
        auth_list.append("Zertifikat")
        self._auth_method.set_model(auth_list)
        self._auth_method.connect("notify::selected", self._on_auth_method_changed)
        group.add(self._auth_method)

        self._password = Adw.PasswordEntryRow(title="Passwort")
        self._password.connect("entry-activated", self._on_login)
        group.add(self._password)

        self._api_key_entry = Adw.PasswordEntryRow(title="API-Key")
        self._api_key_entry.connect("entry-activated", self._on_login)
        self._api_key_entry.set_visible(False)
        group.add(self._api_key_entry)

        # SSH-Key: Datei-Auswahl
        self._ssh_key_row = Adw.ActionRow(title="Private Key", subtitle="Datei wählen...")
        self._ssh_key_row.set_visible(False)
        ssh_key_btn = Gtk.Button(label="Datei wählen...")
        ssh_key_btn.set_tooltip_text("SSH Private Key Datei auswählen")
        ssh_key_btn.set_valign(Gtk.Align.CENTER)
        ssh_key_btn.connect("clicked", self._on_choose_ssh_key)
        self._ssh_key_row.add_suffix(ssh_key_btn)
        group.add(self._ssh_key_row)
        self._ssh_key_path: str = ""

        # Zertifikat: Cert-Datei + Key-Datei
        self._cert_row = Adw.ActionRow(title="Zertifikat (.crt)", subtitle="Datei wählen...")
        self._cert_row.set_visible(False)
        cert_btn = Gtk.Button(label="Datei wählen...")
        cert_btn.set_tooltip_text("Zertifikat-Datei (.crt) auswählen")
        cert_btn.set_valign(Gtk.Align.CENTER)
        cert_btn.connect("clicked", self._on_choose_cert)
        self._cert_row.add_suffix(cert_btn)
        group.add(self._cert_row)
        self._cert_path: str = ""

        self._cert_key_row = Adw.ActionRow(title="Zertifikat-Key (.key)", subtitle="Datei wählen...")
        self._cert_key_row.set_visible(False)
        cert_key_btn = Gtk.Button(label="Datei wählen...")
        cert_key_btn.set_tooltip_text("Zertifikat-Key-Datei (.key) auswählen")
        cert_key_btn.set_valign(Gtk.Align.CENTER)
        cert_key_btn.connect("clicked", self._on_choose_cert_key)
        self._cert_key_row.add_suffix(cert_key_btn)
        group.add(self._cert_key_row)
        self._cert_key_path: str = ""

        # ── Angemeldet bleiben ──
        self._remember_switch = Adw.SwitchRow(
            title="Angemeldet bleiben",
            subtitle="Zugangsdaten verschlüsselt speichern",
        )
        group.add(self._remember_switch)

        self._pw_error = Gtk.Label()
        self._pw_error.add_css_class("error")
        self._pw_error.set_selectable(True)
        self._pw_error.set_wrap(True)
        self._pw_error.set_visible(False)
        box.append(self._pw_error)

        self._pw_spinner = Gtk.Spinner()
        self._pw_spinner.set_visible(False)
        box.append(self._pw_spinner)

        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12, halign=Gtk.Align.CENTER,
        )
        box.append(btn_box)

        cancel_btn = Gtk.Button(label="Abbrechen")
        cancel_btn.set_tooltip_text("Anmeldung abbrechen")
        cancel_btn.connect("clicked", self._on_cancel)
        btn_box.append(cancel_btn)

        self._login_btn = Gtk.Button(label="Anmelden")
        self._login_btn.add_css_class("suggested-action")
        self._login_btn.connect("clicked", self._on_login)
        btn_box.append(self._login_btn)

        # "Passwort vergessen?" link
        forgot_btn = Gtk.Button(label="Passwort vergessen?")
        forgot_btn.add_css_class("flat")
        forgot_btn.add_css_class("link")
        forgot_btn.set_halign(Gtk.Align.CENTER)
        forgot_btn.connect("clicked", self._on_forgot_password)
        box.append(forgot_btn)

        return box

    def _on_auth_method_changed(self, combo: Adw.ComboRow, _pspec) -> None:
        """Sichtbarkeit aller 4 Auth-Varianten steuern."""
        selected = combo.get_selected()
        self._password.set_visible(selected == 0)
        self._api_key_entry.set_visible(selected == 1)
        self._ssh_key_row.set_visible(selected == 2)
        self._cert_row.set_visible(selected == 3)
        self._cert_key_row.set_visible(selected == 3)

    def _build_2fa_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)

        title = Gtk.Label(label="Zwei-Faktor-Authentifizierung")
        title.add_css_class("title-2")
        box.append(title)

        info = Gtk.Label(
            label="Ein Code wurde per Telegram gesendet.\n"
                  "Code eingeben oder in Telegram genehmigen.",
        )
        info.set_wrap(True)
        info.set_xalign(0)
        box.append(info)

        group = Adw.PreferencesGroup()
        box.append(group)

        self._code_entry = Adw.EntryRow(title="6-stelliger Code")
        self._code_entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        self._code_entry.connect("entry-activated", self._on_verify_code)
        group.add(self._code_entry)

        self._twofa_status = Gtk.Label(label="Warte auf Telegram-Bestätigung...")
        self._twofa_status.add_css_class("dim-label")
        box.append(self._twofa_status)

        self._twofa_error = Gtk.Label()
        self._twofa_error.add_css_class("error")
        self._twofa_error.set_selectable(True)
        self._twofa_error.set_wrap(True)
        self._twofa_error.set_visible(False)
        box.append(self._twofa_error)

        self._twofa_spinner = Gtk.Spinner()
        self._twofa_spinner.set_visible(False)
        box.append(self._twofa_spinner)

        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12, halign=Gtk.Align.CENTER,
        )
        box.append(btn_box)

        back_btn = Gtk.Button(label="Zurück")
        back_btn.set_tooltip_text("Zurück zur Passwort-Eingabe")
        back_btn.connect("clicked", self._on_back_to_password)
        btn_box.append(back_btn)

        self._verify_btn = Gtk.Button(label="Prüfen")
        self._verify_btn.add_css_class("suggested-action")
        self._verify_btn.connect("clicked", self._on_verify_code)
        btn_box.append(self._verify_btn)

        return box

    # ── Credentials speichern / laden ──

    def _get_default_profile(self):
        """Default-ConnectionProfile aus Config holen (oder None)."""
        if not self._config_manager:
            return None
        config = self._config_manager.config
        profiles = config.connection_profiles
        for p in profiles:
            if p.is_default:
                return p
        return profiles[0] if profiles else None

    def _restore_saved_credentials(self) -> None:
        """Gespeicherte Zugangsdaten ins Formular laden."""
        profile = self._get_default_profile()
        if not profile or not profile.remember_login:
            return

        # Username
        if profile.username:
            self._username.set_text(profile.username)

        # Auth-Methode
        idx = _AUTH_REVERSE.get(profile.auth_method, 0)
        self._auth_method.set_selected(idx)

        # Credentials je nach Methode
        if profile.auth_method == "password" and profile.saved_password:
            self._password.set_text(profile.saved_password)
        elif profile.auth_method == "api_key" and profile.api_key:
            self._api_key_entry.set_text(profile.api_key)
        elif profile.auth_method == "ssh_key" and profile.auth_key_path:
            self._ssh_key_path = profile.auth_key_path
            self._ssh_key_row.set_subtitle(profile.auth_key_path.split("/")[-1])
        elif profile.auth_method == "certificate":
            if profile.cert_path:
                self._cert_path = profile.cert_path
                self._cert_row.set_subtitle(profile.cert_path.split("/")[-1])
            if profile.cert_key_path:
                self._cert_key_path = profile.cert_key_path
                self._cert_key_row.set_subtitle(profile.cert_key_path.split("/")[-1])

        self._remember_switch.set_active(True)
        logger.info(f"Gespeicherte Credentials geladen (Methode: {profile.auth_method})")

        # Auto-Login wenn Credentials vollständig
        if profile.username and (profile.saved_password or profile.api_key):
            GLib.idle_add(self._on_login)

    def _save_credentials(self) -> None:
        """Aktuelle Zugangsdaten verschlüsselt im Profil speichern."""
        if not self._config_manager:
            return

        profile = self._get_default_profile()
        if not profile:
            return

        remember = self._remember_switch.get_active()
        profile.remember_login = remember
        profile.username = self._username.get_text().strip()

        selected = self._auth_method.get_selected()
        profile.auth_method = _AUTH_INDEX.get(selected, "password")

        if remember:
            # Credentials je nach Methode speichern
            if selected == 0:
                profile.saved_password = self._password.get_text()
            else:
                profile.saved_password = ""

            if selected == 1:
                profile.api_key = self._api_key_entry.get_text().strip()

            if selected == 2:
                profile.auth_key_path = self._ssh_key_path

            if selected == 3:
                profile.cert_path = self._cert_path
                profile.cert_key_path = self._cert_key_path
        else:
            # Credentials löschen
            profile.saved_password = ""

        try:
            self._config_manager.save()
            logger.info(f"Credentials gespeichert (remember={remember})")
        except Exception as e:
            logger.error(f"Credentials speichern fehlgeschlagen: {e}")

    # ── Phase 1: Login ──

    def _on_login(self, *_args) -> None:
        username = self._username.get_text().strip()
        selected = self._auth_method.get_selected()

        if not username:
            self._show_pw_error("Bitte Benutzername eingeben")
            return

        if selected == 0:
            # Passwort
            password = self._password.get_text()
            if not password:
                self._show_pw_error("Bitte Passwort eingeben")
                return
            self._start_login_worker(
                lambda: self._client.login(username, password),
            )
        elif selected == 1:
            # API-Key
            api_key = self._api_key_entry.get_text().strip()
            if not api_key:
                self._show_pw_error("Bitte API-Key eingeben")
                return
            self._start_login_worker(
                lambda: self._client.login(username, None, api_key=api_key),
            )
        elif selected == 2:
            # SSH-Schlüssel
            if not self._ssh_key_path:
                self._show_pw_error("Bitte SSH-Key-Datei wählen")
                return
            self._start_login_worker(
                lambda: self._client.login_ssh_key(username, self._ssh_key_path),
            )
        elif selected == 3:
            # Zertifikat
            if not self._cert_path or not self._cert_key_path:
                self._show_pw_error("Bitte Zertifikat und Key wählen")
                return
            self._start_login_worker(
                lambda: self._client.login_certificate(
                    username, self._cert_path, self._cert_key_path,
                ),
            )

    def _start_login_worker(self, login_fn) -> None:
        """Login im Hintergrund-Thread ausführen."""
        self._login_btn.set_sensitive(False)
        self._pw_error.set_visible(False)
        self._pw_spinner.set_visible(True)
        self._pw_spinner.start()

        def worker():
            try:
                result = login_fn()
                GLib.idle_add(self._on_login_result, result)
            except Exception as e:
                msg = str(e)
                if "401" in msg:
                    msg = "Authentifizierung fehlgeschlagen"
                elif "423" in msg:
                    msg = "Account gesperrt – bitte später versuchen"
                elif "410" in msg:
                    msg = "Challenge abgelaufen"
                elif "400" in msg:
                    msg = "Ungültige Anfrage"
                GLib.idle_add(self._on_login_error, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_login_result(self, result: dict) -> bool:
        self._pw_spinner.stop()
        self._pw_spinner.set_visible(False)

        if result.get("status") == "2fa_required":
            # 2FA noetig — zu Phase 2 wechseln
            self._challenge_id = result["challenge_id"]
            self._stack.set_visible_child_name("twofa")
            self._twofa_error.set_visible(False)
            self._twofa_status.set_label("Warte auf Telegram-Bestätigung...")
            self._start_polling()
            return False

        # Normaler Login ohne 2FA — Credentials speichern
        self._save_credentials()
        logger.info(f"Login erfolgreich: {result.get('username')}")
        if self._on_success:
            self._on_success(result)
        self.close()
        return False

    def _on_login_error(self, message: str) -> bool:
        self._pw_spinner.stop()
        self._pw_spinner.set_visible(False)
        self._login_btn.set_sensitive(True)
        self._show_pw_error(message)
        return False

    def _show_pw_error(self, message: str) -> None:
        self._pw_error.set_text(message)
        self._pw_error.set_visible(True)

    # ── Phase 2: 2FA-Code prüfen ──

    def _on_verify_code(self, *_args) -> None:
        code = self._code_entry.get_text().strip()
        if not code or not self._challenge_id:
            self._show_2fa_error("Bitte Code eingeben")
            return

        self._verify_btn.set_sensitive(False)
        self._twofa_error.set_visible(False)
        self._twofa_spinner.set_visible(True)
        self._twofa_spinner.start()

        challenge_id = self._challenge_id

        def worker():
            try:
                result = self._client.verify_2fa(challenge_id, code)
                GLib.idle_add(self._on_2fa_success, result)
            except Exception as e:
                msg = str(e)
                if "401" in msg:
                    msg = "Code falsch"
                elif "410" in msg:
                    msg = "Challenge abgelaufen — bitte erneut anmelden"
                elif "429" in msg:
                    msg = "Zu viele Fehlversuche"
                elif "403" in msg:
                    msg = "Login per Telegram abgelehnt"
                GLib.idle_add(self._on_2fa_error, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_2fa_success(self, result: dict) -> bool:
        self._stop_polling()
        self._twofa_spinner.stop()
        self._twofa_spinner.set_visible(False)
        # Credentials speichern (auch nach 2FA)
        self._save_credentials()
        logger.info(f"2FA erfolgreich: {result.get('username')}")
        if self._on_success:
            self._on_success(result)
        self.close()
        return False

    def _on_2fa_error(self, message: str) -> bool:
        self._twofa_spinner.stop()
        self._twofa_spinner.set_visible(False)
        self._verify_btn.set_sensitive(True)
        self._show_2fa_error(message)
        return False

    def _show_2fa_error(self, message: str) -> None:
        self._twofa_error.set_text(message)
        self._twofa_error.set_visible(True)

    # ── Polling: Telegram-Button-Genehmigung ──

    def _start_polling(self) -> None:
        self._polling_active = True
        # Try WS for instant 2FA status push
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            if self._client:
                ui_ws_manager.connect_client(self._client)
            ui_ws_manager.on("2fa_update", self._on_ws_2fa_update)
        except Exception:
            pass
        self._poll_timer_id = GLib.timeout_add(
            self.POLL_INTERVAL_MS, self._poll_2fa,
        )

    def _on_ws_2fa_update(self, data: dict) -> bool:
        """Handle WS 2fa_update — instant poll on matching challenge."""
        if data.get("challenge_id") == self._challenge_id:
            self._poll_2fa()
        return False

    def _stop_polling(self) -> None:
        self._polling_active = False
        if self._poll_timer_id is not None:
            GLib.source_remove(self._poll_timer_id)
            self._poll_timer_id = None
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("2fa_update", self._on_ws_2fa_update)
        except Exception:
            pass

    def _poll_2fa(self) -> bool:
        """Pollt den 2FA-Status alle 2 Sekunden."""
        if not self._polling_active or not self._challenge_id:
            return False  # Timer stoppen

        challenge_id = self._challenge_id

        def worker():
            try:
                result = self._client.poll_2fa_status(challenge_id)
                if result.get("token"):
                    GLib.idle_add(self._on_2fa_success, result)
                elif result.get("status") == "pending":
                    remaining = result.get("remaining_seconds", 0)
                    GLib.idle_add(
                        self._twofa_status.set_label,
                        f"Warte auf Telegram-Bestätigung... ({remaining}s)",
                    )
            except Exception as e:
                msg = str(e)
                if "403" in msg:
                    GLib.idle_add(self._on_2fa_error, "Login per Telegram abgelehnt")
                    GLib.idle_add(self._stop_polling)
                elif "410" in msg:
                    GLib.idle_add(self._on_2fa_error, "Challenge abgelaufen")
                    GLib.idle_add(self._stop_polling)
                elif "429" in msg:
                    GLib.idle_add(self._on_2fa_error, "Zu viele Fehlversuche")
                    GLib.idle_add(self._stop_polling)

        threading.Thread(target=worker, daemon=True).start()
        return True  # Timer weiterlaufen lassen

    def _on_back_to_password(self, *_args) -> None:
        """Zurück zur Passwort-Eingabe."""
        self._stop_polling()
        self._challenge_id = None
        self._code_entry.set_text("")
        self._twofa_error.set_visible(False)
        self._login_btn.set_sensitive(True)
        self._stack.set_visible_child_name("password")

    # ── Datei-Auswahl für SSH-Key und Zertifikat ──

    def _on_choose_ssh_key(self, button: Gtk.Button) -> None:
        self._open_file_dialog(
            title="SSH Private Key wählen",
            callback=self._on_ssh_key_chosen,
            initial_folder="~/.ssh",
        )

    def _on_ssh_key_chosen(self, path: str) -> None:
        self._ssh_key_path = path
        self._ssh_key_row.set_subtitle(path.split("/")[-1])

    def _on_choose_cert(self, button: Gtk.Button) -> None:
        self._open_file_dialog(
            title="Zertifikat wählen (.crt)",
            callback=self._on_cert_chosen,
        )

    def _on_cert_chosen(self, path: str) -> None:
        self._cert_path = path
        self._cert_row.set_subtitle(path.split("/")[-1])

    def _on_choose_cert_key(self, button: Gtk.Button) -> None:
        self._open_file_dialog(
            title="Zertifikat-Key wählen (.key)",
            callback=self._on_cert_key_chosen,
        )

    def _on_cert_key_chosen(self, path: str) -> None:
        self._cert_key_path = path
        self._cert_key_row.set_subtitle(path.split("/")[-1])

    def _open_file_dialog(self, title: str, callback, initial_folder: str = "") -> None:
        """FileDialog oeffnen und Callback mit Pfad aufrufen."""
        dialog = Gtk.FileDialog(title=title)
        if initial_folder:
            from pathlib import Path
            folder = Path(initial_folder).expanduser()
            if folder.exists():
                dialog.set_initial_folder(Gio.File.new_for_path(str(folder)))

        window = self.get_root()
        dialog.open(window, None, lambda d, res: self._on_file_selected(d, res, callback))

    def _on_file_selected(self, dialog, result, callback) -> None:
        try:
            file = dialog.open_finish(result)
            if file:
                callback(file.get_path())
        except Exception as e:
            logger.debug(f"Dateiauswahl abgebrochen: {e}")

    def _on_cancel(self, _btn) -> None:
        """Cancel login — close dialog and quit application."""
        self.close()
        window = self.get_root()
        if window:
            app = window.get_application()
            if app:
                app.quit()

    # ── Password Reset Flow ──

    def _on_forgot_password(self, _btn) -> None:
        """Show password reset dialog."""
        self._show_reset_dialog()

    def _show_reset_dialog(self) -> None:
        """Separate dialog for password reset with Telegram 2FA."""
        reset_dialog = Adw.Dialog()
        reset_dialog.set_title("Passwort zurücksetzen")
        reset_dialog.set_content_width(440)
        reset_dialog.set_content_height(520)

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        reset_dialog.set_child(stack)

        # Page 1: Username input
        p1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        p1.set_margin_top(24)
        p1.set_margin_bottom(24)
        p1.set_margin_start(24)
        p1.set_margin_end(24)

        p1_title = Gtk.Label(label="Passwort vergessen")
        p1_title.add_css_class("title-2")
        p1.append(p1_title)

        p1_info = Gtk.Label(
            label="Benutzername eingeben. Ein Code wird an dein\n"
                  "Telegram gesendet um das neue Passwort zu bestätigen.",
        )
        p1_info.set_wrap(True)
        p1_info.set_xalign(0)
        p1.append(p1_info)

        p1_group = Adw.PreferencesGroup()
        p1.append(p1_group)
        reset_user_entry = Adw.EntryRow(title="Benutzername")
        reset_user_entry.set_text(self._username.get_text())
        p1_group.add(reset_user_entry)

        p1_error = Gtk.Label()
        p1_error.add_css_class("error")
        p1_error.set_selectable(True)
        p1_error.set_wrap(True)
        p1_error.set_visible(False)
        p1.append(p1_error)

        p1_spinner = Gtk.Spinner()
        p1_spinner.set_visible(False)
        p1.append(p1_spinner)

        p1_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                          halign=Gtk.Align.CENTER)
        p1.append(p1_btns)
        p1_cancel = Gtk.Button(label="Abbrechen")
        p1_cancel.connect("clicked", lambda _: reset_dialog.close())
        p1_btns.append(p1_cancel)

        p1_send = Gtk.Button(label="Code senden")
        p1_send.add_css_class("suggested-action")
        p1_btns.append(p1_send)
        stack.add_named(p1, "username")

        # Page 2: Code + new password
        p2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        p2.set_margin_top(24)
        p2.set_margin_bottom(24)
        p2.set_margin_start(24)
        p2.set_margin_end(24)

        p2_title = Gtk.Label(label="Neues Passwort setzen")
        p2_title.add_css_class("title-2")
        p2.append(p2_title)

        p2_info = Gtk.Label(label="Code aus Telegram eingeben und neues Passwort wählen.")
        p2_info.set_wrap(True)
        p2_info.set_xalign(0)
        p2.append(p2_info)

        p2_group = Adw.PreferencesGroup()
        p2.append(p2_group)
        reset_code = Adw.EntryRow(title="6-stelliger Code")
        reset_code.set_input_purpose(Gtk.InputPurpose.DIGITS)
        p2_group.add(reset_code)

        reset_pw1 = Adw.PasswordEntryRow(title="Neues Passwort")
        p2_group.add(reset_pw1)
        reset_pw2 = Adw.PasswordEntryRow(title="Passwort bestätigen")
        p2_group.add(reset_pw2)

        p2_status = Gtk.Label(label="Warte auf Telegram-Bestätigung...")
        p2_status.add_css_class("dim-label")
        p2.append(p2_status)

        p2_error = Gtk.Label()
        p2_error.add_css_class("error")
        p2_error.set_selectable(True)
        p2_error.set_wrap(True)
        p2_error.set_visible(False)
        p2.append(p2_error)

        p2_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                          halign=Gtk.Align.CENTER)
        p2.append(p2_btns)
        p2_back = Gtk.Button(label="Zurück")
        p2_back.connect("clicked", lambda _: stack.set_visible_child_name("username"))
        p2_btns.append(p2_back)

        p2_confirm = Gtk.Button(label="Passwort ändern")
        p2_confirm.add_css_class("suggested-action")
        p2_btns.append(p2_confirm)
        stack.add_named(p2, "confirm")

        # State
        _state = {"challenge_id": None, "poll_id": None}

        def on_send(_btn):
            username = reset_user_entry.get_text().strip()
            if not username:
                p1_error.set_label("Benutzername eingeben")
                p1_error.set_visible(True)
                return
            p1_send.set_sensitive(False)
            p1_error.set_visible(False)
            p1_spinner.set_visible(True)
            p1_spinner.start()

            def worker():
                try:
                    result = self._client.request_password_reset(username)
                    GLib.idle_add(_on_send_done, result, None)
                except Exception as e:
                    GLib.idle_add(_on_send_done, None, str(e))

            threading.Thread(target=worker, daemon=True).start()

        def _on_send_done(result, error):
            p1_spinner.stop()
            p1_spinner.set_visible(False)
            p1_send.set_sensitive(True)
            if error:
                p1_error.set_label(error)
                p1_error.set_visible(True)
                return
            _state["challenge_id"] = result.get("challenge_id")
            stack.set_visible_child_name("confirm")
            # Start polling for Telegram approval
            _start_poll()
            return False

        def _start_poll():
            if _state["poll_id"]:
                return
            def poll():
                if not _state["challenge_id"]:
                    return False
                try:
                    data = self._client.poll_2fa_status(_state["challenge_id"])
                    status = data.get("status", "pending")
                    remaining = data.get("remaining_seconds", 0)
                    if status == "approved" or data.get("token"):
                        GLib.idle_add(p2_status.set_label, "✓ Per Telegram genehmigt")
                        return False
                    elif status in ("denied", "expired", "failed"):
                        GLib.idle_add(p2_error.set_label, f"Status: {status}")
                        GLib.idle_add(p2_error.set_visible, True)
                        return False
                    GLib.idle_add(
                        p2_status.set_label,
                        f"Warte auf Telegram... ({remaining}s)",
                    )
                except Exception as e:
                    logger.debug(f"Reset poll error: {e}")
                return True
            _state["poll_id"] = GLib.timeout_add_seconds(2, poll)
            # Auto-stop after 5 minutes
            def _auto_stop_poll():
                if _state["poll_id"]:
                    GLib.source_remove(_state["poll_id"])
                    _state["poll_id"] = None
                return False
            GLib.timeout_add_seconds(300, _auto_stop_poll)

        def on_confirm(_btn):
            code = reset_code.get_text().strip()
            pw1 = reset_pw1.get_text()
            pw2 = reset_pw2.get_text()
            if pw1 != pw2:
                p2_error.set_label("Passwörter stimmen nicht überein")
                p2_error.set_visible(True)
                return
            if len(pw1) < 8:
                p2_error.set_label("Mindestens 8 Zeichen")
                p2_error.set_visible(True)
                return
            p2_confirm.set_sensitive(False)
            p2_error.set_visible(False)

            def worker():
                try:
                    result = self._client.confirm_password_reset(
                        _state["challenge_id"], code, pw1,
                    )
                    GLib.idle_add(_on_confirm_done, result, None)
                except Exception as e:
                    GLib.idle_add(_on_confirm_done, None, str(e))

            threading.Thread(target=worker, daemon=True).start()

        def _on_confirm_done(result, error):
            p2_confirm.set_sensitive(True)
            if error:
                p2_error.set_label(error)
                p2_error.set_visible(True)
                return
            # Success — close reset dialog, show message
            if _state["poll_id"]:
                GLib.source_remove(_state["poll_id"])
            p2_status.set_label("✓ Passwort zurückgesetzt — bitte neu einloggen")
            p2_status.add_css_class("success")
            p2_confirm.set_visible(False)
            # Auto-close after 2 seconds
            GLib.timeout_add_seconds(2, lambda: reset_dialog.close() or False)
            return False

        p1_send.connect("clicked", on_send)
        p2_confirm.connect("clicked", on_confirm)

        window = self.get_root()
        if window:
            reset_dialog.present(window)

    def close(self) -> None:
        self._stop_polling()
        super().close()

# TODO: Diese Datei ist >500Z weil: Login+2FA+QR-Code Flow in einem Dialog, schwer aufzuteilen
