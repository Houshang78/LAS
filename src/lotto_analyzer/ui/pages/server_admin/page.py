"""Server-Verwaltung: Service, Benutzer, Audit-Log, TLS, Scheduler, ML, DB."""

from __future__ import annotations

import shutil
import subprocess
import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.i18n import _
from lotto_common.config import ConfigManager
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_common.models.user import ALL_PERMISSIONS, DEFAULT_USER_PERMISSIONS
from lotto_analyzer.ui.ui_helpers import show_error_toast
from lotto_analyzer.ui.widgets.help_button import HelpButton
from lotto_common.utils.logging_config import get_logger

logger = get_logger("server_admin_page")

# Verfügbare Rollen
USER_ROLES = ["user", "admin", "readonly"]

# Anzeigenamen für Permissions
_PERM_LABELS = {
    "db_edit": _("Datenbank bearbeiten"),
    "generator": _("Zahlen generieren"),
    "ml": _("ML-Training"),
    "telegram": _("Telegram-Verwaltung"),
    "predictions": _("Vorhersagen"),
    "settings": _("Einstellungen ändern"),
    "statistics": _("Statistiken"),
    "reports": _("Berichte"),
    "crawl": _("Daten-Crawling"),
    "firewall": _("Firewall-Verwaltung"),
}

try:
    from lotto_analyzer.server.service import (
        is_service_running, is_service_enabled, service_action,
    )
except ImportError:
    # Standalone-Client: Server-Module nicht verfügbar
    def is_service_running() -> bool: return False
    def is_service_enabled() -> bool: return False
    def service_action(action: str) -> tuple[bool, str]: return False, _("Server-Module nicht verfügbar")


from lotto_analyzer.ui.pages.server_admin.part1 import Part1Mixin
from lotto_analyzer.ui.pages.server_admin.part2 import Part2Mixin
from lotto_analyzer.ui.pages.server_admin.part3 import Part3Mixin
from lotto_analyzer.ui.pages.server_admin.part4 import Part4Mixin


from lotto_analyzer.ui.pages.server_admin.build_ui import BuildUIMixin


