"""UI-Seite server_admin: part2 Mixin."""

from __future__ import annotations

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_common.config import ConfigManager
from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config


logger = get_logger("server_admin.part2")
from lotto_common.models.user import ALL_PERMISSIONS, DEFAULT_USER_PERMISSIONS

from lotto_analyzer.ui.ui_helpers import show_error_toast


class Part2Mixin:
    """Part2 Mixin."""

    # ── Benutzerverwaltung ──

    def _on_create_user(self, button: Gtk.Button) -> None:
        """Dialog zum Erstellen eines neuen Benutzers."""
        dialog = Adw.Dialog()
        dialog.set_title(_("Neuer Benutzer"))
        dialog.set_content_width(self._DIALOG_WIDTH)
        dialog.set_content_height(550)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        dialog.set_child(scrolled)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        scrolled.set_child(box)

        group = Adw.PreferencesGroup()
        box.append(group)

        username_entry = Adw.EntryRow(title=_("Benutzername"))
        group.add(username_entry)

        password_entry = Adw.PasswordEntryRow(title=_("Passwort"))
        group.add(password_entry)

        role_combo = Adw.ComboRow(title=_("Rolle"))
        role_list = Gtk.StringList()
        for r in USER_ROLES:
            role_list.append(r)
        role_combo.set_model(role_list)
        group.add(role_combo)

        # Permissions Checkboxen
        perm_group = Adw.PreferencesGroup(
            title=_("Berechtigungen"),
            description=_("Welche Features darf dieser Benutzer nutzen?"),
        )
        box.append(perm_group)

        perm_switches: dict[str, Adw.SwitchRow] = {}
        for perm in ALL_PERMISSIONS:
            switch = Adw.SwitchRow(
                title=_PERM_LABELS.get(perm, perm),
                active=perm in DEFAULT_USER_PERMISSIONS,
            )
            perm_switches[perm] = switch
            perm_group.add(switch)

        def on_role_changed(*_args):
            roles = USER_ROLES
            role = roles[role_combo.get_selected()]
            is_admin = role == "admin"
            for perm, sw in perm_switches.items():
                if is_admin:
                    sw.set_active(True)
                    sw.set_sensitive(False)
                else:
                    sw.set_sensitive(True)
                    if role == "readonly":
                        sw.set_active(False)

        role_combo.connect("notify::selected", on_role_changed)

        # SSH & Linux Account section
        ssh_group = Adw.PreferencesGroup(
            title=_("SSH & Linux-Account"),
        )
        box.append(ssh_group)

        ssh_key_entry = Adw.EntryRow(title=_("SSH Public Key"))
        ssh_key_entry.set_text("")
        ssh_group.add(ssh_key_entry)

        linux_switch = Adw.SwitchRow(
            title=_("Linux-Account erstellen"),
            subtitle=_("useradd + Home-Verzeichnis + SSH-Key Deploy"),
        )
        ssh_group.add(linux_switch)

        status_label = Gtk.Label()
        box.append(status_label)

        save_btn = Gtk.Button(label=_("Erstellen"))
        save_btn.add_css_class("suggested-action")
        save_btn.set_tooltip_text(_("Benutzer mit diesen Einstellungen erstellen"))

        def on_save(_btn):
            un = username_entry.get_text().strip()
            pw = password_entry.get_text()
            roles = USER_ROLES
            role = roles[role_combo.get_selected()]
            permissions = [p for p, sw in perm_switches.items() if sw.get_active()]

            if not un or not pw:
                status_label.set_text(_("Bitte alle Felder ausfuellen"))
                return

            ssh_key = ssh_key_entry.get_text().strip()
            create_linux = linux_switch.get_active()
            ssh_keys_list = [ssh_key] if ssh_key else None

            def worker():
                try:
                    if self.api_client and not self.db:
                        self.api_client.create_user(
                            un, pw, role, permissions,
                            ssh_public_keys=ssh_keys_list,
                            create_linux_account=create_linux,
                        )
                    else:
                        from lotto_analyzer.server.auth import hash_password
                        from lotto_analyzer.server.user_db import UserDatabase
                        from lotto_common.models.user import Role
                        udb = UserDatabase(self.config_manager.data_dir / "users.db")
                        pw_hash, salt = hash_password(pw)
                        if role == "admin":
                            permissions_final = ALL_PERMISSIONS
                        else:
                            permissions_final = permissions
                        udb.create_user(un, pw_hash, salt, Role(role), permissions_final)
                    GLib.idle_add(status_label.set_text, f"Benutzer '{un}' erstellt")
                    GLib.idle_add(dialog.close)
                    GLib.idle_add(self._load_status)
                except Exception as e:
                    GLib.idle_add(status_label.set_text, f"Fehler: {e}")

            threading.Thread(target=worker, daemon=True).start()

        save_btn.connect("clicked", on_save)
        box.append(save_btn)

        window = self.get_root()
        if window:
            dialog.present(window)

    def _on_edit_permissions(
        self, button: Gtk.Button, user_id: int,
        username: str, role: str, current_perms: list,
    ) -> None:
        """Dialog zum Bearbeiten der Berechtigungen eines Benutzers."""
        is_admin = role == "admin"

        dialog = Adw.Dialog()
        dialog.set_title(f"Berechtigungen: {username}")
        dialog.set_content_width(self._PERM_DIALOG_WIDTH)
        dialog.set_content_height(self._PERM_DIALOG_HEIGHT)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        dialog.set_child(scrolled)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        scrolled.set_child(box)

        if is_admin:
            info = Gtk.Label(
                label=_("Admin hat immer alle Berechtigungen (nicht editierbar)."),
            )
            info.add_css_class("dim-label")
            info.set_wrap(True)
            box.append(info)

        perm_group = Adw.PreferencesGroup(title=_("Feature-Berechtigungen"))
        box.append(perm_group)

        perm_switches: dict[str, Adw.SwitchRow] = {}
        for perm in ALL_PERMISSIONS:
            switch = Adw.SwitchRow(
                title=_PERM_LABELS.get(perm, perm),
                active=is_admin or perm in current_perms,
            )
            if is_admin:
                switch.set_sensitive(False)
            perm_switches[perm] = switch
            perm_group.add(switch)

        status_label = Gtk.Label()
        box.append(status_label)

        if not is_admin:
            save_btn = Gtk.Button(label=_("Speichern"))
            save_btn.add_css_class("suggested-action")
            save_btn.set_tooltip_text(_("Berechtigungen speichern"))

            def on_save(_btn):
                new_perms = [p for p, sw in perm_switches.items() if sw.get_active()]

                def worker():
                    try:
                        if self.api_client and not self.db:
                            self.api_client.update_user(user_id, permissions=new_perms)
                        else:
                            from lotto_analyzer.server.user_db import UserDatabase
                            udb = UserDatabase(self.config_manager.data_dir / "users.db")
                            udb.update_user(user_id, permissions=new_perms)
                        GLib.idle_add(status_label.set_text, "Berechtigungen gespeichert")
                        GLib.idle_add(dialog.close)
                        GLib.idle_add(self._load_status)
                    except Exception as e:
                        GLib.idle_add(status_label.set_text, f"Fehler: {e}")

                threading.Thread(target=worker, daemon=True).start()

            save_btn.connect("clicked", on_save)
            box.append(save_btn)

        window = self.get_root()
        if window:
            dialog.present(window)

    def _on_reset_password(self, button: Gtk.Button, user_id: int) -> None:
        """Passwort zurücksetzen."""
        import secrets
        new_pw = secrets.token_urlsafe(12)

        button.set_sensitive(False)
        orig_label = button.get_label()

        def worker():
            try:
                if self.api_client and not self.db:
                    self.api_client.update_user(user_id, password=new_pw)
                else:
                    from lotto_analyzer.server.auth import hash_password
                    from lotto_analyzer.server.user_db import UserDatabase
                    udb = UserDatabase(self.config_manager.data_dir / "users.db")
                    pw_hash, salt = hash_password(new_pw)
                    udb.update_user(user_id, password_hash=pw_hash, salt=salt)
                GLib.idle_add(self._show_new_password, button, new_pw, orig_label)
            except Exception as e:
                GLib.idle_add(self._show_error_restore_btn, button, orig_label, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _show_new_password(self, button: Gtk.Button, password: str, orig_label: str) -> bool:
        """Neues Passwort sicher in der ActionRow-Subtitle anzeigen, nach 10s entfernen."""
        row = button.get_parent()
        if row and hasattr(row, "set_subtitle"):
            row.set_subtitle(f"Neues PW: {password}")
            # Nach 10 Sekunden automatisch zurücksetzen
            def clear_pw():
                row.set_subtitle("")
                button.set_label(orig_label)
                button.set_sensitive(True)
                return False
            GLib.timeout_add(self._PASSWORD_DISPLAY_MS, clear_pw)
        else:
            button.set_label(orig_label)
            button.set_sensitive(True)
        return False

    def _show_error_restore_btn(self, button: Gtk.Button, orig_label: str, error: str) -> bool:
        """Fehler als Toast anzeigen und Button wiederherstellen."""
        button.set_label(orig_label)
        button.set_sensitive(True)
        show_error_toast(self, error)
        return False

    def _on_toggle_user(
        self, button: Gtk.Button, user_id: int, currently_active: bool,
    ) -> None:
        """Benutzer aktivieren/deaktivieren."""
        new_active = not currently_active
        button.set_sensitive(False)
        orig_label = button.get_label()

        def worker():
            try:
                if self.api_client and not self.db:
                    self.api_client.update_user(user_id, is_active=new_active)
                else:
                    from lotto_analyzer.server.user_db import UserDatabase
                    udb = UserDatabase(self.config_manager.data_dir / "users.db")
                    udb.update_user(user_id, is_active=1 if new_active else 0)
                GLib.idle_add(self._load_status)
            except Exception as e:
                GLib.idle_add(self._show_error_restore_btn, button, orig_label, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_disconnect_user(
        self, button: Gtk.Button, user_id: int, username: str,
    ) -> None:
        """User disconnecten — Sessions löschen + deaktivieren."""
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("'{}' disconnecten?").format(username))
        dialog.set_body(_("Alle Sessions werden beendet und der Account deaktiviert bis ein Admin ihn reaktiviert."))
        dialog.add_response("cancel", _("Abbrechen"))
        dialog.add_response("confirm", _("Disconnect"))
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_dlg, response):
            if response != "confirm":
                return
            button.set_sensitive(False)
            orig_label = button.get_label()

            def worker():
                try:
                    if self.api_client and not self.db:
                        self.api_client.admin_disconnect_user(user_id)
                    else:
                        from lotto_analyzer.server.user_db import UserDatabase
                        udb = UserDatabase(self.config_manager.data_dir / "users.db")
                        udb.disconnect_user(user_id)
                    GLib.idle_add(self._load_status)
                except Exception as e:
                    GLib.idle_add(self._show_error_restore_btn, button, orig_label, str(e))

            threading.Thread(target=worker, daemon=True).start()

        dialog.connect("response", on_response)
        window = self.get_root()
        if window:
            dialog.present(window)

    def _on_ban_user(
        self, button: Gtk.Button, user_id: int, username: str,
    ) -> None:
        """User bannen — deaktivieren + IP auf Blacklist."""
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("'{}' bannen?").format(username))
        dialog.set_body(_("Der User wird gesperrt und die letzte bekannte IP blockiert. Diese Aktion kann nur von einem Admin rückgängig gemacht werden."))
        dialog.add_response("cancel", _("Abbrechen"))
        dialog.add_response("confirm", _("Bannen"))
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_dlg, response):
            if response != "confirm":
                return
            button.set_sensitive(False)
            orig_label = button.get_label()

            def worker():
                try:
                    if self.api_client and not self.db:
                        self.api_client.admin_ban_user(user_id)
                    else:
                        from lotto_analyzer.server.user_db import UserDatabase
                        udb = UserDatabase(self.config_manager.data_dir / "users.db")
                        udb.ban_user(user_id)
                    GLib.idle_add(self._load_status)
                except Exception as e:
                    GLib.idle_add(self._show_error_restore_btn, button, orig_label, str(e))

            threading.Thread(target=worker, daemon=True).start()

        dialog.connect("response", on_response)
        window = self.get_root()
        if window:
            dialog.present(window)

    def _on_delete_user(
        self, button: Gtk.Button, user_id: int, username: str,
    ) -> None:
        """User unwiderruflich löschen."""
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("'{}' entfernen?").format(username))
        dialog.set_body(_("Der Benutzer wird unwiderruflich gelöscht. Diese Aktion kann nicht rückgängig gemacht werden."))
        dialog.add_response("cancel", _("Abbrechen"))
        dialog.add_response("confirm", _("Entfernen"))
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_dlg, response):
            if response != "confirm":
                return
            button.set_sensitive(False)
            orig_label = button.get_label()

            def worker():
                try:
                    if self.api_client and not self.db:
                        self.api_client.admin_delete_user(user_id)
                    else:
                        from lotto_analyzer.server.user_db import UserDatabase
                        udb = UserDatabase(self.config_manager.data_dir / "users.db")
                        udb.delete_user(user_id)
                    GLib.idle_add(self._load_status)
                except Exception as e:
                    GLib.idle_add(self._show_error_restore_btn, button, orig_label, str(e))

            threading.Thread(target=worker, daemon=True).start()

        dialog.connect("response", on_response)
        window = self.get_root()
        if window:
            dialog.present(window)

    # ── API-Key ──

    def _on_audit_limit_changed(self, combo) -> None:
        """Audit-Log Zeilen-Limit geändert — neu laden."""
        text = combo.get_active_text()
        self._audit_limit = int(text) if text else 10
        self._audit_scroll.set_max_content_height(self._audit_limit * 50)
        self._load_status()

    def _on_audit_check_toggled(self, _check) -> None:
        """Audit-Checkbox geändert — Delete-Button aktivieren wenn mind. 1 gewählt."""
        selected = sum(1 for c, _ in self._audit_checks if c.get_active())
        self._audit_delete_btn.set_sensitive(selected > 0)
        self._audit_delete_btn.set_label(
            f"{_('Markierte löschen')} ({selected})" if selected > 0 else _("Markierte löschen")
        )

    def _on_audit_select_all(self, check) -> None:
        """Alle Audit-Einträge aus-/abwählen."""
        active = check.get_active()
        for c, _ in self._audit_checks:
            c.set_active(active)

    def _on_audit_delete(self, _btn) -> None:
        """Markierte Audit-Einträge löschen."""
        selected_ids = [
            entry.get("id") for c, entry in self._audit_checks
            if c.get_active() and entry.get("id")
        ]
        if not selected_ids:
            return

        count = len(selected_ids)
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Audit-Einträge löschen?"))
        dialog.set_body(f"{count} " + _("Einträge werden unwiderruflich gelöscht."))
        dialog.add_response("cancel", _("Abbrechen"))
        dialog.add_response("delete", _("Löschen"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(dlg, resp):
            if resp == "delete":
                self._do_audit_delete(selected_ids)

        dialog.connect("response", on_response)
        dialog.present(self.get_root())

    def _do_audit_delete(self, ids: list) -> None:
        """Audit-Einträge im Hintergrund löschen."""
        def worker():
            try:
                if self.api_client:
                    for aid in ids:
                        try:
                            self.api_client.delete_audit_entry(aid)
                        except Exception as e:
                            logger.warning(f"Audit-Eintrag {aid} löschen fehlgeschlagen: {e}")
                elif self.db:
                    from lotto_analyzer.server.user_db import UserDatabase
                    user_db_path = self.config_manager.data_dir / "users.db"
                    if user_db_path.exists():
                        udb = UserDatabase(user_db_path)
                        for aid in ids:
                            try:
                                udb.delete_audit_entry(aid)
                            except Exception as e:
                                logger.warning(f"Audit-Eintrag {aid} lokal löschen fehlgeschlagen: {e}")
                GLib.idle_add(self._load_status)
            except Exception as e:
                logger.warning(f"Audit-Einträge löschen fehlgeschlagen: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_rotate_api_key(self, button: Gtk.Button) -> None:
        """Neuen API-Key generieren (mit Bestätigung)."""
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("API-Key rotieren?"))
        dialog.set_body(
            _("Der aktuelle API-Key wird ungültig. "
            "Alle Clients müssen den neuen Key verwenden.")
        )
        dialog.add_response("cancel", _("Abbrechen"))
        dialog.add_response("confirm", _("Rotieren"))
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_dlg, response):
            if response != "confirm":
                return
            button.set_sensitive(False)

            def worker():
                try:
                    if self.api_client and not self.db:
                        data = self.api_client.rotate_api_key()
                        prefix = data.get("key_prefix", "????")
                        GLib.idle_add(
                            self._api_key_display.set_subtitle,
                            f"{prefix}...****",
                        )
                    else:
                        from lotto_analyzer.server.auth import generate_api_key
                        from lotto_analyzer.server.user_db import UserDatabase
                        import hashlib
                        udb = UserDatabase(self.config_manager.data_dir / "users.db")
                        new_key = generate_api_key()
                        key_hash = hashlib.sha256(new_key.encode()).hexdigest()
                        udb.create_api_key(1, key_hash, new_key[:8], "Rotierter Key")
                        GLib.idle_add(
                            self._api_key_display.set_subtitle,
                            f"{new_key[:8]}...{new_key[-4:]}",
                        )
                except Exception as e:
                    GLib.idle_add(
                        self._api_key_display.set_subtitle, f"Fehler: {e}",
                    )
                GLib.idle_add(button.set_sensitive, True)

            threading.Thread(target=worker, daemon=True).start()

        dialog.connect("response", on_response)
        window = self.get_root()
        if window:
            dialog.present(window)

