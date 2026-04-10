"""UI-Seite server_admin: part1 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("server_admin.part1")


class Part1Mixin:
    """Part1 Mixin."""

    # ── TLS ──

    def _on_generate_cert(self, button: Gtk.Button) -> None:
        button.set_sensitive(False)
        self._cert_row.set_subtitle(_("Generiere..."))

        def worker():
            try:
                from lotto_analyzer.server.tls import generate_self_signed_cert
                cert_dir = self.config_manager._config_dir / "tls"
                cert_path = cert_dir / "server.crt"
                key_path = cert_dir / "server.key"
                cert_file, key_file = generate_self_signed_cert(cert_path, key_path)
                self.config_manager.config.server.ssl_certfile = cert_file
                self.config_manager.config.server.ssl_keyfile = key_file
                self.config_manager.save()
                GLib.idle_add(self._on_cert_done, cert_file, None, button)
            except Exception as e:
                GLib.idle_add(self._on_cert_done, "", str(e), button)

        threading.Thread(target=worker, daemon=True).start()

    def _on_cert_done(self, path: str, error: str | None, button: Gtk.Button | None = None) -> bool:
        if button:
            button.set_sensitive(True)
        if error:
            self._cert_row.set_subtitle(f"Fehler: {error}")
        else:
            self._cert_row.set_subtitle(f"Erstellt: {path}")
            self._tls_status.set_subtitle(_("Aktiv (neues Zertifikat)"))
        return False

    # ── Let's Encrypt ──

    def _load_le_status(self) -> None:
        """LE-Config + TLS-Status vom Server laden."""
        if not self.api_client:
            return

        def worker():
            try:
                le_config = self.api_client.tls_le_config()
                tls_info = self.api_client.tls_status()
            except Exception as e:
                logger.warning(f"LE/TLS-Status laden fehlgeschlagen: {e}")
                le_config, tls_info = {}, {}
            GLib.idle_add(self._on_le_status_loaded, le_config, tls_info)

        threading.Thread(target=worker, daemon=True).start()

    def _on_le_status_loaded(self, le_config: dict, tls_info: dict) -> bool:
        """LE-Status in UI uebernehmen."""
        # Felder befuellen
        self._le_domain.set_text(le_config.get("domain", ""))
        self._le_email.set_text(le_config.get("email", ""))
        self._le_webroot.set_text(le_config.get("webroot", ""))

        method = le_config.get("method", "webroot")
        self._le_method.set_selected(0 if method == "webroot" else 1)
        self._le_auto_renew.set_active(le_config.get("auto_renew", True))

        # Status-Zeile
        if tls_info.get("status") == "no_cert":
            self._le_status.set_subtitle(_("Kein Zertifikat konfiguriert"))
        elif tls_info.get("issuer"):
            is_ss = tls_info.get("is_self_signed", True)
            days = tls_info.get("days_remaining", 0)
            issuer = tls_info.get("issuer", "?")
            status_text = "Self-Signed" if is_ss else f"{issuer} (trusted)"
            self._le_status.set_subtitle(
                f"{status_text} — {_('gültig noch')} {days} {_('Tage')}"
            )
        else:
            self._le_status.set_subtitle(_("Status unbekannt"))

        # certbot-Verfügbarkeit
        if not le_config.get("certbot_available", False):
            self._le_request_btn.set_tooltip_text("certbot nicht installiert")
            self._le_renew_btn.set_tooltip_text("certbot nicht installiert")

        return False

    def _on_le_request(self, button: Gtk.Button) -> None:
        """Neues LE-Zertifikat anfordern."""
        domain = self._le_domain.get_text().strip()
        email = self._le_email.get_text().strip()
        webroot = self._le_webroot.get_text().strip()

        if not domain or not email or not webroot:
            self._le_status.set_subtitle(_("Fehler: Domain, E-Mail und Webroot erforderlich"))
            return

        button.set_sensitive(False)
        self._le_status.set_subtitle(_("Zertifikat wird angefordert..."))

        def worker():
            try:
                result = self.api_client.tls_le_request(domain, email, webroot)
                GLib.idle_add(self._on_le_action_done, result, button)
            except Exception as e:
                GLib.idle_add(
                    self._on_le_action_done,
                    {"status": "error", "error": str(e)},
                    button,
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_le_renew(self, button: Gtk.Button) -> None:
        """LE-Cert manuell erneuern."""
        button.set_sensitive(False)
        self._le_status.set_subtitle(_("Erneuerung läuft..."))

        def worker():
            try:
                result = self.api_client.tls_le_renew()
                GLib.idle_add(self._on_le_action_done, result, button)
            except Exception as e:
                GLib.idle_add(
                    self._on_le_action_done,
                    {"status": "error", "error": str(e)},
                    button,
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_le_detect(self, button: Gtk.Button) -> None:
        """Vorhandenes LE-Cert suchen."""
        domain = self._le_domain.get_text().strip()
        button.set_sensitive(False)
        self._le_status.set_subtitle(_("Suche vorhandenes Zertifikat..."))

        def worker():
            try:
                result = self.api_client.tls_le_detect(domain)
                GLib.idle_add(self._on_le_detect_done, result, button)
            except Exception as e:
                GLib.idle_add(self._on_le_detect_done, {"status": "error", "error": str(e)}, button)

        threading.Thread(target=worker, daemon=True).start()

    def _on_le_detect_done(self, result: dict, button: Gtk.Button) -> bool:
        """Ergebnis der Cert-Erkennung."""
        button.set_sensitive(True)
        if result.get("status") == "found":
            info = result.get("cert_info", {})
            issuer = info.get("issuer", "?")
            days = info.get("days_remaining", 0)
            path = info.get("path", "")
            self._le_status.set_subtitle(
                f"Gefunden: {issuer} — {days} Tage gültig — {path}"
            )
        elif result.get("status") == "error":
            self._le_status.set_subtitle(f"Fehler: {result.get('error', '?')}")
        else:
            self._le_status.set_subtitle(_("Kein vorhandenes Zertifikat gefunden"))
        return False

    def _on_le_action_done(self, result: dict, button: Gtk.Button) -> bool:
        """Ergebnis einer LE-Aktion (Request/Renew)."""
        button.set_sensitive(True)
        if result.get("status") == "ok":
            msg = result.get("message", "Erfolgreich")
            self._le_status.set_subtitle(f"OK: {msg}")
            # Status neu laden
            GLib.timeout_add(self._FEEDBACK_DELAY_MS, lambda: (self._load_le_status(), False)[-1])
        else:
            self._le_status.set_subtitle(f"Fehler: {result.get('error', '?')}")
        return False

    def _on_le_save_config(self, button: Gtk.Button) -> None:
        """LE-Config zum Server senden."""
        method_idx = self._le_method.get_selected()
        method = "webroot" if method_idx == 0 else "existing"

        data = {
            "domain": self._le_domain.get_text().strip(),
            "email": self._le_email.get_text().strip(),
            "webroot": self._le_webroot.get_text().strip(),
            "method": method,
            "auto_renew": self._le_auto_renew.get_active(),
            "enabled": True,
        }

        button.set_sensitive(False)

        def worker():
            try:
                result = self.api_client.tls_le_update_config(data)
                GLib.idle_add(self._on_le_save_done, result, button)
            except Exception as e:
                GLib.idle_add(self._on_le_save_done, {"status": "error", "error": str(e)}, button)

        threading.Thread(target=worker, daemon=True).start()

    def _on_le_save_done(self, result: dict, button: Gtk.Button) -> bool:
        button.set_sensitive(True)
        if result.get("status") == "updated":
            fields = result.get("updated_fields", [])
            self._le_status.set_subtitle(f"Gespeichert ({len(fields)} Felder)")
        else:
            self._le_status.set_subtitle(f"Fehler: {result.get('error', '?')}")
        return False

