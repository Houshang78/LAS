"""UI-Seite telegram: part3."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("telegram.part3")


class Part3Mixin:
    """Part3 Mixin."""

    def _start_qr_local(self, api_id: int, api_hash: str) -> None:
        """Standalone: QR-Login lokal starten — nur via API verfügbar."""
        logger.warning("QR-Login nur via API verfügbar (core-Import entfernt)")
        GLib.idle_add(self._on_qr_error, _("QR-Login nur im Server-Modus verfügbar"))

    # ══════════════════════════════════════
    # Config speichern
    # ══════════════════════════════════════

    def _on_save_config(self, btn: Gtk.Button) -> None:
        """Konfiguration speichern."""
        def worker():
            try:
                token = self._token_row.get_text().strip()
                chat_id_text = self._chat_id_row.get_text().strip()
                chat_id = int(chat_id_text) if chat_id_text else 0
                allowed_text = self._allowed_row.get_text().strip()
                allowed_ids = []
                if allowed_text:
                    for x in allowed_text.split(","):
                        x = x.strip()
                        if x:
                            try:
                                allowed_ids.append(int(x))
                            except ValueError:
                                pass
                send_notif = self._notify_row.get_active()

                if self.api_client:
                    self.api_client.telegram_update_config(
                        bot_token=token,
                        notification_chat_id=chat_id,
                        allowed_user_ids=allowed_ids,
                        send_notifications=send_notif,
                    )
                    msg = _("Konfiguration gespeichert (Server)")
                else:
                    tg_cfg = self.config_manager.config.telegram
                    tg_cfg.bot_token = token
                    tg_cfg.notification_chat_id = chat_id
                    tg_cfg.allowed_user_ids = allowed_ids
                    tg_cfg.send_notifications = send_notif
                    self.config_manager.save()
                    msg = _("Konfiguration gespeichert (lokal)")
                GLib.idle_add(self._show_feedback, msg, False)
            except Exception as e:
                GLib.idle_add(self._show_feedback, f"{_('Fehler')}: {e}", True)

        threading.Thread(target=worker, daemon=True).start()

    def _show_feedback(self, text: str, is_error: bool) -> bool:
        """Feedback-Label mit passender CSS-Klasse setzen."""
        if is_error:
            self._feedback_label.remove_css_class("success")
            self._feedback_label.add_css_class("error")
        else:
            self._feedback_label.remove_css_class("error")
            self._feedback_label.add_css_class("success")
        self._feedback_label.set_label(text)
        return False

    def _save_config_local(self) -> None:
        """Config lokal speichern (Standalone-Modus)."""
        tg_cfg = self.config_manager.config.telegram
        tg_cfg.bot_token = self._token_row.get_text().strip()
        chat_id_text = self._chat_id_row.get_text().strip()
        tg_cfg.notification_chat_id = int(chat_id_text) if chat_id_text else 0
        allowed_text = self._allowed_row.get_text().strip()
        if allowed_text:
            ids = []
            for x in allowed_text.split(","):
                x = x.strip()
                if x:
                    try:
                        ids.append(int(x))
                    except ValueError:
                        pass
            tg_cfg.allowed_user_ids = ids
        else:
            tg_cfg.allowed_user_ids = []
        tg_cfg.send_notifications = self._notify_row.get_active()
        tg_cfg.enabled = True
        self.config_manager.save()

    # ══════════════════════════════════════
    # Status laden
    # ══════════════════════════════════════

    def _load_status(self) -> bool:
        """Bot-Status laden."""
        def worker():
            try:
                if self.api_client:
                    data = self.api_client.telegram_status()
                else:
                    tg_cfg = self.config_manager.config.telegram
                    data = {
                        "enabled": tg_cfg.enabled,
                        "running": False,
                        "token_configured": bool(tg_cfg.bot_token),
                    }
                GLib.idle_add(self._update_status_ui, data)
            except Exception as e:
                GLib.idle_add(
                    self._status_row.set_subtitle, f"{_('Fehler')}: {e}",
                )
        threading.Thread(target=worker, daemon=True).start()
        return False

    def _update_status_ui(self, data: dict) -> bool:
        """Status-UI aktualisieren + Buttons togglen + erweiterte Stats."""
        running = data.get("running", False)
        enabled = data.get("enabled", False)
        token_ok = data.get("token_configured", False)
        self._bot_running = running

        if running:
            self._status_row.set_subtitle(_("Verbunden — Bot läuft"))
            icon_name = "emblem-ok-symbolic"
            self._connect_btn.set_sensitive(False)
            self._connect_btn.set_label(_("Verbunden"))
            self._disconnect_btn.set_sensitive(True)
        elif enabled and token_ok:
            self._status_row.set_subtitle(_("Konfiguriert, nicht verbunden"))
            icon_name = "dialog-warning-symbolic"
            self._connect_btn.set_sensitive(True)
            self._connect_btn.set_label(_("Verbinden"))
            self._disconnect_btn.set_sensitive(False)
        elif token_ok:
            self._status_row.set_subtitle(_("Token vorhanden, Bot deaktiviert"))
            icon_name = "dialog-warning-symbolic"
            self._connect_btn.set_sensitive(True)
            self._connect_btn.set_label(_("Verbinden"))
            self._disconnect_btn.set_sensitive(False)
        else:
            self._status_row.set_subtitle(_("Nicht konfiguriert — Token eingeben"))
            icon_name = "dialog-error-symbolic"
            self._connect_btn.set_sensitive(True)
            self._connect_btn.set_label(_("Verbinden"))
            self._disconnect_btn.set_sensitive(False)

        # Icon aktualisieren
        self._status_row.remove(self._status_icon)
        self._status_icon = Gtk.Image.new_from_icon_name(icon_name)
        self._status_row.add_prefix(self._status_icon)

        # Erweiterte Bot-Statistik
        uptime = data.get("uptime", "")
        if uptime:
            self._bot_uptime_row.set_subtitle(uptime)
        elif running:
            self._bot_uptime_row.set_subtitle(_("Aktiv"))
        else:
            self._bot_uptime_row.set_subtitle(_("Gestoppt"))

        msg_count = data.get("message_count", data.get("commands_today", 0))
        self._bot_commands_row.set_subtitle(str(msg_count) if msg_count else "—")

        last_msg = data.get("last_message", "")
        if last_msg:
            self._bot_last_msg_row.set_subtitle(str(last_msg)[:80])

        return False

    # ══════════════════════════════════════
    # Chat-Verlauf
    # ══════════════════════════════════════

    def _load_messages(self) -> bool:
        """Chat-Nachrichten laden."""
        def worker():
            try:
                if self.api_client:
                    messages = self.api_client.telegram_messages(50)
                else:
                    messages = []
                GLib.idle_add(self._update_chat_ui, messages)
            except Exception as e:
                logger.warning(f"Telegram-Nachrichten laden fehlgeschlagen: {e}")
        threading.Thread(target=worker, daemon=True).start()
        return False

    def _update_chat_ui(self, messages: list[dict]) -> bool:
        """Chat-Nachrichten im UI anzeigen (inkrementell)."""
        if not messages:
            # Nur leeren State zeigen wenn noetig
            if not self._chat_box.get_first_child():
                empty = Gtk.Label(label=_("Keine Nachrichten"))
                empty.add_css_class("dim-label")
                self._chat_box.append(empty)
            return False

        # Prüfen ob sich Nachrichten geändert haben
        new_ids = [m.get("id") or m.get("date", "") for m in messages]
        if self._last_msg_ids == new_ids:
            return False  # Nichts geändert — kein Rebuild
        self._last_msg_ids = new_ids

        # Vollständiger Rebuild nur bei tatsaechlicher Änderung
        while self._chat_box.get_first_child():
            self._chat_box.remove(self._chat_box.get_first_child())

        for msg in messages:
            direction = msg.get("direction", "in")
            user = msg.get("user", "?")
            text = msg.get("text", "")
            ts = msg.get("timestamp", "")[:16]

            msg_box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=2,
            )

            if direction == "in":
                msg_box.set_halign(Gtk.Align.START)
            else:
                msg_box.set_halign(Gtk.Align.END)

            # Header
            header = Gtk.Label(
                label=f"{user} — {ts}",
                xalign=0 if direction == "in" else 1,
            )
            header.add_css_class("dim-label")
            header.add_css_class("caption")
            msg_box.append(header)

            # Body
            body = Gtk.Label(label=text, xalign=0, wrap=True)
            body.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            body.set_max_width_chars(60)

            frame = Gtk.Frame()
            frame.add_css_class("card")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            inner.set_margin_top(8)
            inner.set_margin_bottom(8)
            inner.set_margin_start(12)
            inner.set_margin_end(12)
            inner.append(body)
            frame.set_child(inner)
            msg_box.append(frame)

            self._chat_box.append(msg_box)

        # Hoehe explizit: ~60px pro Nachricht, max 600px
        row_h = 60
        h = min(len(messages) * row_h, 600)
        self._chat_scroll.set_min_content_height(max(h, 80))
        self._chat_scroll.set_max_content_height(600)

        # Nach dem Befuellen zum Ende scrollen
        adj = self._chat_scroll.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()))

        return False

    def _poll_messages(self) -> bool:
        """Nachrichten alle 10s aktualisieren."""
        self._load_messages()
        return True

    def _on_send(self, widget) -> None:
        """Nachricht senden."""
        text = self._send_entry.get_text().strip()
        if not text:
            return
        self._send_entry.set_text("")

        def worker():
            try:
                if self.api_client:
                    self.api_client.telegram_send(text)
                    GLib.idle_add(self._load_messages)
            except Exception as e:
                logger.warning(f"Telegram-Senden fehlgeschlagen: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _on_refresh(self, button: Gtk.Button) -> None:
        """Manuelles Aktualisieren."""
        self._load_status()
        self._load_messages()
        self._load_bot_qr()

    def _on_ws_telegram_event(self, data: dict) -> bool:
        """Handle WS notification/telegram_status — trigger instant refresh."""
        self._load_status()
        self._load_messages()
        return False

    def cleanup(self) -> None:
        """Alle Timer und WS-Listener entfernen — wird beim Seitenwechsel/Beenden aufgerufen."""
        super().cleanup()
        if self._poll_id:
            GLib.source_remove(self._poll_id)
            self._poll_id = None
        if self._qr_poll_id:
            GLib.source_remove(self._qr_poll_id)
            self._qr_poll_id = None
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("telegram_message", self._on_ws_telegram_event)
            ui_ws_manager.off("telegram_status", self._on_ws_telegram_event)
        except Exception:
            pass
