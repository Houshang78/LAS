"""Firewall & Sicherheit: IP-Filter, GeoIP, Fail2ban, Auto-Block, Protokoll."""

from __future__ import annotations

import ipaddress
import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Pango

from lotto_common.i18n import _
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_analyzer.ui.ui_helpers import show_toast
from lotto_common.config import ConfigManager
from lotto_common.utils.logging_config import get_logger

logger = get_logger("security_page")


from lotto_analyzer.ui.pages.security.part1 import Part1Mixin
from lotto_analyzer.ui.pages.security.part2 import Part2Mixin
from lotto_analyzer.ui.pages.security.part3 import Part3Mixin


class SecurityPage(Part1Mixin, Part2Mixin, Part3Mixin, BasePage):
    """Firewall- und Sicherheitsverwaltung."""

    _LIST_PAGE_SIZE = 100
    _LOG_PAGE_SIZE = 50
    _AUDIT_DEBOUNCE_MS = 500
    _SCROLL_DELAY_MS = 50
    _CHAT_MIN_HEIGHT = 200
    _CHAT_MAX_HEIGHT = 400

    def __init__(self, config_manager: ConfigManager, db: Database | None, app_mode: str, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager=config_manager, db=db, app_mode=app_mode, api_client=api_client,
                         app_db=app_db, backtest_db=backtest_db)
        self._log_offset = 0
        self._sec_chat_sending = False
        # Vollständige Listen (für "Alle laden")
        self._whitelist_all: list = []
        self._blacklist_all: list = []
        self._auto_blocked_all: list = []
        self._action_buttons: list = []
        self._build_ui()
        self.refresh()

    def set_user_role(self, role: str) -> None:
        """Benutzerrolle setzen und alle Aktions-Buttons einschraenken."""
        super().set_user_role(role)
        if self._is_readonly:
            # Firewall-Switch deaktivieren (kein normaler Button)
            self._fw_active_switch.set_sensitive(False)

    def cleanup(self) -> None:
        """Audit-Debounce Timer aufräumen."""
        if hasattr(self, "_audit_save_timer") and self._audit_save_timer:
            GLib.source_remove(self._audit_save_timer)
            self._audit_save_timer = None
        super().cleanup()

    # ──────────────────────────────────────────────────────────────────
    #  UI aufbauen
    # ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        self.append(scrolled)

        clamp = Adw.Clamp(maximum_size=900)
        scrolled.set_child(clamp)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        clamp.set_child(content)

        title = Gtk.Label(label=_("Firewall & Sicherheit"))
        title.add_css_class("title-1")
        content.append(title)

        # ── 1. Firewall-Status ──
        self._build_status_section(content)

        # ── 2. IP-Whitelist ──
        self._build_whitelist_section(content)

        # ── 3. IP-Blacklist (manuell) ──
        self._build_blacklist_section(content)

        # ── 4. Automatisch gesperrte IPs ──
        self._build_auto_blocked_section(content)

        # ── 5. Auto-Block Einstellungen ──
        self._build_auto_block_settings_section(content)

        # ── 6. GeoIP-Filter ──
        self._build_geoip_section(content)

        # ── 7. Fail2ban Integration ──
        self._build_fail2ban_section(content)

        # ── 8. IP-Prüfung ──
        self._build_ip_check_section(content)

        # ── 9. Firewall-Protokoll ──
        self._build_log_section(content)

        # ── 10. Erweiterte Sicherheit ──
        self._build_advanced_section(content)

        # ── 11. Audit-Einstellungen ──
        self._build_audit_settings_section(content)

        # ── 12. AI-Sicherheitsassistent ──
        self._build_security_ai_section(content)

        # Aktualisieren-Button
        refresh_box = Gtk.Box(halign=Gtk.Align.CENTER)
        refresh_box.set_margin_top(12)
        refresh_btn = Gtk.Button(label=_("Status aktualisieren"))
        refresh_btn.add_css_class("pill")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        refresh_box.append(refresh_btn)
        content.append(refresh_box)

