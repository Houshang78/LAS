"""UI-Seite telegram: part1."""

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
from lotto_analyzer.ui.pages.telegram.page import QRCodeWidget
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from lotto_common.config import ConfigManager
from lotto_common.models.draw import DrawDay
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_common.models.game_config import GameType, get_config


logger = get_logger("telegram.part1")

from lotto_analyzer.ui.widgets.help_button import HelpButton


class Part1Mixin:
    """Part1 Mixin."""


# ── Telegram-Seite ──


from lotto_analyzer.ui.pages.telegram.part2 import Part2Mixin
from lotto_analyzer.ui.pages.telegram.part3 import Part3Mixin


class TelegramPage(Part2Mixin, Part3Mixin, BasePage):
    """Telegram-Bot Verwaltung: Login/Logout, QR-Login, Config, Chat-Verlauf."""

    def __init__(
        self,
        config_manager: ConfigManager,
        db: Database | None,
        app_mode: str,
        api_client=None,
        app_db=None,
        backtest_db=None,
    ):
        super().__init__(config_manager, db, app_mode, api_client, app_db=app_db, backtest_db=backtest_db)
        self._poll_id: int | None = None
        self._qr_poll_id: int | None = None
        self._bot_running = False
        self._last_msg_ids: list = []
        self._ai_analyst = None
        self._init_ai()
        self._build_ui()

    def _init_ai(self) -> None:
        # Standalone-AI entfernt: AI läuft immer auf dem Server
        pass

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

        # Titel
        title = Gtk.Label(label=_("Telegram-Bot"))
        title.add_css_class("title-1")
        content.append(title)

        # ══════════════════════════════════════
        # Status + Connect/Disconnect (Bot API)
        # ══════════════════════════════════════
        status_group = Adw.PreferencesGroup(
            title=_("Bot-Verbindung"),
            description=_("Telegram-Bot (Bot API) starten und stoppen"),
        )
        status_group.set_header_suffix(
            HelpButton(_("Startet den Telegram-Bot. Danach kannst du per Telegram-App Befehle senden (/tipps, /stats, /draw)."))
        )
        content.append(status_group)

        # Status-Zeile
        self._status_row = Adw.ActionRow(
            title=_("Bot-Status"), subtitle=_("Wird geprüft..."),
        )
        self._status_icon = Gtk.Image.new_from_icon_name("dialog-question-symbolic")
        self._status_row.add_prefix(self._status_icon)
        status_group.add(self._status_row)

        # Connect / Disconnect Buttons
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
            halign=Gtk.Align.CENTER,
        )
        btn_box.set_margin_top(8)

        self._connect_btn = Gtk.Button(label=_("Verbinden"))
        self._connect_btn.add_css_class("suggested-action")
        self._connect_btn.add_css_class("pill")
        self._connect_btn.connect("clicked", self._on_connect)
        btn_box.append(self._connect_btn)

        self._disconnect_btn = Gtk.Button(label=_("Trennen"))
        self._disconnect_btn.add_css_class("destructive-action")
        self._disconnect_btn.add_css_class("pill")
        self._disconnect_btn.connect("clicked", self._on_disconnect)
        self._disconnect_btn.set_sensitive(False)
        btn_box.append(self._disconnect_btn)

        self._conn_spinner = Gtk.Spinner()
        self._conn_spinner.set_visible(False)
        btn_box.append(self._conn_spinner)

        status_group.add(btn_box)

        # Bot-QR-Code (Link zum Bot)
        self._bot_qr_row = Adw.ActionRow(
            title=_("Bot-Link QR"),
            subtitle=_("QR-Code scannen um Chat mit Bot zu oeffnen"),
        )
        self._bot_qr_widget = QRCodeWidget(size=150)
        self._bot_qr_widget.set_valign(Gtk.Align.CENTER)
        self._bot_qr_row.add_suffix(self._bot_qr_widget)
        self._bot_qr_row.set_activatable(False)
        status_group.add(self._bot_qr_row)

        # Feedback-Label
        self._feedback_label = Gtk.Label(label="")
        self._feedback_label.add_css_class("dim-label")
        self._feedback_label.set_wrap(True)
        status_group.add(self._feedback_label)

        # ── Erweiterte Bot-Statistik ──
        bot_stats_group = Adw.PreferencesGroup(
            title=_("Bot-Statistik"),
            description=_("Aktivität und Uptime"),
        )
        content.append(bot_stats_group)

        self._bot_uptime_row = Adw.ActionRow(
            title=_("Bot-Uptime"),
            subtitle="—",
        )
        self._bot_uptime_row.add_prefix(
            Gtk.Image.new_from_icon_name("preferences-system-time-symbolic")
        )
        bot_stats_group.add(self._bot_uptime_row)

        self._bot_commands_row = Adw.ActionRow(
            title=_("Verarbeitete Befehle"),
            subtitle="—",
        )
        self._bot_commands_row.add_prefix(
            Gtk.Image.new_from_icon_name("utilities-terminal-symbolic")
        )
        bot_stats_group.add(self._bot_commands_row)

        self._bot_last_msg_row = Adw.ActionRow(
            title=_("Letzte Nachricht"),
            subtitle="—",
        )
        self._bot_last_msg_row.add_prefix(
            Gtk.Image.new_from_icon_name("mail-unread-symbolic")
        )
        bot_stats_group.add(self._bot_last_msg_row)

        # ══════════════════════════════════════
        # QR-Code-Login (Telethon MTProto)
        # ══════════════════════════════════════
        qr_group = Adw.PreferencesGroup(
            title=_("QR-Code-Login (Telethon)"),
            description=_("Mit Telegram-Account anmelden — QR-Code mit Handy scannen"),
        )
        qr_group.set_header_suffix(
            HelpButton(_("Für erweiterte Funktionen: Scanne den QR-Code mit der Telegram-App auf deinem Handy."))
        )
        content.append(qr_group)

        # API-ID Eingabe
        self._api_id_row = Adw.EntryRow(title=_("API-ID (von my.telegram.org)"))
        tg_cfg = self.config_manager.config.telegram
        if tg_cfg.api_id:
            self._api_id_row.set_text(str(tg_cfg.api_id))
        qr_group.add(self._api_id_row)

        # API-Hash Eingabe
        self._api_hash_row = Adw.EntryRow(title=_("API-Hash"))
        if tg_cfg.api_hash:
            self._api_hash_row.set_text(tg_cfg.api_hash)
        self._api_hash_row.add_css_class("monospace")
        qr_group.add(self._api_hash_row)

        # QR-Login Status
        self._qr_status_row = Adw.ActionRow(
            title=_("QR-Login"),
            subtitle=_("Nicht gestartet"),
        )
        qr_group.add(self._qr_status_row)

        # QR-Code Widget (gross, zentriert)
        qr_center = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            halign=Gtk.Align.CENTER,
        )
        qr_center.set_margin_top(12)
        qr_center.set_margin_bottom(12)

        self._qr_widget = QRCodeWidget(size=280)
        qr_center.append(self._qr_widget)

        self._qr_hint = Gtk.Label(
            label=_("Oeffne Telegram auf deinem Handy → Einstellungen → "
                     "Geraete → QR-Code scannen"),
        )
        self._qr_hint.add_css_class("dim-label")
        self._qr_hint.add_css_class("caption")
        self._qr_hint.set_wrap(True)
        self._qr_hint.set_max_width_chars(50)
        self._qr_hint.set_justify(Gtk.Justification.CENTER)
        self._qr_hint.set_margin_top(8)
        self._qr_hint.set_visible(False)
        qr_center.append(self._qr_hint)

        qr_group.add(qr_center)

        # QR-Login Buttons
        qr_btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
            halign=Gtk.Align.CENTER,
        )
        qr_btn_box.set_margin_top(4)

        self._qr_start_btn = Gtk.Button(label=_("Mit QR-Code anmelden"))
        self._qr_start_btn.add_css_class("suggested-action")
        self._qr_start_btn.add_css_class("pill")
        self._qr_start_btn.connect("clicked", self._on_qr_start)
        qr_btn_box.append(self._qr_start_btn)

        self._qr_cancel_btn = Gtk.Button(label=_("Abbrechen"))
        self._qr_cancel_btn.set_tooltip_text(_("QR-Code Login abbrechen"))
        self._qr_cancel_btn.add_css_class("pill")
        self._qr_cancel_btn.connect("clicked", self._on_qr_cancel)
        self._qr_cancel_btn.set_sensitive(False)
        qr_btn_box.append(self._qr_cancel_btn)

        self._qr_spinner = Gtk.Spinner()
        self._qr_spinner.set_visible(False)
        qr_btn_box.append(self._qr_spinner)

        qr_group.add(qr_btn_box)

        # ══════════════════════════════════════
        # Konfiguration (editierbar)
        # ══════════════════════════════════════
        config_group = Adw.PreferencesGroup(
            title=_("Bot-Konfiguration"),
            description=_("Bot-Token und Benachrichtigungen"),
        )
        content.append(config_group)

        # Bot-Token Eingabe
        self._token_row = Adw.EntryRow(title=_("Bot-Token"))
        if tg_cfg.bot_token:
            self._token_row.set_text(tg_cfg.bot_token)
        self._token_row.add_css_class("monospace")
        self._token_row.add_suffix(
            HelpButton(_("Den Token bekommst du von @BotFather in Telegram. Format: 123456:ABC-DEF."))
        )
        config_group.add(self._token_row)

        # Notification Chat-ID
        self._chat_id_row = Adw.EntryRow(title=_("Notification Chat-ID"))
        if tg_cfg.notification_chat_id:
            self._chat_id_row.set_text(str(tg_cfg.notification_chat_id))
        config_group.add(self._chat_id_row)

        # Allowed User IDs
        self._allowed_row = Adw.EntryRow(title=_("Erlaubte User-IDs (kommagetrennt)"))
        if tg_cfg.allowed_user_ids:
            self._allowed_row.set_text(
                ", ".join(str(uid) for uid in tg_cfg.allowed_user_ids)
            )
        config_group.add(self._allowed_row)

        # Benachrichtigungen Toggle
        self._notify_row = Adw.SwitchRow(
            title=_("Benachrichtigungen senden"),
            subtitle=_("Nach Crawl/Generate/Report"),
        )
        self._notify_row.set_active(tg_cfg.send_notifications)
        config_group.add(self._notify_row)

        # Speichern-Button
        save_box = Gtk.Box(halign=Gtk.Align.CENTER)
        save_box.set_margin_top(8)
        save_btn = Gtk.Button(label=_("Konfiguration speichern"))
        save_btn.set_tooltip_text(_("Telegram Bot-Konfiguration speichern"))
        save_btn.add_css_class("pill")
        save_btn.connect("clicked", self._on_save_config)
        save_box.append(save_btn)
        config_group.add(save_box)

        # ══════════════════════════════════════
        # Chat-Verlauf
        # ══════════════════════════════════════
        chat_group = Adw.PreferencesGroup(
            title=_("Chat-Verlauf"),
            description=_("Letzte Telegram-Nachrichten"),
        )
        chat_group.set_header_suffix(
            HelpButton(_("Zeigt die letzten Nachrichten zwischen Telegram-Nutzern und dem Bot (Befehle und Antworten)."))
        )
        content.append(chat_group)

        # Erklärungstext + Chat in einem Frame
        chat_info = Gtk.Label(
            label=_("Eingehend = Befehle der Nutzer, Ausgehend = Antworten des Bots. "
                     "Verfügbare Befehle: /tipps, /stats, /draw, /hilfe."),
        )
        chat_info.set_wrap(True)
        chat_info.set_xalign(0)
        chat_info.add_css_class("dim-label")
        chat_info.set_margin_start(12)
        chat_info.set_margin_end(12)
        chat_info.set_margin_top(8)
        chat_info.set_margin_bottom(4)

        chat_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        chat_outer.append(chat_info)

        self._chat_scroll = Gtk.ScrolledWindow()
        self._chat_scroll.set_min_content_height(80)
        self._chat_scroll.set_max_content_height(600)

        self._chat_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8,
        )
        self._chat_box.set_margin_top(8)
        self._chat_box.set_margin_bottom(8)
        self._chat_box.set_margin_start(8)
        self._chat_box.set_margin_end(8)
        self._chat_scroll.set_child(self._chat_box)

        chat_outer.append(self._chat_scroll)

        chat_frame = Gtk.Frame()
        chat_frame.set_child(chat_outer)
        content.append(chat_frame)

        # ── Sende-Leiste ──
        send_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
        )
        send_box.set_margin_top(8)

        self._send_entry = Gtk.Entry()
        self._send_entry.set_placeholder_text(_("Nachricht senden..."))
        self._send_entry.set_hexpand(True)
        self._send_entry.connect("activate", self._on_send)
        send_box.append(self._send_entry)

        send_btn = Gtk.Button(icon_name="mail-send-symbolic")
        send_btn.set_tooltip_text(_("Nachricht senden"))
        send_btn.add_css_class("suggested-action")
        send_btn.connect("clicked", self._on_send)
        send_box.append(send_btn)

        content.append(send_box)

        # ── Refresh Button ──
        btn_box2 = Gtk.Box(halign=Gtk.Align.CENTER)
        btn_box2.set_margin_top(12)
        refresh_btn = Gtk.Button(label=_("Aktualisieren"))
        refresh_btn.set_tooltip_text(_("Telegram-Status aktualisieren"))
        refresh_btn.add_css_class("pill")
        refresh_btn.connect("clicked", self._on_refresh)
        btn_box2.append(refresh_btn)
        content.append(btn_box2)

        # AI-Panel
        self._ai_panel = AIPanel(
            ai_analyst=self._ai_analyst, api_client=self.api_client,
            title="AI-Analyse", config_manager=self.config_manager,
            db=self.db, page="telegram", app_db=self.app_db,
        )
        content.append(self._ai_panel)

        # Initial laden
        GLib.idle_add(self._load_status)
        GLib.idle_add(self._load_messages)
        GLib.idle_add(self._load_bot_qr)

        # Slow fallback polling (WS pushes instant)
        self._poll_id = GLib.timeout_add_seconds(60, self._poll_messages)

        # WS-Listener fuer instant Updates
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.on("telegram_message", self._on_ws_telegram_event)
            ui_ws_manager.on("telegram_status", self._on_ws_telegram_event)
        except Exception:
            pass

    # ══════════════════════════════════════
    # API-Client
    # ══════════════════════════════════════

    def set_api_client(self, client: "APIClient | None") -> None:
        """API-Client setzen."""
        super().set_api_client(client)
        self._ai_panel.api_client = client

    def refresh(self) -> None:
        """Telegram-Daten nur neu laden wenn veraltet (>5min)."""
        if not self.is_stale():
            return
        self._load_status()
        self._load_messages()
        self._load_bot_qr()

    # ══════════════════════════════════════
    # Bot Connect / Disconnect
    # ══════════════════════════════════════

    def _on_connect(self, btn: Gtk.Button) -> None:
        """Telegram-Bot starten."""
        self._connect_btn.set_sensitive(False)
        self._conn_spinner.set_visible(True)
        self._conn_spinner.start()
        self._feedback_label.set_label(_("Verbinde..."))

        def worker():
            try:
                if self.api_client:
                    result = self.api_client.telegram_connect()
                    msg = _("Verbunden") if result.get("running") else _("Fehler")
                else:
                    self._save_config_local()
                    msg = _("Config gespeichert (Neustart noetig für Bot-Start)")
                GLib.idle_add(self._on_connect_done, msg, None)
            except Exception as e:
                GLib.idle_add(self._on_connect_done, "", str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_connect_done(self, msg: str, error: str | None) -> bool:
        self._connect_btn.set_sensitive(True)
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
        self._load_bot_qr()
        return False

    def _on_disconnect(self, btn: Gtk.Button) -> None:
        """Telegram-Bot stoppen."""
        self._disconnect_btn.set_sensitive(False)
        self._conn_spinner.set_visible(True)
        self._conn_spinner.start()
        self._feedback_label.set_label(_("Trenne..."))

        def worker():
            try:
                if self.api_client:
                    result = self.api_client.telegram_disconnect()
                    msg = _("Getrennt")
                else:
                    tg_cfg = self.config_manager.config.telegram
                    tg_cfg.enabled = False
                    self.config_manager.save()
                    msg = _("Deaktiviert")
                GLib.idle_add(self._on_disconnect_done, msg, None)
            except Exception as e:
                GLib.idle_add(self._on_disconnect_done, "", str(e))

        threading.Thread(target=worker, daemon=True).start()

