"""ImprovementReportPanel: Bericht-Widget mit TTS + AI-Diskussion."""

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_analyzer.ui.widgets.speak_button import SpeakButton
from lotto_analyzer.ui.widgets.mic_button import MicButton
from lotto_common.utils.logging_config import get_logger

logger = get_logger("improvement_report")


class ImprovementReportPanel(Gtk.Box):
    """Wiederverwendbares Widget für ML-Verbesserungsberichte.

    Features:
    - Bericht anzeigen (selectable Text)
    - Komplett vorlesen (SpeakButton)
    - Markierten Text vorlesen
    - AI-Diskussion ueber den Bericht
    - Spracheingabe via MicButton
    """

    def __init__(
        self, ai_analyst=None, api_client=None,
        audio_service=None, config_manager=None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.ai_analyst = ai_analyst
        self.api_client = api_client
        self._audio_service = audio_service
        self._config_manager = config_manager
        self._report_text = ""
        self._chat_history: list[tuple[str, str]] = []  # (frage, antwort)

        self._build_ui()

    def _build_ui(self) -> None:
        # ── Header ──
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_top(12)
        header.set_margin_start(12)
        header.set_margin_end(12)

        icon = Gtk.Image.new_from_icon_name("document-properties-symbolic")
        header.append(icon)

        title = Gtk.Label(label="ML-Verbesserungsbericht")
        title.add_css_class("title-3")
        title.set_hexpand(True)
        title.set_xalign(0)
        header.append(title)

        # SpeakButton für gesamten Bericht
        self._speak_btn = SpeakButton(
            audio_service=self._audio_service,
            config_manager=self._config_manager,
        )
        header.append(self._speak_btn)

        self.append(header)
        self.append(Gtk.Separator())

        # ── Bericht-Anzeige ──
        report_scroll = Gtk.ScrolledWindow()
        report_scroll.set_min_content_height(200)
        report_scroll.set_vexpand(True)
        report_scroll.set_margin_start(12)
        report_scroll.set_margin_end(12)

        self._report_label = Gtk.Label(
            label="Noch kein Bericht vorhanden. Starte Self-Improvement um einen Bericht zu generieren.",
        )
        self._report_label.set_wrap(True)
        self._report_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._report_label.set_xalign(0)
        self._report_label.set_valign(Gtk.Align.START)
        self._report_label.set_selectable(True)
        report_scroll.set_child(self._report_label)

        self.append(report_scroll)

        # ── Auswahl-Vorlesen Button ──
        selection_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        selection_box.set_margin_start(12)
        selection_box.set_margin_end(12)

        self._selection_speak_btn = Gtk.Button(label="Auswahl vorlesen")
        self._selection_speak_btn.set_icon_name("audio-speakers-symbolic")
        self._selection_speak_btn.add_css_class("flat")
        self._selection_speak_btn.connect("clicked", self._on_speak_selection)
        self._selection_speak_btn.set_tooltip_text(
            "Markiere Text im Bericht und klicke hier zum Vorlesen"
        )
        selection_box.append(self._selection_speak_btn)

        self.append(selection_box)
        self.append(Gtk.Separator())

        # ── AI-Diskussion ──
        chat_header = Gtk.Label(label="Fragen zum Bericht")
        chat_header.add_css_class("heading")
        chat_header.set_xalign(0)
        chat_header.set_margin_start(12)
        chat_header.set_margin_top(4)
        self.append(chat_header)

        # Chat-Verlauf
        self._chat_scroll = Gtk.ScrolledWindow()
        self._chat_scroll.set_min_content_height(100)
        self._chat_scroll.set_vexpand(False)
        self._chat_scroll.set_margin_start(12)
        self._chat_scroll.set_margin_end(12)

        self._chat_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4,
        )
        self._chat_scroll.set_child(self._chat_box)
        self.append(self._chat_scroll)

        # Spinner für AI-Antwort
        self._chat_spinner = Gtk.Spinner()
        self._chat_spinner.set_visible(False)
        self.append(self._chat_spinner)

        # Eingabezeile
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        input_box.set_margin_start(12)
        input_box.set_margin_end(12)
        input_box.set_margin_bottom(12)

        self._entry = Gtk.Entry()
        self._entry.set_hexpand(True)
        self._entry.set_placeholder_text("Frage zum Bericht...")
        self._entry.connect("activate", self._on_send)
        input_box.append(self._entry)

        # MicButton
        self._mic_btn = MicButton(audio_service=self._audio_service)
        self._mic_btn.connect("transcribed", self._on_mic_transcribed)
        input_box.append(self._mic_btn)

        # Senden-Button
        send_btn = Gtk.Button(icon_name="mail-send-symbolic")
        send_btn.set_tooltip_text("Frage senden")
        send_btn.add_css_class("suggested-action")
        send_btn.connect("clicked", self._on_send)
        input_box.append(send_btn)

        self.append(input_box)

    # ── Public API ──

    def set_report(self, report_text: str) -> None:
        """Bericht anzeigen und SpeakButton konfigurieren."""
        self._report_text = report_text
        self._report_label.set_label(report_text)
        self._speak_btn.text = report_text
        self._chat_history.clear()
        # Chat-Box leeren
        while self._chat_box.get_first_child():
            self._chat_box.remove(self._chat_box.get_first_child())

    def set_audio_service(self, audio_service) -> None:
        """AudioService nachtraeglich setzen."""
        self._audio_service = audio_service
        self._speak_btn.audio_service = audio_service
        self._mic_btn.audio_service = audio_service

    # ── Event Handler ──

    def _on_speak_selection(self, btn) -> None:
        """Markierten Text vorlesen."""
        if not self._audio_service:
            return

        # GTK4: selection_bounds gibt es nicht direkt auf Labels.
        # Wir nutzen den gesamten Text wenn nichts markiert ist,
        # sonst den Clipboard-Inhalt.
        clipboard = self._report_label.get_clipboard()
        if clipboard:
            # Async lesen — bei Erfolg vorlesen
            clipboard.read_text_async(None, self._on_clipboard_read)
        else:
            # Fallback: ganzen Bericht vorlesen
            self._audio_service.speak(self._report_text)

    def _on_clipboard_read(self, clipboard, result) -> None:
        """Callback wenn Clipboard-Text gelesen wurde."""
        try:
            text = clipboard.read_text_finish(result)
            if text and text.strip():
                self._audio_service.speak(text.strip())
            elif self._report_text:
                self._audio_service.speak(self._report_text)
        except Exception as e:
            logger.debug(f"Clipboard für TTS lesen fehlgeschlagen: {e}")
            if self._report_text:
                self._audio_service.speak(self._report_text)

    def _on_send(self, widget) -> None:
        """Frage an AI senden."""
        question = self._entry.get_text().strip()
        if not question:
            return
        self._entry.set_text("")
        self._ask_ai(question)

    def _on_mic_transcribed(self, btn, text) -> None:
        """Transkription in Eingabefeld uebernehmen."""
        self._entry.set_text(text)

    def _ask_ai(self, question: str) -> None:
        """AI-Frage zum Bericht stellen."""
        if not self.ai_analyst and not self.api_client:
            self._add_chat_message(question, "Kein AI-Backend verfügbar.")
            return

        self._chat_spinner.set_visible(True)
        self._chat_spinner.start()

        # Frage-Label sofort anzeigen
        q_label = Gtk.Label(label=f"Du: {question}")
        q_label.add_css_class("heading")
        q_label.set_xalign(0)
        q_label.set_wrap(True)
        q_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._chat_box.append(q_label)

        def worker():
            try:
                # Bericht als Kontext mitgeben
                context_prompt = (
                    f"Kontext: Folgender ML-Verbesserungsbericht wurde erstellt:\n"
                    f"---\n{self._report_text[:3000]}\n---\n\n"
                    f"Frage des Benutzers: {question}\n\n"
                    f"Antworte auf Deutsch, beziehe dich auf den Bericht."
                )
                if self.ai_analyst:
                    reply = self.ai_analyst.chat(context_prompt)
                elif self.api_client:
                    reply = self.api_client.chat(context_prompt)
                else:
                    reply = "Kein AI-Backend"
                GLib.idle_add(self._show_ai_reply, question, reply)
            except Exception as e:
                GLib.idle_add(
                    self._show_ai_reply, question, f"Fehler: {e}",
                )

        threading.Thread(target=worker, daemon=True).start()

    def _show_ai_reply(self, question: str, reply: str) -> bool:
        """AI-Antwort in Chat-Verlauf anzeigen."""
        self._chat_spinner.stop()
        self._chat_spinner.set_visible(False)

        self._chat_history.append((question, reply))

        # Antwort-Box mit SpeakButton
        answer_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
        )

        answer_label = Gtk.Label(label=f"AI: {reply}")
        answer_label.set_xalign(0)
        answer_label.set_wrap(True)
        answer_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        answer_label.set_selectable(True)
        answer_label.set_hexpand(True)
        answer_box.append(answer_label)

        # SpeakButton für diese Antwort
        speak = SpeakButton(
            audio_service=self._audio_service,
            config_manager=self._config_manager,
        )
        speak.text = reply
        answer_box.append(speak)

        self._chat_box.append(answer_box)
        self._chat_box.append(Gtk.Separator())

        # Scroll nach unten
        adj = self._chat_scroll.get_vadjustment()
        if adj:
            adj.set_value(adj.get_upper())

        return False

    def _add_chat_message(self, question: str, reply: str) -> None:
        """Chat-Nachricht direkt hinzufügen (ohne Thread)."""
        q_label = Gtk.Label(label=f"Du: {question}")
        q_label.add_css_class("heading")
        q_label.set_xalign(0)
        q_label.set_wrap(True)
        self._chat_box.append(q_label)

        a_label = Gtk.Label(label=f"AI: {reply}")
        a_label.set_xalign(0)
        a_label.set_wrap(True)
        a_label.set_selectable(True)
        self._chat_box.append(a_label)
        self._chat_box.append(Gtk.Separator())
