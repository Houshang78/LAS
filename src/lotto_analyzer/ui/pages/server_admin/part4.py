"""UI-Seite server_admin: part4 Mixin."""

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


logger = get_logger("server_admin.part4")
import shutil
import subprocess


class Part4Mixin:
    """Part4 Mixin."""

    # ── Service-Steuerung ──

    def _on_service_action(self, button: Gtk.Button, action: str) -> None:
        for btn in self._service_buttons.values():
            btn.set_sensitive(False)
        self._service_status.set_subtitle(f"{action.title()}...")

        def worker():
            try:
                ok, message = service_action(action)
                GLib.idle_add(self._on_action_done, ok, message)
            except Exception as e:
                GLib.idle_add(self._on_action_done, False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_action_done(self, ok: bool, message: str) -> bool:
        for btn in self._service_buttons.values():
            btn.set_sensitive(True)

        prefix = "OK" if ok else "Fehler"
        self._service_status.set_subtitle(f"{prefix}: {message}")

        GLib.timeout_add(self._FEEDBACK_DELAY_MS, lambda: (self._load_status(), False)[-1])
        return False

    def _on_autostart_toggled(self, switch: Adw.SwitchRow, _pspec) -> None:
        action = "enable" if switch.get_active() else "disable"

        def worker():
            try:
                result = subprocess.run(
                    ["sudo", "systemctl", action, "lotto-analyzer-server"],
                    capture_output=True, text=True, timeout=15,
                )
                ok = result.returncode == 0
                msg = (
                    _("Autostart aktiviert") if action == "enable" else _("Autostart deaktiviert")
                    if ok else result.stderr.strip()
                )
            except Exception as e:
                ok = False
                msg = str(e)
            GLib.idle_add(self._on_autostart_result, ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_autostart_result(self, ok: bool, message: str) -> bool:
        prefix = "OK" if ok else "Fehler"
        self._autostart.set_subtitle(f"{prefix}: {message}")
        return False

    def _on_backup(self, button: Gtk.Button) -> None:
        if not self.db:
            return

        self._backup_btn.set_sensitive(False)

        def worker():
            try:
                src = self.db.db_path
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dst = src.parent / f"lotto_backup_{timestamp}.db"
                shutil.copy2(str(src), str(dst))
                GLib.idle_add(self._on_backup_done, str(dst), None)
            except Exception as e:
                GLib.idle_add(self._on_backup_done, "", str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_backup_done(self, path: str, error: str | None) -> bool:
        self._backup_btn.set_sensitive(True)
        if error:
            self._backup_btn.set_label(f"Fehler: {error}")
        else:
            self._backup_btn.set_label(f"Gespeichert: {path}")
        # Label nach 5 Sekunden zurücksetzen
        GLib.timeout_add(self._BACKUP_LABEL_RESTORE_MS, self._restore_backup_label)
        return False

    def _restore_backup_label(self) -> bool:
        self._backup_btn.set_label(_("Backup erstellen"))
        return False

    # ── Per-User Telegram-Bots ──

    def _update_telegram_bots_ui(self, bots: list[dict]) -> bool:
        """Telegram-Bot-Liste aktualisieren."""
        while True:
            row = self._tg_bot_list.get_row_at_index(0)
            if row is None:
                break
            self._tg_bot_list.remove(row)

        for bot in bots:
            uid = bot.get("user_id", 0)
            username = bot.get("username", "?")
            active = bot.get("is_active", False)
            running = bot.get("running", False)
            status = _("Läuft") if running else (_("Aktiv") if active else _("Inaktiv"))
            row = Adw.ExpanderRow(
                title=f"{username} (User-ID: {uid})",
                subtitle=f"Status: {status} | Chat-ID: {bot.get('chat_id') or '—'}",
            )

            # Toggle
            toggle_row = Adw.SwitchRow(title=_("Bot aktiv"), active=active)
            toggle_row.connect(
                "notify::active", self._on_tg_bot_toggle, uid,
            )
            row.add_row(toggle_row)

            # Log anzeigen
            log_row = Adw.ActionRow(title=_("Nachrichten-Log"))
            log_btn = Gtk.Button(label=_("Log anzeigen"))
            log_btn.set_valign(Gtk.Align.CENTER)
            log_btn.set_tooltip_text(_("Telegram-Nachrichten-Log anzeigen"))
            log_btn.connect("clicked", self._on_show_tg_log, uid, username)
            log_row.add_suffix(log_btn)
            row.add_row(log_row)

            # Entfernen
            rm_row = Adw.ActionRow(title="")
            rm_btn = Gtk.Button(label=_("Bot entfernen"))
            rm_btn.add_css_class("destructive-action")
            rm_btn.set_valign(Gtk.Align.CENTER)
            rm_btn.set_tooltip_text(_("Telegram-Bot von diesem Benutzer entfernen"))
            rm_btn.connect("clicked", self._on_remove_tg_bot, uid)
            rm_row.add_suffix(rm_btn)
            row.add_row(rm_row)

            self._tg_bot_list.append(row)

        if not bots:
            self._tg_bot_list.append(
                Adw.ActionRow(title=_("Keine User-Bots konfiguriert")),
            )
        return False

    def _on_add_telegram_bot(self, button: Gtk.Button) -> None:
        """Dialog zum Zuweisen eines Telegram-Bots an einen User."""
        dialog = Adw.Dialog()
        dialog.set_title(_("Telegram-Bot zuweisen"))
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

        user_combo = Adw.ComboRow(title=_("Benutzer"))
        user_list = Gtk.StringList()
        users_data = []

        def load_users():
            try:
                if self.api_client and not self.db:
                    users_data.extend(self.api_client.list_users())
                else:
                    from lotto_analyzer.server.user_db import UserDatabase
                    udb = UserDatabase(self.config_manager.data_dir / "users.db")
                    users_data.extend(udb.list_users())
            except Exception as e:
                logger.warning(f"Benutzerliste laden fehlgeschlagen: {e}")
            GLib.idle_add(_populate)

        def _populate():
            for u in users_data:
                user_list.append(f"{u['username']} (ID: {u['id']})")
            user_combo.set_model(user_list)

        threading.Thread(target=load_users, daemon=True).start()
        group.add(user_combo)

        token_entry = Adw.PasswordEntryRow(title=_("Bot-Token (von @BotFather)"))
        group.add(token_entry)

        chat_entry = Adw.EntryRow(title=_("Chat-ID (optional)"))
        group.add(chat_entry)

        status_label = Gtk.Label()
        box.append(status_label)

        save_btn = Gtk.Button(label=_("Zuweisen"))
        save_btn.add_css_class("suggested-action")
        save_btn.set_tooltip_text(_("Bot dem Benutzer zuweisen"))

        def on_save(_btn):
            idx = user_combo.get_selected()
            if idx < 0 or idx >= len(users_data):
                status_label.set_text(_("Bitte Benutzer wählen"))
                return
            uid = users_data[idx]["id"]
            token = token_entry.get_text().strip()
            chat_id_str = chat_entry.get_text().strip()
            chat_id = int(chat_id_str) if chat_id_str.isdigit() else None

            if not token:
                status_label.set_text(_("Bot-Token erforderlich"))
                return

            def worker():
                try:
                    if self.api_client and not self.db:
                        self.api_client.admin_set_telegram_bot(uid, token, chat_id)
                    GLib.idle_add(status_label.set_text, "Bot zugewiesen")
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

    def _on_tg_bot_toggle(self, switch: Adw.SwitchRow, _pspec, user_id: int) -> None:
        """Telegram-Bot an/aus schalten."""
        active = switch.get_active()

        def worker():
            try:
                if self.api_client and not self.db:
                    self.api_client.admin_toggle_telegram_bot(user_id, active)
            except Exception as e:
                logger.warning(f"Telegram-Bot Toggle fehlgeschlagen: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_show_tg_log(self, button: Gtk.Button, user_id: int, username: str) -> None:
        """Log-Dialog für einen User-Bot anzeigen."""
        dialog = Adw.Dialog()
        dialog.set_title(f"Telegram-Log: {username}")
        dialog.set_content_width(self._TG_LOG_DIALOG_WIDTH)
        dialog.set_content_height(self._TG_LOG_DIALOG_HEIGHT)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        dialog.set_child(scrolled)

        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_monospace(True)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_view.set_margin_top(8)
        text_view.set_margin_bottom(8)
        text_view.set_margin_start(8)
        text_view.set_margin_end(8)
        scrolled.set_child(text_view)

        def load_log():
            try:
                if self.api_client and not self.db:
                    lines = self.api_client.admin_get_telegram_log(user_id, limit=self._TELEGRAM_LOG_LIMIT)
                    text = "\n".join(lines) if lines else _("(Kein Log vorhanden)")
                else:
                    text = _("(Nur im Client-Modus verfügbar)")
                GLib.idle_add(text_view.get_buffer().set_text, text, -1)
            except Exception as e:
                GLib.idle_add(text_view.get_buffer().set_text, f"Fehler: {e}", -1)

        threading.Thread(target=load_log, daemon=True).start()

        window = self.get_root()
        if window:
            dialog.present(window)

    def _on_remove_tg_bot(self, button: Gtk.Button, user_id: int) -> None:
        """User-Bot entfernen."""
        button.set_sensitive(False)

        def worker():
            try:
                if self.api_client and not self.db:
                    self.api_client.admin_delete_telegram_bot(user_id)
                GLib.idle_add(self._load_status)
            except Exception as e:
                GLib.idle_add(button.set_label, f"Fehler: {e}")
            GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()
