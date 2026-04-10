"""UI-Seite security: part3 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("security.part3")




class Part3Mixin2:
    """Teil 2 von Part3Mixin."""

    def _on_fail2ban_loaded(self, f2b: dict) -> bool:
        installed = f2b.get("installed", False)
        self._f2b_status_row.set_subtitle(_("Installiert") if installed else _("Nicht installiert"))

        jail_configured = f2b.get("jail_configured", False)
        self._f2b_jail_row.set_subtitle(_("Konfiguriert") if jail_configured else _("Nicht konfiguriert"))

        banned = f2b.get("banned_ips", [])
        if isinstance(banned, list):
            self._f2b_banned_row.set_subtitle(str(len(banned)))
        else:
            self._f2b_banned_row.set_subtitle(str(banned))

        # Buttons je nach Status aktivieren/deaktivieren
        self._f2b_install_btn.set_sensitive(not installed)
        self._f2b_configure_btn.set_sensitive(installed and not jail_configured)
        self._f2b_remove_btn.set_sensitive(installed and jail_configured)
        return False

    def _load_logs(self, clear: bool = False) -> None:
        """Firewall-Log laden."""
        def worker():
            try:
                entries = self.api_client.firewall_log(limit=self._LOG_PAGE_SIZE, offset=self._log_offset)
            except Exception as e:
                logger.warning(f"Firewall-Log laden fehlgeschlagen: {e}")
                entries = []
            GLib.idle_add(self._on_logs_loaded, entries, clear)

        threading.Thread(target=worker, daemon=True).start()

    def _on_logs_loaded(self, entries: list, clear: bool) -> bool:
        if clear:
            self._clear_listbox(self._log_box)

        for entry in entries:
            ts = entry.get("timestamp", "?")
            ip = entry.get("ip", "?")
            action = entry.get("action", "?")
            country = entry.get("country", "")

            title = f"{ts} | {ip}"
            subtitle = action
            if country:
                subtitle += f" | {country}"

            row = Adw.ActionRow(title=title, subtitle=subtitle)
            self._log_box.append(row)

        if not entries and clear:
            self._log_box.append(
                Adw.ActionRow(title=_("Keine Protokolleintraege"))
            )

        if entries:
            self._log_offset += len(entries)

        self._load_more_btn.set_sensitive(len(entries) >= 50)
        return False

    # ──────────────────────────────────────────────────────────────────
    #  Aktionen: Firewall-Status
    # ──────────────────────────────────────────────────────────────────

    def _on_firewall_toggled(self, switch: Adw.SwitchRow, _pspec) -> None:
        """Firewall aktivieren/deaktivieren."""
        enabled = switch.get_active()

        def worker():
            try:
                self.api_client.firewall_update_config({"enabled": enabled})
                GLib.idle_add(
                    self._fw_active_switch.set_subtitle,
                    _("Aktiv") if enabled else _("Deaktiviert"),
                )
            except Exception as e:
                GLib.idle_add(self._fw_active_switch.set_subtitle, f"Fehler: {e}")

        threading.Thread(target=worker, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────
    #  Aktionen: Whitelist
    # ──────────────────────────────────────────────────────────────────

    def _on_add_whitelist(self, button: Gtk.Button) -> None:
        """Dialog zum Hinzufügen einer IP/CIDR zur Whitelist."""
        dialog = Adw.AlertDialog(
            heading=_("IP zur Whitelist hinzufügen"),
            body=_("IP-Adresse oder CIDR-Netzwerk eingeben"),
        )
        dialog.add_response("cancel", _("Abbrechen"))
        dialog.add_response("add", _("Hinzufügen"))
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        group = Adw.PreferencesGroup()
        ip_entry = Adw.EntryRow(title=_("IP / CIDR (z.B. 192.168.1.0/24)"))
        group.add(ip_entry)

        type_combo = Adw.ComboRow(title=_("Typ"))
        type_list = Gtk.StringList()
        for t in ["ip", "cidr", "range"]:
            type_list.append(t)
        type_combo.set_model(type_list)
        group.add(type_combo)

        desc_entry = Adw.EntryRow(title=_("Beschreibung (optional)"))
        group.add(desc_entry)

        dialog.set_extra_child(group)

        status_label = Gtk.Label()
        status_label.add_css_class("error")
        group.add(status_label)

        def on_response(_dialog, response):
            if response != "add":
                return
            ip_val = ip_entry.get_text().strip()
            if not ip_val:
                return
            # IP/CIDR validieren
            err = self._validate_ip_or_cidr(ip_val)
            if err:
                status_label.set_text(err)
                # Dialog offen lassen — erneut praesentieren
                window = self.get_root()
                if window:
                    dialog.present(window)
                return
            types = ["ip", "cidr", "range"]
            entry_type = types[type_combo.get_selected()]
            desc = desc_entry.get_text().strip()

            def worker():
                try:
                    self.api_client.firewall_add_whitelist(ip_val, entry_type, desc)
                    GLib.idle_add(self._load_whitelist)
                except Exception as e:
                    GLib.idle_add(self._show_error, f"Whitelist-Fehler: {e}")

            threading.Thread(target=worker, daemon=True).start()

        dialog.connect("response", on_response)

        window = self.get_root()
        if window:
            dialog.present(window)

    def _on_toggle_whitelist(self, switch: Gtk.Switch, _pspec, entry_id: int) -> None:
        """Whitelist-Eintrag aktivieren/deaktivieren."""
        def worker():
            try:
                self.api_client.firewall_toggle_whitelist(entry_id)
            except Exception as e:
                GLib.idle_add(self._show_error, f"Toggle-Fehler: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_remove_whitelist(self, button: Gtk.Button, entry_id: int) -> None:
        """Whitelist-Eintrag entfernen."""
        button.set_sensitive(False)
        orig_label = button.get_icon_name() or button.get_label()

        def worker():
            try:
                self.api_client.firewall_remove_whitelist(entry_id)
                GLib.idle_add(self._load_whitelist)
            except Exception as e:
                GLib.idle_add(self._show_error, f"Whitelist-Fehler: {e}")
                GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────
    #  Aktionen: Blacklist
    # ──────────────────────────────────────────────────────────────────

    def _on_add_blacklist(self, button: Gtk.Button) -> None:
        """Dialog zum Hinzufügen einer IP/CIDR zur Blacklist."""
        dialog = Adw.AlertDialog(
            heading=_("IP sperren"),
            body=_("IP-Adresse oder CIDR-Netzwerk eingeben"),
        )
        dialog.add_response("cancel", _("Abbrechen"))
        dialog.add_response("block", _("Sperren"))
        dialog.set_response_appearance("block", Adw.ResponseAppearance.DESTRUCTIVE)

        group = Adw.PreferencesGroup()
        ip_entry = Adw.EntryRow(title=_("IP / CIDR (z.B. 10.0.0.5)"))
        group.add(ip_entry)

        type_combo = Adw.ComboRow(title=_("Typ"))
        type_list = Gtk.StringList()
        for t in ["ip", "cidr", "range"]:
            type_list.append(t)
        type_combo.set_model(type_list)
        group.add(type_combo)

        reason_entry = Adw.EntryRow(title=_("Grund (optional)"))
        group.add(reason_entry)

        status_label = Gtk.Label()
        status_label.add_css_class("error")
        group.add(status_label)

        dialog.set_extra_child(group)

        def on_response(_dialog, response):
            if response != "block":
                return
            ip_val = ip_entry.get_text().strip()
            if not ip_val:
                return
            # IP/CIDR validieren
            err = self._validate_ip_or_cidr(ip_val)
            if err:
                status_label.set_text(err)
                window = self.get_root()
                if window:
                    dialog.present(window)
                return
            types = ["ip", "cidr", "range"]
            entry_type = types[type_combo.get_selected()]
            reason = reason_entry.get_text().strip()

            def worker():
                try:
                    self.api_client.firewall_add_blacklist(ip_val, entry_type, reason)
                    GLib.idle_add(self._load_blacklist)
                except Exception as e:
                    GLib.idle_add(self._show_error, f"Blacklist-Fehler: {e}")

            threading.Thread(target=worker, daemon=True).start()

        dialog.connect("response", on_response)

        window = self.get_root()
        if window:
            dialog.present(window)

    def _on_remove_blacklist(self, button: Gtk.Button, entry_id: int) -> None:
        """Manuellen Blacklist-Eintrag entfernen."""
        button.set_sensitive(False)

        def worker():
            try:
                self.api_client.firewall_remove_blacklist(entry_id)
                GLib.idle_add(self._load_blacklist)
            except Exception as e:
                GLib.idle_add(self._show_error, f"Blacklist-Fehler: {e}")
                GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────
    #  Aktionen: Auto-Block
    # ──────────────────────────────────────────────────────────────────

    def _on_unblock_auto(self, button: Gtk.Button, entry_id: int) -> None:
        """Automatisch gesperrte IP entsperren."""
        button.set_sensitive(False)

        def worker():
            try:
                self.api_client.firewall_unblock_auto(entry_id)
                GLib.idle_add(self._load_auto_blocked)
                GLib.idle_add(self._load_firewall_status)
            except Exception as e:
                GLib.idle_add(self._show_error, f"Entsperren fehlgeschlagen: {e}")
                GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()

    def _on_save_auto_block_settings(self, button: Gtk.Button) -> None:
        """Auto-Block-Einstellungen speichern."""
        data = {
            "auto_block_enabled": self._auto_block_switch.get_active(),
            "max_failed_attempts": int(self._max_attempts_spin.get_value()),
            "failed_attempt_window_minutes": int(self._time_window_spin.get_value()),
            "auto_block_duration_minutes": int(self._block_duration_spin.get_value()),
            "port_scan_protection": self._portscan_switch.get_active(),
            "whitelist_bypass_ratelimit": self._whitelist_ratelimit_switch.get_active(),
            "whitelist_bypass_geoip": self._geoip_whitelist_bypass.get_active(),
            "log_retention_days": int(self._log_retention_spin.get_value()),
        }

        def worker():
            try:
                self.api_client.firewall_update_config(data)
                GLib.idle_add(self._auto_block_status.set_text, _("Gespeichert"))
            except Exception as e:
                GLib.idle_add(self._auto_block_status.set_text, f"Fehler: {e}")

        threading.Thread(target=worker, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────
    #  Aktionen: GeoIP
    # ──────────────────────────────────────────────────────────────────

    def _on_geoip_update(self, button: Gtk.Button) -> None:
        """GeoIP-Datenbank aktualisieren."""
        button.set_sensitive(False)
        self._geoip_db_row.set_subtitle(_("Wird aktualisiert..."))

        def worker():
            try:
                result = self.api_client.firewall_geoip_update()
                msg = result.get("message", "Aktualisiert")
                GLib.idle_add(self._geoip_db_row.set_subtitle, msg)
                GLib.idle_add(self._load_geoip)
            except Exception as e:
                GLib.idle_add(self._geoip_db_row.set_subtitle, f"Fehler: {e}")
            GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────
    #  Aktionen: Fail2ban
    # ──────────────────────────────────────────────────────────────────

    def _on_f2b_install(self, button: Gtk.Button) -> None:
        """Fail2ban installieren."""
        button.set_sensitive(False)
        self._f2b_status_row.set_subtitle(_("Wird installiert..."))

        def worker():
            try:
                result = self.api_client.firewall_fail2ban_install()
                msg = result.get("message", "Installiert")
                GLib.idle_add(self._f2b_status_row.set_subtitle, msg)
                GLib.idle_add(self._load_fail2ban)
            except Exception as e:
                GLib.idle_add(self._f2b_status_row.set_subtitle, f"Fehler: {e}")
                GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()

    def _on_f2b_configure(self, button: Gtk.Button) -> None:
        """Fail2ban Jail konfigurieren."""
        button.set_sensitive(False)
        self._f2b_jail_row.set_subtitle(_("Wird konfiguriert..."))

        def worker():
            try:
                result = self.api_client.firewall_fail2ban_configure()
                msg = result.get("message", "Konfiguriert")
                GLib.idle_add(self._f2b_jail_row.set_subtitle, msg)
                GLib.idle_add(self._load_fail2ban)
            except Exception as e:
                GLib.idle_add(self._f2b_jail_row.set_subtitle, f"Fehler: {e}")
                GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()

    def _on_f2b_remove(self, button: Gtk.Button) -> None:
        """Fail2ban Jail entfernen."""
        button.set_sensitive(False)
        self._f2b_jail_row.set_subtitle(_("Wird entfernt..."))

        def worker():
            try:
                result = self.api_client.firewall_fail2ban_remove()
                msg = result.get("message", "Entfernt")
                GLib.idle_add(self._f2b_jail_row.set_subtitle, msg)
                GLib.idle_add(self._load_fail2ban)
            except Exception as e:
                GLib.idle_add(self._f2b_jail_row.set_subtitle, f"Fehler: {e}")
                GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────
    #  Aktionen: IP-Prüfung
    # ──────────────────────────────────────────────────────────────────

    def _on_check_ip(self, button: Gtk.Button) -> None:
        """IP-Adresse gegen alle Firewall-Regeln prüfen."""
        ip = self._ip_check_entry.get_text().strip()
        if not ip:
            self._ip_check_result.set_text(_("Bitte eine IP-Adresse eingeben."))
            return

        self._ip_check_result.set_text(_("Wird geprüft..."))
        button.set_sensitive(False)

        def worker():
            try:
                result = self.api_client.firewall_check_ip(ip)
                lines = []
                lines.append(f"IP: {ip}")
                lines.append(f"{_('Erlaubt')}: {_('Ja') if result.get('allowed', False) else _('Nein')}")
                if result.get("whitelisted"):
                    lines.append(f"{_('Whitelist')}: {_('Ja')}")
                if result.get("blacklisted"):
                    lines.append(f"{_('Blacklist')}: {_('Ja')}")
                if result.get("auto_blocked"):
                    lines.append(f"{_('Auto-Block')}: {_('Ja')}")
                country = result.get("country")
                if country:
                    lines.append(f"{_('Land')}: {country}")
                if result.get("geoip_blocked"):
                    lines.append(f"{_('GeoIP blockiert')}: {_('Ja')}")
                reason = result.get("reason", "")
                if reason:
                    lines.append(f"{_('Grund')}: {reason}")
                text = "\n".join(lines)
                GLib.idle_add(self._ip_check_result.set_text, text)
            except Exception as e:
                GLib.idle_add(self._ip_check_result.set_text, f"Fehler: {e}")
            GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────
    #  Aktionen: Log
    # ──────────────────────────────────────────────────────────────────

