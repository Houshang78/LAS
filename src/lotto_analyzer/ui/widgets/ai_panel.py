"""AI-Panel Widget: AI-Chat mit DB-Kontext, Sessions, History.

Nutzt ChatBox für das UI und fuegt AI-Logik hinzu:
- DB-Kontext beim ersten Senden
- Session-Verwaltung (Neuer Chat, History, Löschen)
- API- oder lokaler AI-Analyst
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Pango, GLib
import logging
import threading

from lotto_common.models.draw import DrawDay
from lotto_analyzer.ui.widgets.chat_box import ChatBox

logger = logging.getLogger("ai_panel")


class AIPanel(Gtk.Box):
    """AI-Chat-Panel mit DB-Kontext und Session-Verwaltung."""

    def __init__(self, ai_analyst=None, api_client=None, title="AI-Analyse",
                 audio_service=None, config_manager=None, db=None, page="statistics",
                 app_db=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.ai_analyst = ai_analyst
        self.api_client = api_client
        self._config_manager = config_manager
        self._db = db
        self._app_db = app_db
        self._page = page
        self._session_id: int | None = None
        self._thinking_label: Gtk.Label | None = None
        self._context_sent = False
        self._external_context = ""
        self._cancel_event = threading.Event()
        self.set_size_request(300, -1)

        # Audio aus Config initialisieren
        if not audio_service and config_manager:
            try:
                config = config_manager.config
                if config.audio.tts_enabled:
                    from lotto_analyzer.ui.audio_service import AudioService
                    audio_service = AudioService(
                        tts_lang=config.audio.tts_language,
                        openai_api_key=config.audio.openai_api_key,
                    )
            except Exception as e:
                logger.debug(f"AudioService initialisieren fehlgeschlagen: {e}")

        # ── Header mit Session-Buttons ──
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.set_margin_top(8)
        header.set_margin_start(8)
        header.set_margin_end(8)
        header.append(Gtk.Image.new_from_icon_name("user-available-symbolic"))
        lbl = Gtk.Label(label=title)
        lbl.add_css_class("heading")
        lbl.set_hexpand(True)
        lbl.set_xalign(0)
        header.append(lbl)

        # Neuer Chat
        new_btn = Gtk.Button(icon_name="tab-new-symbolic", tooltip_text="Neuer Chat")
        new_btn.connect("clicked", self._on_new_chat)
        header.append(new_btn)

        # Verlauf
        history_btn = Gtk.MenuButton(
            icon_name="document-open-recent-symbolic", tooltip_text="Verlauf",
        )
        self._history_popover = Gtk.Popover()
        self._history_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._history_box.set_margin_top(8)
        self._history_box.set_margin_bottom(8)
        self._history_box.set_margin_start(8)
        self._history_box.set_margin_end(8)
        self._history_popover.set_child(self._history_box)
        history_btn.set_popover(self._history_popover)
        self._history_popover.connect("show", self._on_history_show)
        header.append(history_btn)

        # Löschen
        del_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Chat löschen")
        del_btn.add_css_class("destructive-action")
        del_btn.connect("clicked", self._on_delete_chat)
        header.append(del_btn)

        self.append(header)
        self.append(Gtk.Separator())

        # ── ChatBox Widget ──
        self._chat_box = ChatBox(
            placeholder="Klicke 'Analysieren' oder stelle eine Frage.",
            input_placeholder="Frage an AI...",
            audio_service=audio_service,
            config_manager=config_manager,
            min_height=80,
            max_height=600,
            show_header=False,  # Header wird oben separat gebaut
        )
        self._chat_box.connect("message-submitted", self._on_user_message)
        self.append(self._chat_box)

        # Letzten Chat automatisch laden
        self._restore_last_session()

    # ── Oeffentliche API ──

    def add_message(self, text: str, is_user: bool = False) -> None:
        """Nachricht zum Chat hinzufügen."""
        self._chat_box.add_message(text, is_user=is_user)

    def set_result(self, text: str) -> None:
        """Ergebnis direkt anzeigen (ohne User-Nachricht)."""
        self._chat_box.add_ai_message(text)
        self._chat_box.scroll_to_bottom()

    def analyze(self, prompt: str) -> None:
        """Automatischer Aufruf von aussen (z.B. Statistik-Analyse)."""
        if not self.ai_analyst and not self.api_client:
            return
        self._ensure_session()
        if self._session_id:
            self._save_message(self._session_id, "user", prompt)

        self._chat_box.add_user_message(prompt)
        self._thinking_label = self._chat_box.add_thinking()
        self._chat_box.set_busy(True)

        def run():
            try:
                result = self._chat(prompt)
                if not self._cancel_event.is_set():
                    GLib.idle_add(self._on_ai_response, result)
            except Exception as e:
                if not self._cancel_event.is_set():
                    GLib.idle_add(self._on_ai_response, f"Fehler: {e}")
        threading.Thread(target=run, daemon=True).start()

    # ── Interne Logik ──

    def _restore_last_session(self) -> None:
        """Letzten Chat dieser Seite automatisch laden (DB oder API)."""
        try:
            sessions = self._get_sessions()
            if sessions:
                last = sessions[0]
                self._session_id = last["id"]
                messages = self._get_messages(last["id"])
                if messages:
                    self._chat_box.clear()
                    for msg in messages:
                        if msg["role"] == "user":
                            self._chat_box.add_user_message(msg["content"])
                        else:
                            self._chat_box.add_ai_message(msg["content"])
                    self._chat_box.scroll_to_bottom()
                    self._context_sent = True
        except Exception as e:
            logger.debug(f"Session laden fehlgeschlagen: {e}")

    # ── Session-Helfer (DB oder API) ──

    def _get_sessions(self) -> list[dict]:
        if self._app_db:
            return self._app_db.get_chat_sessions(self._page)
        if self.api_client:
            return self.api_client.get_chat_sessions(self._page)
        return []

    def _get_messages(self, session_id: int) -> list[dict]:
        if self._app_db:
            return self._app_db.get_chat_messages(session_id)
        if self.api_client:
            return self.api_client.get_chat_messages(session_id)
        return []

    def _create_session(self) -> int | None:
        if self._app_db:
            return self._app_db.create_chat_session(self._page)
        if self.api_client:
            return self.api_client.create_chat_session(self._page)
        return None

    def _save_message(self, session_id: int, role: str, content: str) -> None:
        if self._app_db:
            self._app_db.add_chat_message(session_id, role, content)
        elif self.api_client:
            self.api_client.add_chat_message(session_id, role, content)

    def _delete_session(self, session_id: int) -> None:
        if self._app_db:
            self._app_db.delete_chat_session(session_id)
        elif self.api_client:
            self.api_client.delete_chat_session(session_id)

    def _ensure_session(self) -> None:
        if self._session_id is None:
            self._session_id = self._create_session()

    def _chat(self, message: str) -> str:
        """AI-Chat — lokal oder via Server."""
        enriched = self._enrich_with_context(message)
        if self.ai_analyst:
            return self.ai_analyst.chat(enriched)
        if self.api_client:
            return self.api_client.chat(enriched)
        raise RuntimeError("Kein AI-Backend verfügbar")

    def _enrich_with_context(self, message: str) -> str:
        """Beim ersten Senden DB-Kontext voranstellen."""
        if self._context_sent:
            return message
        self._context_sent = True

        # Externer Kontext hat Priorität (z.B. Backtest-Bericht)
        ext = getattr(self, "_external_context", "")
        if ext:
            return (
                f"[KONTEXT – Nutze diese Daten für alle Antworten]\n\n"
                f"{ext}\n\n"
                f"[BENUTZER-FRAGE]\n{message}"
            )

        ctx = self._build_full_context()
        if not ctx:
            return message
        return (
            f"[DATENBANK-KONTEXT – Nutze diese Daten für alle Antworten]\n\n"
            f"{ctx}\n\n"
            f"[BENUTZER-FRAGE]\n{message}"
        )

    def _build_full_context(self) -> str:
        """DB-Kontext für AI zusammenstellen."""
        if not self._db and self.api_client:
            try:
                stats = self.api_client.get_db_stats()
                return f"=== LOTTO SERVER-KONTEXT ===\nDB-Statistik: {stats}\n"
            except Exception as e:
                logger.warning(f"DB-Stats via API laden fehlgeschlagen: {e}")
                return ""
        if not self._db:
            return ""
        try:
            parts = []
            for day in [DrawDay.SATURDAY, DrawDay.WEDNESDAY,
                        DrawDay.TUESDAY, DrawDay.FRIDAY]:
                latest = self._db.get_draws(day)
                count = self._db.get_draw_count(day)
                if count > 0:
                    parts.append(f"\n{day.value}: {count} Ziehungen")
                    if latest:
                        last_5 = latest[-5:]
                        draws_txt = []
                        for d in last_5:
                            nums = sorted(d.numbers)
                            if d.is_eurojackpot:
                                bonus = sorted(d.bonus_numbers) if d.bonus_numbers else []
                                draws_txt.append(
                                    f"  {d.draw_date.strftime('%d.%m.%Y')}: {nums} EZ:{bonus}"
                                )
                            else:
                                sz = d.super_number if d.super_number is not None else "?"
                                draws_txt.append(
                                    f"  {d.draw_date.strftime('%d.%m.%Y')}: {nums} SZ:{sz}"
                                )
                        parts.append(
                            f"Letzte 5 {day.value}-Ziehungen:\n"
                            + "\n".join(draws_txt)
                        )
                    parts.append("---")
            sat = self._db.get_draw_count(DrawDay.SATURDAY)
            wed = self._db.get_draw_count(DrawDay.WEDNESDAY)
            tue = self._db.get_draw_count(DrawDay.TUESDAY)
            fri = self._db.get_draw_count(DrawDay.FRIDAY)
            parts.insert(0,
                f"=== LOTTO DATENBANK-KONTEXT ===\n"
                f"6aus49 — Sa: {sat} | Mi: {wed}\n"
                f"EuroJackpot — Di: {tue} | Fr: {fri}\n"
            )
            return "\n".join(parts)
        except Exception as e:
            logger.debug(f"DB-Kontext zusammenstellen fehlgeschlagen: {e}")
            return ""

    def _on_ai_response(self, text: str) -> None:
        """AI-Antwort empfangen."""
        self._chat_box.set_busy(False)
        if self._thinking_label:
            self._chat_box.remove_widget(self._thinking_label)
        self._thinking_label = None
        self._chat_box.add_ai_message(text)
        self._chat_box.scroll_to_bottom()
        if self._session_id:
            self._save_message(self._session_id, "assistant", text)

    def _on_user_message(self, _widget, text: str) -> None:
        """User hat im ChatBox eine Nachricht gesendet."""
        self._ensure_session()
        if self._session_id:
            self._save_message(self._session_id, "user", text)
        self._chat_box.add_user_message(text)
        self._thinking_label = self._chat_box.add_thinking()
        self._chat_box.set_busy(True)

        def run():
            try:
                result = self._chat(text)
                if not self._cancel_event.is_set():
                    GLib.idle_add(self._on_ai_response, result)
            except Exception as e:
                if not self._cancel_event.is_set():
                    GLib.idle_add(self._on_ai_response, f"Fehler: {e}")
        threading.Thread(target=run, daemon=True).start()

    def set_context(self, context_text: str) -> None:
        """Externen Kontext setzen (z.B. Backtest-Bericht).

        Wird beim nächsten Chat als Kontext vorangestellt.
        Ersetzt den Standard-DB-Kontext.
        """
        self._external_context = context_text
        self._context_sent = False

    # ── Session-Verwaltung ──

    def _on_new_chat(self, _btn) -> None:
        self._session_id = None
        self._context_sent = False
        self._chat_box.clear()
        if self.api_client:
            try:
                self.api_client.clear_chat()
            except Exception as e:
                logger.warning(f"Chat löschen via API fehlgeschlagen: {e}")

    def _on_history_show(self, _popover) -> None:
        while child := self._history_box.get_first_child():
            self._history_box.remove(child)

        sessions = self._get_sessions()
        if not sessions:
            lbl = Gtk.Label(label="Keine gespeicherten Chats.")
            lbl.add_css_class("dim-label")
            self._history_box.append(lbl)
            return

        for sess in sessions[:15]:
            title = sess.get("title") or f"Chat #{sess['id']}"
            created = sess.get("created_at", "")[:16]
            btn = Gtk.Button()
            btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title_lbl = Gtk.Label(label=title[:50], xalign=0)
            title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            btn_box.append(title_lbl)
            date_lbl = Gtk.Label(label=created, xalign=0)
            date_lbl.add_css_class("dim-label")
            date_lbl.add_css_class("caption")
            btn_box.append(date_lbl)
            btn.set_child(btn_box)
            btn.connect("clicked", self._on_load_session, sess["id"])
            self._history_box.append(btn)

    def _on_load_session(self, _btn, session_id: int) -> None:
        self._history_popover.popdown()
        self._session_id = session_id
        self._chat_box.clear()
        messages = self._get_messages(session_id)
        for msg in messages:
            if msg["role"] == "user":
                self._chat_box.add_user_message(msg["content"])
            else:
                self._chat_box.add_ai_message(msg["content"])
        self._chat_box.scroll_to_bottom()

    def cleanup(self) -> None:
        """Laufende AI-Anfragen abbrechen."""
        self._cancel_event.set()

    def _on_delete_chat(self, _btn) -> None:
        if self._session_id:
            self._delete_session(self._session_id)
        self._session_id = None
        self._chat_box.clear()
