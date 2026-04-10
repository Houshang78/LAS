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




class Part3Mixin1:
    """Teil 1 von Part3Mixin."""

    def _build_log_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Firewall-Protokoll"),
            description=_("Letzte Firewall-Ereignisse"),
        )
        content.append(group)

        self._log_box = Gtk.ListBox()
        self._log_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._log_box.add_css_class("boxed-list")
        group.add(self._log_box)

        btn_row = Adw.ActionRow(title="")
        self._load_more_btn = Gtk.Button(label=_("Mehr laden"))
        self._load_more_btn.set_valign(Gtk.Align.CENTER)
        self._load_more_btn.connect("clicked", self._on_load_more_logs)
        btn_row.add_suffix(self._load_more_btn)
        group.add(btn_row)

    # ── Sektion 10: Erweiterte Sicherheit ──

    def _build_advanced_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Erweiterte Sicherheit"),
            description=_("Zusaetzliche Schutzmassnahmen"),
        )
        content.append(group)

        self._portscan_switch = Adw.SwitchRow(
            title=_("Port-Scan-Schutz"),
            subtitle=_("Erkennung und Blockierung von Port-Scans"),
        )
        group.add(self._portscan_switch)

        self._whitelist_ratelimit_switch = Adw.SwitchRow(
            title=_("Whitelist umgeht Rate-Limit"),
            subtitle=_("IPs in der Whitelist werden vom Rate-Limit ausgenommen"),
        )
        group.add(self._whitelist_ratelimit_switch)

        self._log_retention_spin = Adw.SpinRow.new_with_range(1, 365, 1)
        self._log_retention_spin.set_title(_("Log-Aufbewahrung (Tage)"))
        self._log_retention_spin.set_value(90)
        group.add(self._log_retention_spin)

        cleanup_row = Adw.ActionRow(title="")
        cleanup_btn = Gtk.Button(label=_("Alte Logs bereinigen"))
        cleanup_btn.set_tooltip_text(_("Audit-Logs aelter als 90 Tage löschen"))
        cleanup_btn.add_css_class("destructive-action")
        cleanup_btn.set_valign(Gtk.Align.CENTER)
        cleanup_btn.connect("clicked", self._on_cleanup_logs)
        self._cleanup_status = Gtk.Label()
        self._cleanup_status.set_valign(Gtk.Align.CENTER)
        cleanup_row.add_suffix(self._cleanup_status)
        cleanup_row.add_suffix(cleanup_btn)
        self.register_readonly_button(cleanup_btn)
        group.add(cleanup_row)

    # ──────────────────────────────────────────────────────────────────
    #  Daten laden / refresh
    # ──────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Alle Daten nur neu laden wenn veraltet (>5min)."""
        if not self.api_client or not self.is_stale():
            return
        self._log_offset = 0
        self._load_firewall_status()
        self._load_whitelist()
        self._load_blacklist()
        self._load_auto_blocked()
        self._load_config()
        self._load_geoip()
        self._load_fail2ban()
        self._load_logs(clear=True)
        self.mark_refreshed()

    def _load_firewall_status(self) -> None:
        """Firewall-Status vom Server laden."""
        def worker():
            try:
                status = self.api_client.firewall_status()
                attempts = self.api_client.firewall_list_failed_attempts()
            except Exception as e:
                logger.warning(f"Firewall-Status Abfrage fehlgeschlagen: {e}")
                status, attempts = {}, []
            GLib.idle_add(self._on_status_loaded, status, attempts)

        threading.Thread(target=worker, daemon=True).start()

    def _on_status_loaded(self, status: dict, attempts: list) -> bool:
        # Firewall-Schalter setzen ohne Signal auszuloesen
        self._fw_active_switch.handler_block_by_func(self._on_firewall_toggled)
        self._fw_active_switch.set_active(status.get("enabled", False))
        self._fw_active_switch.handler_unblock_by_func(self._on_firewall_toggled)

        blocked = status.get("blocked_count", 0)
        self._blocked_count_row.set_subtitle(str(blocked))

        self._failed_logins_row.set_subtitle(str(len(attempts)))

        geoip = status.get("geoip_status", _("Nicht konfiguriert"))
        self._geoip_status_row.set_subtitle(str(geoip))
        return False

    def _load_whitelist(self) -> None:
        """Whitelist vom Server laden."""
        def worker():
            try:
                entries = self.api_client.firewall_list_whitelist()
            except Exception as e:
                logger.warning(f"Whitelist laden fehlgeschlagen: {e}")
                entries = []
            GLib.idle_add(self._on_whitelist_loaded, entries)

        threading.Thread(target=worker, daemon=True).start()

    def _on_whitelist_loaded(self, entries: list, show_all: bool = False) -> bool:
        self._whitelist_all = entries
        total = len(entries)
        limit = total if show_all else self._LIST_PAGE_SIZE
        display = entries[:limit]

        self._clear_listbox(self._whitelist_box)

        # Info-Zeile aktualisieren
        if total > limit:
            self._whitelist_info_row.set_subtitle(f"{limit} von {total} angezeigt")
            self._whitelist_load_all_btn.set_visible(True)
        else:
            self._whitelist_info_row.set_subtitle(str(total))
            self._whitelist_load_all_btn.set_visible(False)

        for entry in display:
            entry_id = entry.get("id")
            ip = entry.get("ip", entry.get("ip_or_cidr", "?"))
            desc = entry.get("description", "")
            active = entry.get("active", True)

            row = Adw.ActionRow(
                title=ip,
                subtitle=desc if desc else _("Kein Kommentar"),
            )

            # Toggle-Switch
            toggle = Gtk.Switch()
            toggle.set_active(active)
            toggle.set_valign(Gtk.Align.CENTER)
            toggle.connect("notify::active", self._on_toggle_whitelist, entry_id)
            row.add_suffix(toggle)

            # Löschen-Button
            del_btn = Gtk.Button(icon_name="user-trash-symbolic")
            del_btn.set_tooltip_text(_("Eintrag löschen"))
            del_btn.add_css_class("destructive-action")
            del_btn.set_valign(Gtk.Align.CENTER)
            del_btn.connect("clicked", self._on_remove_whitelist, entry_id)
            row.add_suffix(del_btn)

            self._whitelist_box.append(row)

        if not entries:
            self._whitelist_box.append(
                Adw.ActionRow(title=_("Keine Einträge"))
            )
        return False

    def _load_blacklist(self) -> None:
        """Manuelle Blacklist vom Server laden."""
        def worker():
            try:
                entries = self.api_client.firewall_list_blacklist(include_expired=False)
            except Exception as e:
                logger.warning(f"Blacklist laden fehlgeschlagen: {e}")
                entries = []
            GLib.idle_add(self._on_blacklist_loaded, entries)

        threading.Thread(target=worker, daemon=True).start()

    def _on_blacklist_loaded(self, entries: list, show_all: bool = False) -> bool:
        self._blacklist_all = entries
        total = len(entries)
        limit = total if show_all else self._LIST_PAGE_SIZE
        display = entries[:limit]

        self._clear_listbox(self._blacklist_box)

        # Info-Zeile aktualisieren
        if total > limit:
            self._blacklist_info_row.set_subtitle(f"{limit} von {total} angezeigt")
            self._blacklist_load_all_btn.set_visible(True)
        else:
            self._blacklist_info_row.set_subtitle(str(total))
            self._blacklist_load_all_btn.set_visible(False)

        for entry in display:
            entry_id = entry.get("id")
            ip = entry.get("ip", entry.get("ip_or_cidr", "?"))
            reason = entry.get("reason", "")
            blocked_at = entry.get("blocked_at", "")

            row = Adw.ActionRow(
                title=ip,
                subtitle=f"{reason} | {_('Gesperrt')}: {blocked_at}" if blocked_at else reason,
            )

            unblock_btn = Gtk.Button(label=_("Entsperren"))
            unblock_btn.set_tooltip_text(_("IP-Adresse aus der Blacklist entfernen"))
            unblock_btn.set_valign(Gtk.Align.CENTER)
            unblock_btn.connect("clicked", self._on_remove_blacklist, entry_id)
            row.add_suffix(unblock_btn)

            self._blacklist_box.append(row)

        if not entries:
            self._blacklist_box.append(
                Adw.ActionRow(title=_("Keine manuell gesperrten IPs"))
            )
        return False

    def _load_auto_blocked(self) -> None:
        """Automatisch gesperrte IPs laden."""
        def worker():
            try:
                entries = self.api_client.firewall_list_blocked()
            except Exception as e:
                logger.warning(f"Auto-Block-Liste laden fehlgeschlagen: {e}")
                entries = []
            GLib.idle_add(self._on_auto_blocked_loaded, entries)

        threading.Thread(target=worker, daemon=True).start()

    def _on_auto_blocked_loaded(self, entries: list, show_all: bool = False) -> bool:
        self._auto_blocked_all = entries
        total = len(entries)
        limit = total if show_all else self._LIST_PAGE_SIZE
        display = entries[:limit]

        self._clear_listbox(self._auto_blocked_box)

        # Info-Zeile aktualisieren
        if total > limit:
            self._auto_blocked_info_row.set_subtitle(f"{limit} von {total} angezeigt")
            self._auto_blocked_load_all_btn.set_visible(True)
        else:
            self._auto_blocked_info_row.set_subtitle(str(total))
            self._auto_blocked_load_all_btn.set_visible(False)

        for entry in display:
            entry_id = entry.get("id")
            ip = entry.get("ip", "?")
            reason = entry.get("reason", "Auto-Block")
            blocked_at = entry.get("blocked_at", "")
            expires = entry.get("expires_at", "")

            subtitle_parts = []
            if reason:
                subtitle_parts.append(reason)
            if blocked_at:
                subtitle_parts.append(f"{_('Seit')}: {blocked_at}")
            if expires:
                subtitle_parts.append(f"{_('Bis')}: {expires}")

            row = Adw.ActionRow(
                title=ip,
                subtitle=" | ".join(subtitle_parts) if subtitle_parts else _("Automatisch gesperrt"),
            )

            unblock_btn = Gtk.Button(label=_("Entsperren"))
            unblock_btn.set_tooltip_text(_("Automatische Sperre aufheben"))
            unblock_btn.set_valign(Gtk.Align.CENTER)
            unblock_btn.connect("clicked", self._on_unblock_auto, entry_id)
            row.add_suffix(unblock_btn)

            self._auto_blocked_box.append(row)

        if not entries:
            self._auto_blocked_box.append(
                Adw.ActionRow(title=_("Keine automatisch gesperrten IPs"))
            )
        return False

    def _load_config(self) -> None:
        """Firewall-Konfiguration laden."""
        def worker():
            try:
                config = self.api_client.firewall_config()
            except Exception as e:
                logger.warning(f"Firewall-Config laden fehlgeschlagen: {e}")
                config = {}
            GLib.idle_add(self._on_config_loaded, config)

        threading.Thread(target=worker, daemon=True).start()

    def _on_config_loaded(self, config: dict) -> bool:
        # Auto-Block Einstellungen
        auto_block = config.get("auto_block", {})
        if isinstance(auto_block, dict):
            self._auto_block_switch.set_active(auto_block.get("enabled", False))
            self._max_attempts_spin.set_value(auto_block.get("max_attempts", 3))
            self._time_window_spin.set_value(auto_block.get("time_window_minutes", 30))
            self._block_duration_spin.set_value(auto_block.get("block_duration_minutes", 1440))
        else:
            self._auto_block_switch.set_active(config.get("auto_block_enabled", False))
            self._max_attempts_spin.set_value(config.get("max_attempts", 3))
            self._time_window_spin.set_value(config.get("time_window_minutes", 30))
            self._block_duration_spin.set_value(config.get("block_duration_minutes", 1440))

        # Erweiterte Sicherheit
        self._portscan_switch.set_active(config.get("portscan_protection", False))
        self._whitelist_ratelimit_switch.set_active(config.get("whitelist_bypasses_ratelimit", False))
        self._log_retention_spin.set_value(config.get("log_retention_days", 90))

        # GeoIP bypass
        self._geoip_whitelist_bypass.set_active(config.get("whitelist_bypasses_geoip", False))
        return False

    def _load_geoip(self) -> None:
        """GeoIP-Status laden."""
        def worker():
            try:
                geoip = self.api_client.firewall_geoip_status()
            except Exception as e:
                logger.warning(f"GeoIP-Status laden fehlgeschlagen: {e}")
                geoip = {}
            GLib.idle_add(self._on_geoip_loaded, geoip)

        threading.Thread(target=worker, daemon=True).start()

    def _on_geoip_loaded(self, geoip: dict) -> bool:
        self._geoip_filter_switch.set_active(geoip.get("enabled", False))

        db_info = geoip.get("database", _("Nicht installiert"))
        db_date = geoip.get("database_date", "")
        if db_date:
            self._geoip_db_row.set_subtitle(f"{db_info} ({_('Stand')}: {db_date})")
        else:
            self._geoip_db_row.set_subtitle(str(db_info))

        countries = geoip.get("allowed_countries", [])
        if countries:
            self._geoip_countries_row.set_subtitle(", ".join(countries))
        else:
            self._geoip_countries_row.set_subtitle(_("Keine konfiguriert (alle erlaubt)"))
        return False

    def _load_fail2ban(self) -> None:
        """Fail2ban-Status laden."""
        def worker():
            try:
                f2b = self.api_client.firewall_fail2ban_status()
            except Exception as e:
                logger.warning(f"Fail2ban-Status laden fehlgeschlagen: {e}")
                f2b = {}
            GLib.idle_add(self._on_fail2ban_loaded, f2b)

        threading.Thread(target=worker, daemon=True).start()

