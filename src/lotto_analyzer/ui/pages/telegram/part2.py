"""UI-Seite telegram: part2."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("telegram.part2")


class Part2Mixin:
    """Part2 Mixin."""

    def _on_disconnect_done(self, msg: str, error: str | None) -> bool:
        self._disconnect_btn.set_sensitive(True)
        self._conn_spinner.stop()
        self._conn_spinner.set_visible(False)
        if error:
            self._feedback_label.remove_css_class("success")
            self._feedback_label.add_css_class("error")
            self._feedback_label.set_label(f"{_('Fehler')}: {error}")
        else:
            self._feedback_label.remove_css_class("error")
            self._feedback_label.add_css_class("success")
            self._feedback_label.set_label(msg)
        self._load_status()
        return False

    # ══════════════════════════════════════
    # Bot-Link QR (t.me/BOT_USERNAME)
    # ══════════════════════════════════════

    def _load_bot_qr(self) -> bool:
        """Bot-Link QR-Code laden."""
        def worker():
            url = ""
            username = ""
            try:
                if self.api_client:
                    data = self.api_client.telegram_bot_link()
                    url = data.get("url", "")
                    username = data.get("username", "")
            except Exception as e:
                logger.warning(f"Bot-Link Abfrage fehlgeschlagen: {e}")
            GLib.idle_add(self._update_bot_qr, url, username)
        threading.Thread(target=worker, daemon=True).start()
        return False

    def _update_bot_qr(self, url: str, username: str) -> bool:
        if url:
            self._bot_qr_widget.set_url(url)
            self._bot_qr_row.set_subtitle(f"@{username} — {_('QR scannen zum Chatten')}")
        else:
            self._bot_qr_widget.clear()
            self._bot_qr_row.set_subtitle(_("Bot nicht verbunden"))
        return False

    # ══════════════════════════════════════
    # QR-Code-Login (Telethon)
    # ══════════════════════════════════════

    def _on_qr_start(self, btn: Gtk.Button) -> None:
        """QR-Login starten."""
        api_id_text = self._api_id_row.get_text().strip()
        api_hash = self._api_hash_row.get_text().strip()

        if not api_id_text or not api_hash:
            self._qr_status_row.set_subtitle(
                _("API-ID und API-Hash eingeben (von my.telegram.org)")
            )
            return

        try:
            api_id = int(api_id_text)
        except ValueError:
            self._qr_status_row.set_subtitle(_("API-ID muss eine Zahl sein"))
            return

        self._qr_start_btn.set_sensitive(False)
        self._qr_cancel_btn.set_sensitive(True)
        self._qr_spinner.set_visible(True)
        self._qr_spinner.start()
        self._qr_status_row.set_subtitle(_("Starte QR-Login..."))
        self._qr_hint.set_visible(True)

        def worker():
            try:
                if self.api_client:
                    result = self.api_client.telegram_qr_start(
                        api_id=api_id,
                        api_hash=api_hash,
                    )
                    GLib.idle_add(self._on_qr_started, result)
                else:
                    # Standalone: direkt Telethon starten
                    self._start_qr_local(api_id, api_hash)
            except Exception as e:
                GLib.idle_add(self._on_qr_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_qr_started(self, result: dict) -> bool:
        """QR-Login gestartet — URL anzeigen + Polling starten."""
        status = result.get("status", "error")
        qr_url = result.get("qr_url", "")
        error = result.get("error", "")

        if status == "authorized":
            user = result.get("user_name", "")
            self._qr_status_row.set_subtitle(f"{_('Bereits eingeloggt')}: {user}")
            self._qr_widget.clear()
            self._qr_hint.set_visible(False)
            self._qr_spinner.stop()
            self._qr_spinner.set_visible(False)
            self._qr_start_btn.set_sensitive(True)
            self._qr_cancel_btn.set_sensitive(False)
            return False

        if status == "error":
            self._on_qr_error(error)
            return False

        if qr_url:
            self._qr_widget.set_url(qr_url)
            self._qr_status_row.set_subtitle(_("Warte auf Scan..."))

        # WS-Listener für instant QR-Status-Updates
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.on("qr_status", self._on_ws_qr_status)
        except Exception:
            pass
        # Slow fallback polling (WS pushes instant)
        if self._qr_poll_id:
            GLib.source_remove(self._qr_poll_id)
        self._qr_poll_id = GLib.timeout_add_seconds(10, self._poll_qr_status)
        return False

    def _on_ws_qr_status(self, data: dict) -> bool:
        """Handle WS qr_status push — instant UI update."""
        self._update_qr_status(data)
        return False

    def _poll_qr_status(self) -> bool:
        """QR-Login Status pollen."""
        def worker():
            try:
                if self.api_client:
                    result = self.api_client.telegram_qr_status()
                    GLib.idle_add(self._update_qr_status, result)
                elif hasattr(self, "_local_qr_handler"):
                    s = self._local_qr_handler.get_state()
                    GLib.idle_add(self._update_qr_status, {
                        "status": s.status,
                        "qr_url": s.qr_url,
                        "error": s.error,
                        "user_name": s.user_name,
                        "user_id": s.user_id,
                        "phone": s.phone,
                    })
            except Exception as e:
                logger.warning(f"QR-Status Abfrage fehlgeschlagen: {e}")
        threading.Thread(target=worker, daemon=True).start()
        return True  # weiter pollen

    def _update_qr_status(self, data: dict) -> bool:
        """QR-Status UI aktualisieren."""
        status = data.get("status", "idle")
        qr_url = data.get("qr_url", "")

        if status == "waiting" and qr_url:
            self._qr_widget.set_url(qr_url)
            self._qr_status_row.set_subtitle(_("Warte auf Scan..."))

        elif status == "authorized":
            user = data.get("user_name", "")
            user_id = data.get("user_id", 0)
            phone = data.get("phone", "")
            info = f"{_('Eingeloggt')}: {user}"
            if phone:
                info += f" (+{phone})"
            self._qr_status_row.set_subtitle(info)
            self._qr_widget.clear()
            self._qr_hint.set_visible(False)
            self._stop_qr_polling()
            self._qr_spinner.stop()
            self._qr_spinner.set_visible(False)
            self._qr_start_btn.set_sensitive(True)
            self._qr_start_btn.set_label(_("Erneut anmelden"))
            self._qr_cancel_btn.set_sensitive(False)

        elif status in ("error", "cancelled"):
            error = data.get("error", status)
            self._on_qr_error(error)

        return False

    def _on_qr_cancel(self, btn: Gtk.Button) -> None:
        """QR-Login abbrechen."""
        def worker():
            try:
                if self.api_client:
                    self.api_client.telegram_qr_cancel()
                elif hasattr(self, "_local_qr_handler"):
                    self._local_qr_handler.cancel()
            except Exception as e:
                logger.warning(f"QR-Login Abbruch fehlgeschlagen: {e}")
            GLib.idle_add(self._on_qr_cancelled)
        threading.Thread(target=worker, daemon=True).start()

    def _on_qr_cancelled(self) -> bool:
        self._stop_qr_polling()
        self._qr_status_row.set_subtitle(_("Abgebrochen"))
        self._qr_widget.clear()
        self._qr_hint.set_visible(False)
        self._qr_spinner.stop()
        self._qr_spinner.set_visible(False)
        self._qr_start_btn.set_sensitive(True)
        self._qr_start_btn.set_label(_("Mit QR-Code anmelden"))
        self._qr_cancel_btn.set_sensitive(False)
        return False

    def _on_qr_error(self, error: str) -> bool:
        self._stop_qr_polling()
        self._qr_status_row.set_subtitle(f"{_('Fehler')}: {error}")
        self._qr_widget.clear()
        self._qr_hint.set_visible(False)
        self._qr_spinner.stop()
        self._qr_spinner.set_visible(False)
        self._qr_start_btn.set_sensitive(True)
        self._qr_start_btn.set_label(_("Mit QR-Code anmelden"))
        self._qr_cancel_btn.set_sensitive(False)
        return False

    def _stop_qr_polling(self) -> None:
        """QR-Polling und WS-Abo stoppen."""
        if self._qr_poll_id:
            GLib.source_remove(self._qr_poll_id)
            self._qr_poll_id = None
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("qr_status", self._on_ws_qr_status)
        except Exception:
            pass

