"""UI-Seite security: part1 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("security.part1")


class Part1Mixin:
    """Part1 Mixin."""

    # ── Sektion 1: Firewall-Status ──

    def _build_status_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Firewall-Status"),
            description=_("Übersicht der aktuellen Firewall-Konfiguration"),
        )
        content.append(group)

        self._fw_active_switch = Adw.SwitchRow(
            title=_("Firewall aktiv"),
            subtitle=_("IP-basierte Zugriffskontrolle"),
        )
        self._fw_active_switch.connect("notify::active", self._on_firewall_toggled)
        group.add(self._fw_active_switch)

        self._blocked_count_row = Adw.ActionRow(
            title=_("Blockierte IPs"),
            subtitle="0",
        )
        group.add(self._blocked_count_row)

        self._failed_logins_row = Adw.ActionRow(
            title=_("Fehlgeschlagene Logins (24h)"),
            subtitle="0",
        )
        group.add(self._failed_logins_row)

        self._geoip_status_row = Adw.ActionRow(
            title=_("GeoIP-Status"),
            subtitle=_("Unbekannt"),
        )
        group.add(self._geoip_status_row)

    # ── Sektion 2: IP-Whitelist ──

    def _build_whitelist_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("IP-Whitelist"),
            description=_("Immer erlaubte IP-Adressen und Netzwerke"),
        )
        content.append(group)

        self._whitelist_info_row = Adw.ActionRow(title=_("Einträge"), subtitle="0")
        self._whitelist_load_all_btn = Gtk.Button(label=_("Alle laden"))
        self._whitelist_load_all_btn.set_tooltip_text(_("Alle Whitelist-Einträge anzeigen"))
        self._whitelist_load_all_btn.set_valign(Gtk.Align.CENTER)
        self._whitelist_load_all_btn.set_visible(False)
        self._whitelist_load_all_btn.connect(
            "clicked", lambda _: self._on_whitelist_loaded(self._whitelist_all, show_all=True),
        )
        self._whitelist_info_row.add_suffix(self._whitelist_load_all_btn)
        group.add(self._whitelist_info_row)

        self._whitelist_box = Gtk.ListBox()
        self._whitelist_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._whitelist_box.add_css_class("boxed-list")
        group.add(self._whitelist_box)

        btn_row = Adw.ActionRow(title=_("Aktionen"))
        add_btn = Gtk.Button(label=_("IP/Netzwerk hinzufügen"))
        add_btn.set_tooltip_text(_("IP-Adresse oder Netzwerk zur Whitelist hinzufügen"))
        add_btn.add_css_class("suggested-action")
        add_btn.set_valign(Gtk.Align.CENTER)
        add_btn.connect("clicked", self._on_add_whitelist)
        btn_row.add_suffix(add_btn)
        self.register_readonly_button(add_btn)
        group.add(btn_row)

    # ── Sektion 3: IP-Blacklist (manuell) ──

    def _build_blacklist_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("IP-Blacklist (Manuell)"),
            description=_("Manuell gesperrte IP-Adressen und Netzwerke"),
        )
        content.append(group)

        self._blacklist_info_row = Adw.ActionRow(title=_("Einträge"), subtitle="0")
        self._blacklist_load_all_btn = Gtk.Button(label=_("Alle laden"))
        self._blacklist_load_all_btn.set_tooltip_text(_("Alle Blacklist-Einträge anzeigen"))
        self._blacklist_load_all_btn.set_valign(Gtk.Align.CENTER)
        self._blacklist_load_all_btn.set_visible(False)
        self._blacklist_load_all_btn.connect(
            "clicked", lambda _: self._on_blacklist_loaded(self._blacklist_all, show_all=True),
        )
        self._blacklist_info_row.add_suffix(self._blacklist_load_all_btn)
        group.add(self._blacklist_info_row)

        self._blacklist_box = Gtk.ListBox()
        self._blacklist_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._blacklist_box.add_css_class("boxed-list")
        group.add(self._blacklist_box)

        btn_row = Adw.ActionRow(title=_("Aktionen"))
        add_btn = Gtk.Button(label=_("IP/Netzwerk sperren"))
        add_btn.set_tooltip_text(_("IP-Adresse oder Netzwerk zur Blacklist hinzufügen"))
        add_btn.add_css_class("destructive-action")
        add_btn.set_valign(Gtk.Align.CENTER)
        add_btn.connect("clicked", self._on_add_blacklist)
        btn_row.add_suffix(add_btn)
        self.register_readonly_button(add_btn)
        group.add(btn_row)

    # ── Sektion 4: Automatisch gesperrte IPs ──

    def _build_auto_blocked_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Automatisch gesperrte IPs"),
            description=_("Durch zu viele Fehlversuche gesperrte Adressen"),
        )
        content.append(group)

        self._auto_blocked_info_row = Adw.ActionRow(title=_("Einträge"), subtitle="0")
        self._auto_blocked_load_all_btn = Gtk.Button(label=_("Alle laden"))
        self._auto_blocked_load_all_btn.set_tooltip_text(_("Alle auto-gesperrten IPs anzeigen"))
        self._auto_blocked_load_all_btn.set_valign(Gtk.Align.CENTER)
        self._auto_blocked_load_all_btn.set_visible(False)
        self._auto_blocked_load_all_btn.connect(
            "clicked", lambda _: self._on_auto_blocked_loaded(self._auto_blocked_all, show_all=True),
        )
        self._auto_blocked_info_row.add_suffix(self._auto_blocked_load_all_btn)
        group.add(self._auto_blocked_info_row)

        self._auto_blocked_box = Gtk.ListBox()
        self._auto_blocked_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._auto_blocked_box.add_css_class("boxed-list")
        group.add(self._auto_blocked_box)

