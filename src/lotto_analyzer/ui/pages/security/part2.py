"""UI-Seite security: part2 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("security.part2")


class Part2Mixin:
    """Part2 Mixin."""

    # ── Sektion 5: Auto-Block Einstellungen ──

    def _build_auto_block_settings_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Auto-Block Einstellungen"),
            description=_("Automatische Sperre bei wiederholten Fehlversuchen"),
        )
        content.append(group)

        self._auto_block_switch = Adw.SwitchRow(
            title=_("Auto-Sperre aktiv"),
            subtitle=_("IPs nach zu vielen Fehlversuchen automatisch sperren"),
        )
        group.add(self._auto_block_switch)

        self._max_attempts_spin = Adw.SpinRow.new_with_range(1, 20, 1)
        self._max_attempts_spin.set_title(_("Max. Fehlversuche"))
        self._max_attempts_spin.set_value(3)
        group.add(self._max_attempts_spin)

        self._time_window_spin = Adw.SpinRow.new_with_range(5, 120, 5)
        self._time_window_spin.set_title(_("Zeitfenster (Min.)"))
        self._time_window_spin.set_value(30)
        group.add(self._time_window_spin)

        self._block_duration_spin = Adw.SpinRow.new_with_range(0, 10080, 10)
        self._block_duration_spin.set_title(_("Sperrdauer (Min.)"))
        self._block_duration_spin.set_subtitle(_("0 = dauerhaft"))
        self._block_duration_spin.set_value(1440)
        group.add(self._block_duration_spin)

        save_row = Adw.ActionRow(title="")
        save_btn = Gtk.Button(label=_("Speichern"))
        save_btn.add_css_class("suggested-action")
        save_btn.set_valign(Gtk.Align.CENTER)
        save_btn.connect("clicked", self._on_save_auto_block_settings)
        save_row.add_suffix(save_btn)
        self.register_readonly_button(save_btn)
        self._auto_block_status = Gtk.Label()
        self._auto_block_status.set_valign(Gtk.Align.CENTER)
        save_row.add_suffix(self._auto_block_status)
        group.add(save_row)

    # ── Sektion 6: GeoIP-Filter ──

    def _build_geoip_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("GeoIP-Filter"),
            description=_("Laenderspezifische Zugriffskontrolle"),
        )
        content.append(group)

        self._geoip_filter_switch = Adw.SwitchRow(
            title=_("GeoIP-Filter aktiv"),
            subtitle=_("Zugriff nur aus erlaubten Ländern"),
        )
        group.add(self._geoip_filter_switch)

        update_btn = Gtk.Button(label=_("DB aktualisieren"))
        update_btn.set_tooltip_text(_("GeoIP-Datenbank aktualisieren"))
        update_btn.set_valign(Gtk.Align.CENTER)
        update_btn.connect("clicked", self._on_geoip_update)
        self._geoip_db_row = Adw.ActionRow(
            title=_("GeoIP-Datenbank"),
            subtitle=_("Unbekannt"),
        )
        self._geoip_db_row.add_suffix(update_btn)
        group.add(self._geoip_db_row)

        self._geoip_countries_row = Adw.ActionRow(
            title=_("Erlaubte Laender"),
            subtitle=_("Keine konfiguriert"),
        )
        group.add(self._geoip_countries_row)

        self._geoip_whitelist_bypass = Adw.SwitchRow(
            title=_("Whitelist umgeht GeoIP"),
            subtitle=_("IPs in der Whitelist werden vom GeoIP-Filter ausgenommen"),
        )
        group.add(self._geoip_whitelist_bypass)

    # ── Sektion 7: Fail2ban Integration ──

    def _build_fail2ban_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Fail2ban Integration"),
            description=_("Systemweite Intrusion Prevention"),
        )
        content.append(group)

        self._f2b_status_row = Adw.ActionRow(
            title=_("Status"),
            subtitle=_("Wird geprüft..."),
        )
        group.add(self._f2b_status_row)

        self._f2b_jail_row = Adw.ActionRow(
            title=_("Jail"),
            subtitle=_("Wird geprüft..."),
        )
        group.add(self._f2b_jail_row)

        self._f2b_banned_row = Adw.ActionRow(
            title=_("Gebannte IPs"),
            subtitle="0",
        )
        group.add(self._f2b_banned_row)

        btn_row = Adw.ActionRow(title=_("Aktionen"))

        self._f2b_install_btn = Gtk.Button(label=_("Installieren"))
        self._f2b_install_btn.set_valign(Gtk.Align.CENTER)
        self._f2b_install_btn.connect("clicked", self._on_f2b_install)
        btn_row.add_suffix(self._f2b_install_btn)

        self._f2b_configure_btn = Gtk.Button(label=_("Jail konfigurieren"))
        self._f2b_configure_btn.add_css_class("suggested-action")
        self._f2b_configure_btn.set_valign(Gtk.Align.CENTER)
        self._f2b_configure_btn.connect("clicked", self._on_f2b_configure)
        btn_row.add_suffix(self._f2b_configure_btn)

        self._f2b_remove_btn = Gtk.Button(label=_("Jail entfernen"))
        self._f2b_remove_btn.add_css_class("destructive-action")
        self._f2b_remove_btn.set_valign(Gtk.Align.CENTER)
        self._f2b_remove_btn.connect("clicked", self._on_f2b_remove)
        btn_row.add_suffix(self._f2b_remove_btn)

        self._action_buttons.extend([
            self._f2b_install_btn, self._f2b_configure_btn, self._f2b_remove_btn,
        ])
        group.add(btn_row)

    # ── Sektion 8: IP-Prüfung ──

    def _build_ip_check_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("IP-Prüfung"),
            description=_("Einzelne IP-Adresse gegen alle Regeln prüfen"),
        )
        content.append(group)

        self._ip_check_entry = Adw.EntryRow(title=_("IP-Adresse eingeben"))
        group.add(self._ip_check_entry)

        check_row = Adw.ActionRow(title="")
        check_btn = Gtk.Button(label=_("Prüfen"))
        check_btn.set_tooltip_text(_("IP-Adresse prüfen: Whitelist, Blacklist, GeoIP-Status"))
        check_btn.add_css_class("suggested-action")
        check_btn.set_valign(Gtk.Align.CENTER)
        check_btn.connect("clicked", self._on_check_ip)
        check_row.add_suffix(check_btn)
        group.add(check_row)

        self._ip_check_result = Gtk.Label()
        self._ip_check_result.set_wrap(True)
        self._ip_check_result.set_margin_start(12)
        self._ip_check_result.set_margin_end(12)
        self._ip_check_result.set_halign(Gtk.Align.START)
        group.add(self._ip_check_result)

