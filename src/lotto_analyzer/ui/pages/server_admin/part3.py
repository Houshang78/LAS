"""UI-Seite server_admin: part3 Mixin."""

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


logger = get_logger("server_admin.part3")


class Part3Mixin:
    """Part3 Mixin."""

    # ── SSH-Key-Verwaltung ──

    def _on_add_ssh_key(self, button: Gtk.Button) -> None:
        """Dialog zum Hinzufügen eines SSH-Keys."""
        dialog = Adw.Dialog()
        dialog.set_title(_("SSH-Key hinzufügen"))
        dialog.set_content_width(self._DIALOG_WIDTH)
        dialog.set_content_height(350)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        dialog.set_child(box)

        group = Adw.PreferencesGroup()
        box.append(group)

        # User-Auswahl (ComboRow mit verfügbaren Usern)
        user_combo = Adw.ComboRow(title=_("Benutzer"))
        user_list = Gtk.StringList()
        users_data = []

        def load_users():
            # D3: API-only — SSH-Key-Add-Dialog Benutzerliste.
            try:
                if self.api_client:
                    users_data.extend(self.api_client.list_users())
                else:
                    logger.warning("load_users (sshkey): kein api_client")
            except Exception as e:
                logger.warning(f"Benutzerliste laden fehlgeschlagen: {e}")
            GLib.idle_add(_populate_users)

        def _populate_users():
            for u in users_data:
                user_list.append(f"{u['username']} (ID: {u['id']})")
            user_combo.set_model(user_list)

        threading.Thread(target=load_users, daemon=True).start()
        group.add(user_combo)

        key_entry = Adw.EntryRow(title=_("Public Key (ssh-rsa/ssh-ed25519 ...)"))
        group.add(key_entry)

        desc_entry = Adw.EntryRow(title=_("Beschreibung (optional)"))
        group.add(desc_entry)

        status_label = Gtk.Label()
        box.append(status_label)

        save_btn = Gtk.Button(label=_("Registrieren"))
        save_btn.add_css_class("suggested-action")
        save_btn.set_tooltip_text(_("SSH-Key registrieren"))

        def on_save(_btn):
            idx = user_combo.get_selected()
            if idx >= len(users_data):
                status_label.set_text(_("Bitte Benutzer wählen"))
                return
            user = users_data[idx]
            key_data = key_entry.get_text().strip()
            desc = desc_entry.get_text().strip()
            if not key_data:
                status_label.set_text(_("Bitte Public Key eingeben"))
                return

            def worker():
                # D3: API-only — Server validiert + parst den SSH-Key
                # serverseitig (parse_public_key + Fingerprint im Backend).
                try:
                    if not self.api_client:
                        GLib.idle_add(status_label.set_text, _("Server nicht verbunden"))
                        return
                    self.api_client.add_user_key(user["id"], key_data, desc)
                    GLib.idle_add(status_label.set_text, _("SSH-Key registriert"))
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

    def _on_remove_ssh_key(self, button: Gtk.Button, fingerprint: str) -> None:
        """SSH-Key entfernen."""
        button.set_sensitive(False)
        orig_label = button.get_label()

        def worker():
            # D3: API-only.
            try:
                if not self.api_client:
                    GLib.idle_add(
                        self._show_error_restore_btn, button, orig_label,
                        _("Server nicht verbunden"),
                    )
                    return
                self.api_client.remove_user_key(fingerprint)
                GLib.idle_add(self._load_status)
            except Exception as e:
                GLib.idle_add(self._show_error_restore_btn, button, orig_label, str(e))

        threading.Thread(target=worker, daemon=True).start()

    # ── Zertifikat-Verwaltung ──

    def _on_issue_cert(self, button: Gtk.Button) -> None:
        """Dialog zum Ausstellen eines Client-Zertifikats."""
        dialog = Adw.Dialog()
        dialog.set_title(_("Zertifikat ausstellen"))
        dialog.set_content_width(self._DIALOG_WIDTH)
        dialog.set_content_height(300)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        dialog.set_child(box)

        group = Adw.PreferencesGroup()
        box.append(group)

        user_combo = Adw.ComboRow(title=_("Benutzer"))
        user_list = Gtk.StringList()
        users_data = []

        def load_users():
            try:
                # D3: API-only — Cert-Issue-Dialog Benutzerliste.
                if self.api_client:
                    users_data.extend(self.api_client.list_users())
                else:
                    logger.warning("load_users (cert): kein api_client")
            except Exception as e:
                logger.warning(f"Benutzerliste laden fehlgeschlagen: {e}")
            GLib.idle_add(_populate_users)

        def _populate_users():
            for u in users_data:
                user_list.append(f"{u['username']} (ID: {u['id']})")
            user_combo.set_model(user_list)

        threading.Thread(target=load_users, daemon=True).start()
        group.add(user_combo)

        days_entry = Adw.SpinRow.new_with_range(30, 3650, 1)
        days_entry.set_title(_("Gültigkeitsdauer (Tage)"))
        days_entry.set_value(365)
        group.add(days_entry)

        status_label = Gtk.Label()
        status_label.set_wrap(True)
        box.append(status_label)

        save_btn = Gtk.Button(label=_("Ausstellen"))
        save_btn.add_css_class("suggested-action")
        save_btn.set_tooltip_text(_("Zertifikat ausstellen"))

        def on_save(_btn):
            idx = user_combo.get_selected()
            if idx >= len(users_data):
                status_label.set_text(_("Bitte Benutzer wählen"))
                return
            user = users_data[idx]
            days = int(days_entry.get_value())

            def worker():
                # D3: API-only — Server stellt Cert aus + persistiert.
                # Client-seitige CA-Schlüssel-Operationen verboten
                # (Sicherheitsrisiko + falscher Trust-Anchor).
                try:
                    if not self.api_client:
                        GLib.idle_add(status_label.set_text, _("Server nicht verbunden"))
                        return
                    result = self.api_client.issue_certificate(user["id"], days)
                    GLib.idle_add(
                        status_label.set_text,
                        f"Zertifikat ausgestellt!\nSerial: {result.get('serial', '?')[:20]}...",
                    )
                    GLib.idle_add(self._load_status)
                except Exception as e:
                    GLib.idle_add(status_label.set_text, f"Fehler: {e}")

            threading.Thread(target=worker, daemon=True).start()

        save_btn.connect("clicked", on_save)
        box.append(save_btn)

        window = self.get_root()
        if window:
            dialog.present(window)

    def _on_revoke_cert(self, button: Gtk.Button, serial: str) -> None:
        """Zertifikat widerrufen (mit Bestätigung)."""
        short_serial = serial[:18] + ".." if len(serial) > 20 else serial
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Zertifikat widerrufen?"))
        dialog.set_body(
            _("Das Zertifikat ({}) wird unwiderruflich gesperrt. "
            "Der Client kann sich danach nicht mehr damit anmelden.").format(short_serial)
        )
        dialog.add_response("cancel", _("Abbrechen"))
        dialog.add_response("confirm", _("Widerrufen"))
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_dlg, response):
            if response != "confirm":
                return
            button.set_sensitive(False)
            orig_label = button.get_label()

            def worker():
                # D3: API-only.
                try:
                    if not self.api_client:
                        GLib.idle_add(
                            self._show_error_restore_btn, button, orig_label,
                            _("Server nicht verbunden"),
                        )
                        return
                    self.api_client.revoke_certificate(serial)
                    GLib.idle_add(self._load_status)
                except Exception as e:
                    GLib.idle_add(self._show_error_restore_btn, button, orig_label, str(e))

            threading.Thread(target=worker, daemon=True).start()

        dialog.connect("response", on_response)
        window = self.get_root()
        if window:
            dialog.present(window)