class ServerAdminPage(BuildUIMixin, Part1Mixin, Part2Mixin, Part3Mixin, Part4Mixin, BasePage):
    """Server-Verwaltungsseite (nur im Server-Modus)."""

    _FEEDBACK_DELAY_MS = 1000
    _PASSWORD_DISPLAY_MS = 10000
    _BACKUP_LABEL_RESTORE_MS = 5000
    _TELEGRAM_LOG_LIMIT = 200
    _DIALOG_WIDTH = 450
    _PERM_DIALOG_WIDTH = 400
    _PERM_DIALOG_HEIGHT = 450
    _TG_LOG_DIALOG_WIDTH = 600
    _TG_LOG_DIALOG_HEIGHT = 500

    def __init__(self, config_manager: ConfigManager, db: Database | None, app_mode: str, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager=config_manager, db=db, app_mode=app_mode, api_client=api_client,
                         app_db=app_db, backtest_db=backtest_db)

        self._build_ui()
        self._load_status()

    def cleanup(self) -> None:
        """Feedback-Timer aufräumen."""
        super().cleanup()

    def refresh(self) -> None:
        """Status nur neu laden wenn veraltet (>5min)."""
        if self.is_stale() and self.api_client:
            self._load_status()

    # _build_ui is provided by BuildUIMixin


    def _load_status(self) -> None:
        """Status-Informationen laden (im Hintergrund-Thread)."""
        if self.api_client and not self.db:
            # Client-Modus: alles via API
            def api_worker():
                ssh_keys, certificates = [], []
                try:
                    health = self.api_client.health()
                    db_stats = self.api_client.get_db_stats()
                    ml_info = self.api_client.ml_status()
                    users = self.api_client.list_users()
                    audit_entries = self.api_client.get_audit_log(limit=self._audit_limit)
                except Exception as e:
                    logger.warning(f"Server-Status Abfrage fehlgeschlagen: {e}")
                    health, db_stats, ml_info = {}, None, None
                    users, audit_entries = [], []
                try:
                    # SSH-Keys und Zertifikate für alle User laden
                    for u in users:
                        uid = u.get("id")
                        if uid:
                            ssh_keys.extend(self.api_client.list_user_keys(uid))
                    certificates = self.api_client.list_certificates()
                except Exception as e:
                    logger.warning(f"SSH-Keys/Zertifikate laden fehlgeschlagen: {e}")
                tls_info = {"status": f"Server: {health.get('version', '?')}", "expires": None}
                api_key_display = "****...****"
                # Telegram-Bots laden
                tg_bots = []
                try:
                    tg_bots = self.api_client.admin_list_telegram_bots()
                except Exception as e:
                    logger.warning(f"Telegram-Bots laden fehlgeschlagen: {e}")
                GLib.idle_add(
                    self._on_status_loaded, True, True, db_stats,
                    ml_info, tls_info, users, audit_entries, api_key_display,
                    ssh_keys, certificates,
                )
                GLib.idle_add(self._update_telegram_bots_ui, tg_bots)
                GLib.idle_add(lambda: (self._load_le_status(), False)[-1])
            threading.Thread(target=api_worker, daemon=True).start()
            return

        def worker():
            running = is_service_running()
            enabled = is_service_enabled()

            db_stats = None
            if self.db:
                try:
                    db_stats = self.db.get_db_stats()
                except Exception as e:
                    logger.warning(f"DB-Stats laden fehlgeschlagen: {e}")

            ml_info = None
            if self.db:
                try:
                    with self.db.connection() as conn:
                        row = conn.execute(
                            "SELECT * FROM ml_models ORDER BY last_trained DESC LIMIT 1"
                        ).fetchone()
                        if row:
                            ml_info = dict(row)
                except Exception as e:
                    logger.warning(f"ML-Modelle Abfrage fehlgeschlagen: {e}")

            # TLS-Status
            tls_info = self._check_tls()

            # Benutzer und Audit laden (falls User-DB vorhanden)
            users = []
            audit_entries = []
            api_key_display = "****...****"
            ssh_keys = []
            certificates = []
            try:
                from lotto_analyzer.server.user_db import UserDatabase
                user_db_path = self.config_manager.data_dir / "users.db"
                if user_db_path.exists():
                    udb = UserDatabase(user_db_path)
                    users = udb.list_users()
                    audit_entries = udb.get_audit_log(limit=self._audit_limit)
                    keys = udb.list_api_keys()
                    if keys:
                        api_key_display = f"{keys[0].get('key_prefix', '****')}...****"
                    ssh_keys = udb.list_public_keys()
                    certificates = udb.list_certificates()
            except Exception as e:
                logger.warning(f"Benutzer/Audit laden fehlgeschlagen: {e}")

            GLib.idle_add(
                self._on_status_loaded, running, enabled, db_stats,
                ml_info, tls_info, users, audit_entries, api_key_display,
                ssh_keys, certificates,
            )

        threading.Thread(target=worker, daemon=True).start()

    def _check_tls(self) -> dict:
        """TLS-Zertifikat-Status prüfen."""
        config = self.config_manager.config
        if not config.server.ssl_certfile:
            return {"status": _("Nicht konfiguriert"), "expires": None}
        try:
            from lotto_analyzer.server.tls import check_cert_valid
            expires = check_cert_valid(config.server.ssl_certfile)
            if expires:
                return {
                    "status": f"Aktiv (bis {expires.strftime('%Y-%m-%d')})",
                    "expires": str(expires),
                }
            return {"status": _("Ungültig"), "expires": None}
        except Exception as e:
            return {"status": f"Fehler: {e}", "expires": None}

    def _on_status_loaded(
        self, running: bool, enabled: bool,
        db_stats: dict | None, ml_info: dict | None,
        tls_info: dict, users: list, audit_entries: list,
        api_key_display: str,
        ssh_keys: list | None = None, certificates: list | None = None,
    ) -> bool:
        # TLS
        self._tls_status.set_subtitle(tls_info.get("status", "—"))

        # Benutzer
        while True:
            row = self._user_list_box.get_row_at_index(0)
            if row is None:
                break
            self._user_list_box.remove(row)

        for user in users:
            perms = user.get("permissions", [])
            perms_str = ", ".join(perms) if perms else _("(keine)")
            label = (
                f"{user.get('username', '?')} "
                f"({user.get('role', '?')}) – "
                f"{_('Aktiv') if user.get('is_active') else _('Deaktiviert')}"
            )
            subtitle = f"{_('Berechtigungen')}: {perms_str}"
            if user.get("last_login"):
                subtitle += f" | {_('Letzter Login')}: {user['last_login']}"
            row = Adw.ActionRow(title=label, subtitle=subtitle)

            # Berechtigungen-Button
            perm_btn = Gtk.Button(label=_("Rechte"))
            perm_btn.set_valign(Gtk.Align.CENTER)
            perm_btn.set_tooltip_text(_("Benutzer-Berechtigungen bearbeiten"))
            perm_btn.connect(
                "clicked", self._on_edit_permissions,
                user.get("id"), user.get("username", "?"),
                user.get("role", "user"), perms,
            )
            row.add_suffix(perm_btn)

            # Reset-Button
            reset_btn = Gtk.Button(label=_("PW Reset"))
            reset_btn.set_valign(Gtk.Align.CENTER)
            reset_btn.set_tooltip_text(_("Passwort-Reset per E-Mail senden"))
            reset_btn.connect("clicked", self._on_reset_password, user.get("id"))
            row.add_suffix(reset_btn)

            # Deaktivieren/Aktivieren-Button
            if user.get("is_active"):
                deact_btn = Gtk.Button(label=_("Deaktivieren"))
                deact_btn.add_css_class("destructive-action")
                deact_btn.set_tooltip_text(_("Benutzerkonto deaktivieren"))
            else:
                deact_btn = Gtk.Button(label=_("Aktivieren"))
                deact_btn.add_css_class("suggested-action")
                deact_btn.set_tooltip_text(_("Benutzerkonto aktivieren"))
            deact_btn.set_valign(Gtk.Align.CENTER)
            deact_btn.connect(
                "clicked", self._on_toggle_user,
                user.get("id"), user.get("is_active"),
            )
            row.add_suffix(deact_btn)

            # Disconnect-Button
            disc_btn = Gtk.Button(label=_("Disconnect"))
            disc_btn.set_valign(Gtk.Align.CENTER)
            disc_btn.set_tooltip_text(_("Aktive Sitzung des Benutzers trennen"))
            disc_btn.connect(
                "clicked", self._on_disconnect_user,
                user.get("id"), user.get("username", "?"),
            )
            row.add_suffix(disc_btn)

            # Ban-Button
            ban_btn = Gtk.Button(label=_("Bannen"))
            ban_btn.add_css_class("destructive-action")
            ban_btn.set_valign(Gtk.Align.CENTER)
            ban_btn.set_tooltip_text(_("Benutzer dauerhaft sperren"))
            ban_btn.connect(
                "clicked", self._on_ban_user,
                user.get("id"), user.get("username", "?"),
            )
            row.add_suffix(ban_btn)

            # Entfernen-Button
            del_btn = Gtk.Button(label=_("Entfernen"))
            del_btn.add_css_class("destructive-action")
            del_btn.set_valign(Gtk.Align.CENTER)
            del_btn.set_tooltip_text(_("Benutzerkonto unwiderruflich löschen"))
            del_btn.connect(
                "clicked", self._on_delete_user,
                user.get("id"), user.get("username", "?"),
            )
            row.add_suffix(del_btn)

            self._user_list_box.append(row)

        if not users:
            self._user_list_box.append(
                Adw.ActionRow(title=_("Keine Benutzer gefunden"))
            )

        # API-Key
        self._api_key_display.set_subtitle(api_key_display)

        # Audit-Log
        while True:
            row = self._audit_list.get_row_at_index(0)
            if row is None:
                break
            self._audit_list.remove(row)
        self._audit_checks.clear()
        self._audit_select_all.set_active(False)

        for entry in audit_entries[:self._audit_limit]:
            ts = entry.get("timestamp", "—")
            user = entry.get("username", "—")
            action = entry.get("action", "—")
            endpoint = entry.get("endpoint", "")
            status = entry.get("status_code", 0)

            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.CENTER)
            check.connect("toggled", self._on_audit_check_toggled)

            row = Adw.ActionRow(
                title=f"{ts} | {user} | {action}",
                subtitle=f"{entry.get('method', '')} {endpoint} → {status} | {entry.get('ip_address', '')}",
            )
            row.add_prefix(check)
            self._audit_list.append(row)
            self._audit_checks.append((check, entry))

        if not audit_entries:
            self._audit_list.append(
                Adw.ActionRow(title=_("Keine Einträge"))
            )

        # Service
        if running:
            self._service_status.set_subtitle(_("Aktiv (läuft)"))
        else:
            self._service_status.set_subtitle(_("Inaktiv (gestoppt)"))

        self._autostart.handler_block_by_func(self._on_autostart_toggled)
        self._autostart.set_active(enabled)
        self._autostart.handler_unblock_by_func(self._on_autostart_toggled)

        # DB
        if db_stats:
            self._db_size.set_subtitle(f"{db_stats.get('db_size_mb', 0)} MB")
            sat = db_stats.get("draws_saturday", 0)
            wed = db_stats.get("draws_wednesday", 0)
            self._db_draws.set_subtitle(f"{_('Samstag')}: {sat} | {_('Mittwoch')}: {wed}")

        # ML
        if ml_info:
            last_trained = ml_info.get("last_trained", "—")
            self._ml_status.set_subtitle(str(last_trained))
            accuracy = ml_info.get("accuracy", 0)
            self._ml_accuracy.set_subtitle(f"{accuracy:.1%}" if accuracy else "—")
        else:
            self._ml_status.set_subtitle(_("Kein Modell trainiert"))
            self._ml_accuracy.set_subtitle("—")

        # SSH-Keys
        while True:
            row = self._ssh_key_list.get_row_at_index(0)
            if row is None:
                break
            self._ssh_key_list.remove(row)

        for key in (ssh_keys or []):
            fp = key.get("fingerprint", "—")
            row = Adw.ActionRow(
                title=f"{key.get('username', '?')} — {key.get('key_type', '?')}",
                subtitle=f"{fp} | {key.get('description', '')} | Erstellt: {key.get('created_at', '—')}",
            )
            rm_btn = Gtk.Button(label=_("Entfernen"))
            rm_btn.add_css_class("destructive-action")
            rm_btn.set_valign(Gtk.Align.CENTER)
            rm_btn.set_tooltip_text(_("SSH-Key entfernen"))
            rm_btn.connect("clicked", self._on_remove_ssh_key, fp)
            row.add_suffix(rm_btn)
            self._ssh_key_list.append(row)

        if not ssh_keys:
            self._ssh_key_list.append(
                Adw.ActionRow(title=_("Keine SSH-Keys registriert"))
            )

        # Client-Zertifikate
        while True:
            row = self._cert_list.get_row_at_index(0)
            if row is None:
                break
            self._cert_list.remove(row)

        for cert in (certificates or []):
            serial = cert.get("serial_number", "—")
            short_serial = serial[:18] + ".." if len(serial) > 20 else serial
            revoked = f" [{_('WIDERRUFEN')}]" if cert.get("is_revoked") else ""
            row = Adw.ActionRow(
                title=f"{cert.get('username', '?')} — {short_serial}{revoked}",
                subtitle=f"{_('Gueltig bis')}: {cert.get('expires_at', '—')} | {cert.get('description', '')}",
            )
            if not cert.get("is_revoked"):
                rev_btn = Gtk.Button(label=_("Widerrufen"))
                rev_btn.add_css_class("destructive-action")
                rev_btn.set_valign(Gtk.Align.CENTER)
                rev_btn.set_tooltip_text(_("Zertifikat widerrufen"))
                rev_btn.connect("clicked", self._on_revoke_cert, serial)
                row.add_suffix(rev_btn)
            self._cert_list.append(row)

        if not certificates:
            self._cert_list.append(
                Adw.ActionRow(title=_("Keine Zertifikate ausgestellt"))
            )

        return False


# TODO: Diese Datei ist >500Z weil: GTK4 Admin-Page mit 4 Part-Mixins, viele Tab-Initialisierungen
