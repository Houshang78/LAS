"""ChatBox Widget: Wiederverwendbarer Chat-Bereich mit Bubbles, Scroll, Input.

Reines UI-Widget ohne AI-Logik. Kann von AIPanel, Monitor, Telegram etc. genutzt werden.
Signale:
    message-submitted(str): User hat eine Nachricht gesendet (Enter oder Button)
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Pango, GLib, GObject
import logging

from lotto_analyzer.ui.widgets.speak_button import SpeakButton
from lotto_analyzer.ui.widgets.mic_button import MicButton

logger = logging.getLogger("chat_box")


class ChatBox(Gtk.Box):
    """Wiederverwendbarer Chat-Bereich mit Bubbles, Scroll, Eingabe, Mic, Speaker."""

    __gsignals__ = {
        "message-submitted": (GObject.SignalFlags.RUN_LAST, None, (str,)),
        "message-deleted": (GObject.SignalFlags.RUN_LAST, None, (str,)),
        "message-edited": (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(
        self,
        placeholder: str = "Stelle eine Frage...",
        input_placeholder: str = "Nachricht eingeben...",
        audio_service=None,
        config_manager=None,
        min_height: int = 80,
        max_height: int = 600,
        show_header: bool = True,
        title: str = "",
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._audio_service = audio_service
        self._config_manager = config_manager
        self._min_height = min_height
        self._max_height = max_height
        self._msg_count = 0
        self._scroll_timer = None

        # ── Header (optional) ──
        if show_header and title:
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            header.set_margin_top(8)
            header.set_margin_start(8)
            header.set_margin_end(8)
            lbl = Gtk.Label(label=title)
            lbl.add_css_class("heading")
            lbl.set_hexpand(True)
            lbl.set_xalign(0)
            header.append(lbl)

            # SpeakButton (Header — liest ganzen Chat oder Markierung vor)
            self._header_speak_btn = SpeakButton(
                audio_service=audio_service, config_manager=config_manager,
            )
            self._header_speak_btn.set_tooltip_text("Ganzen Chat vorlesen (oder Markierung)")
            self._header_speak_btn.connect("clicked", self._on_header_speak_clicked)
            header.append(self._header_speak_btn)

            # Neuer Chat
            new_btn = Gtk.Button(icon_name="tab-new-symbolic", tooltip_text="Neuer Chat")
            new_btn.connect("clicked", lambda _: self.clear())
            header.append(new_btn)

            # Löschen
            del_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Chat löschen")
            del_btn.add_css_class("destructive-action")
            del_btn.connect("clicked", lambda _: self.clear())
            header.append(del_btn)

            self.append(header)
            self.append(Gtk.Separator())
        else:
            self._header_speak_btn = None

        # ── Chat-Bereich ──
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_margin_start(8)
        self._scroll.set_margin_end(8)
        self._scroll.set_min_content_height(min_height)
        self._scroll.set_max_content_height(max_height)

        self._chat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._scroll.set_child(self._chat_box)
        self.append(self._scroll)

        # Platzhalter
        self._placeholder_text = placeholder
        self._placeholder = Gtk.Label(label=placeholder)
        self._placeholder.add_css_class("dim-label")
        self._placeholder.set_wrap(True)
        self._placeholder.set_xalign(0)
        self._chat_box.append(self._placeholder)

        # ── Spinner ──
        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        self.append(self._spinner)

        # ── Eingabe ──
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        input_box.set_margin_start(8)
        input_box.set_margin_end(8)
        input_box.set_margin_bottom(8)

        self._entry = Gtk.Entry()
        self._entry.set_hexpand(True)
        self._entry.set_placeholder_text(input_placeholder)
        self._entry.connect("activate", self._on_submit)
        input_box.append(self._entry)

        self._mic_btn = MicButton(audio_service=audio_service)
        self._mic_btn.connect("transcribed", self._on_mic_transcribed)
        input_box.append(self._mic_btn)

        send_btn = Gtk.Button(icon_name="mail-send-symbolic")
        send_btn.set_tooltip_text("Senden")
        send_btn.add_css_class("suggested-action")
        send_btn.connect("clicked", self._on_submit)
        input_box.append(send_btn)

        self.append(input_box)

    # ── Oeffentliche API ──

    def add_user_message(self, text: str) -> None:
        """User-Nachricht als Box mit Toolbar (Edit, Delete, Speaker)."""
        self._remove_placeholder()

        frame = Gtk.Frame()
        frame.add_css_class("card")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Toolbar
        toolbar = Gtk.Box(spacing=2, halign=Gtk.Align.END)
        toolbar.set_margin_top(2)
        toolbar.set_margin_end(4)

        if self._audio_service:
            speak = SpeakButton(audio_service=self._audio_service, config_manager=self._config_manager)
            speak.text = text
            speak.set_tooltip_text("Vorlesen")
            toolbar.append(speak)

        edit_btn = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Bearbeiten")
        edit_btn.add_css_class("flat")
        edit_btn.add_css_class("circular")
        toolbar.append(edit_btn)

        del_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Löschen")
        del_btn.add_css_class("flat")
        del_btn.add_css_class("circular")
        del_btn.connect("clicked", self._on_bubble_delete, frame)
        toolbar.append(del_btn)

        box.append(toolbar)

        # Nachricht
        lbl = Gtk.Label(label=text)
        lbl.set_wrap(True)
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lbl.set_xalign(0)
        lbl.set_selectable(True)
        lbl.set_margin_start(12)
        lbl.set_margin_end(12)
        lbl.set_margin_bottom(8)
        box.append(lbl)

        # Edit-Handler (braucht Referenz auf Label)
        edit_btn.connect("clicked", self._on_bubble_edit, lbl, frame)

        frame.set_child(box)
        self._chat_box.append(frame)
        self._msg_count += 1
        self._update_scroll_height()

    def add_ai_message(self, text: str) -> Gtk.Label:
        """AI-Antwort als Box mit Toolbar (Speaker, Delete)."""
        self._remove_placeholder()

        frame = Gtk.Frame()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Toolbar
        toolbar = Gtk.Box(spacing=2, halign=Gtk.Align.END)
        toolbar.set_margin_top(2)
        toolbar.set_margin_end(4)

        if self._audio_service:
            speak = SpeakButton(audio_service=self._audio_service, config_manager=self._config_manager)
            speak.text = text
            speak.set_tooltip_text("Vorlesen")
            toolbar.append(speak)

        del_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Löschen")
        del_btn.add_css_class("flat")
        del_btn.add_css_class("circular")
        del_btn.connect("clicked", self._on_bubble_delete, frame)
        toolbar.append(del_btn)

        box.append(toolbar)

        # Nachricht
        lbl = Gtk.Label(label=text)
        lbl.set_wrap(True)
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lbl.set_xalign(0)
        lbl.set_selectable(True)
        lbl.set_margin_start(12)
        lbl.set_margin_end(12)
        lbl.set_margin_bottom(8)
        box.append(lbl)

        frame.set_child(box)
        self._chat_box.append(frame)
        self._msg_count += 1
        self._update_scroll_height()
        return lbl

    def add_message(self, text: str, is_user: bool = False) -> None:
        """Nachricht hinzufügen (Convenience-Methode)."""
        if is_user:
            self.add_user_message(text)
        else:
            self.add_ai_message(text)
        self.scroll_to_bottom()

    def add_thinking(self) -> Gtk.Label:
        """'AI denkt nach...' Platzhalter hinzufügen."""
        lbl = Gtk.Label(label="AI denkt nach...")
        lbl.add_css_class("dim-label")
        lbl.set_wrap(True)
        lbl.set_xalign(0)
        self._chat_box.append(lbl)
        return lbl

    def remove_widget(self, widget: Gtk.Widget) -> None:
        """Widget aus Chat-Box entfernen (z.B. Thinking-Platzhalter)."""
        if widget and widget.get_parent() == self._chat_box:
            self._chat_box.remove(widget)

    def clear(self) -> None:
        """Alle Nachrichten entfernen und Platzhalter anzeigen."""
        while child := self._chat_box.get_first_child():
            self._chat_box.remove(child)
        self._placeholder = Gtk.Label(label=self._placeholder_text)
        self._placeholder.add_css_class("dim-label")
        self._placeholder.set_wrap(True)
        self._placeholder.set_xalign(0)
        self._chat_box.append(self._placeholder)
        self._msg_count = 0
        self._update_scroll_height()

    def set_busy(self, busy: bool) -> None:
        """Spinner an/aus und Eingabe sperren/freigeben."""
        self._spinner.set_visible(busy)
        if busy:
            self._spinner.start()
        else:
            self._spinner.stop()
        self._entry.set_sensitive(not busy)

    def scroll_to_bottom(self) -> None:
        """Chat nach unten scrollen."""
        def _do_scroll():
            self._scroll_timer = None
            adj = self._scroll.get_vadjustment()
            adj.set_value(adj.get_upper())
            # Aeusserer Scroll (wenn in ScrolledWindow eingebettet)
            parent = self.get_parent()
            while parent:
                if isinstance(parent, Gtk.ScrolledWindow):
                    outer = parent.get_vadjustment()
                    outer.set_value(outer.get_upper())
                    break
                parent = parent.get_parent()
            return False
        if self._scroll_timer:
            GLib.source_remove(self._scroll_timer)
        self._scroll_timer = GLib.timeout_add(50, _do_scroll)

    def cleanup_timers(self) -> None:
        """Alle laufenden Timer bereinigen."""
        if self._scroll_timer:
            GLib.source_remove(self._scroll_timer)
            self._scroll_timer = None

    @property
    def entry(self) -> Gtk.Entry:
        """Zugriff auf das Eingabefeld (z.B. für externen Text)."""
        return self._entry

    # ── Interne Methoden ──

    def _remove_placeholder(self) -> None:
        if self._placeholder and self._placeholder.get_parent():
            self._chat_box.remove(self._placeholder)

    def _update_scroll_height(self) -> None:
        """Scroll-Hoehe an Inhalt anpassen."""
        GLib.idle_add(self._sync_scroll_height)

    def _sync_scroll_height(self) -> bool:
        _, nat_h, _, _ = self._chat_box.measure(Gtk.Orientation.VERTICAL, -1)
        h = min(max(nat_h, self._min_height), self._max_height)
        self._scroll.set_min_content_height(h)
        self.scroll_to_bottom()
        return False

    def get_all_text(self) -> str:
        """Gesamten Chat-Text als String zurückgeben."""
        parts = []
        child = self._chat_box.get_first_child()
        while child:
            if isinstance(child, Gtk.Frame):
                # Labels in Frame > Box > Label suchen
                box = child.get_child()
                if isinstance(box, Gtk.Box):
                    inner = box.get_first_child()
                    while inner:
                        if isinstance(inner, Gtk.Label) and inner.get_text():
                            parts.append(inner.get_text())
                        inner = inner.get_next_sibling()
            elif isinstance(child, Gtk.Label):
                parts.append(child.get_text())
            child = child.get_next_sibling()
        return "\n\n".join(parts)

    def _on_header_speak_clicked(self, btn) -> None:
        """Header-Speaker: Markierung vorlesen, oder ganzen Chat."""
        # Zuerst prüfen ob Text markiert ist
        clipboard = self.get_clipboard()
        if clipboard:
            clipboard.read_text_async(None, self._on_header_sel_read)
        else:
            self._header_speak_btn.text = self.get_all_text()

    def _on_header_sel_read(self, clipboard, result) -> None:
        """Clipboard-Text prüfen — Markierung oder ganzer Chat."""
        try:
            sel = clipboard.read_text_finish(result)
            if sel and sel.strip() and len(sel.strip()) > 2:
                self._header_speak_btn.text = sel.strip()
            else:
                self._header_speak_btn.text = self.get_all_text()
        except Exception as e:
            logger.debug(f"Clipboard lesen fehlgeschlagen: {e}")
            self._header_speak_btn.text = self.get_all_text()

    def _on_submit(self, _widget) -> None:
        """User drueckt Enter oder Send-Button."""
        text = self._entry.get_text().strip()
        if not text:
            return
        self._entry.set_text("")
        self.emit("message-submitted", text)

    def _on_mic_transcribed(self, _btn, text: str) -> None:
        """Spracheingabe uebernehmen und senden."""
        if text:
            self._entry.set_text(text)
            self._on_submit(None)

    def _on_bubble_delete(self, _btn, frame: Gtk.Frame) -> None:
        """Einzelne Nachricht aus dem Chat entfernen."""
        if frame.get_parent() == self._chat_box:
            # Text extrahieren bevor Frame entfernt wird
            text = self._extract_text(frame)
            self._chat_box.remove(frame)
            self._msg_count = max(0, self._msg_count - 1)
            self._update_scroll_height()
            self.emit("message-deleted", text)

    def _on_bubble_edit(self, _btn, lbl: Gtk.Label, frame: Gtk.Frame) -> None:
        """User-Nachricht bearbeiten — Text ins Eingabefeld laden, Bubble entfernen."""
        text = lbl.get_text()
        self._entry.set_text(text)
        self._entry.grab_focus()
        if frame.get_parent() == self._chat_box:
            self._chat_box.remove(frame)
            self._msg_count = max(0, self._msg_count - 1)
            self.emit("message-edited", text)

    @staticmethod
    def _extract_text(frame: Gtk.Frame) -> str:
        """Text aus einem Frame>Box>Label extrahieren."""
        box = frame.get_child()
        if isinstance(box, Gtk.Box):
            child = box.get_first_child()
            while child:
                if isinstance(child, Gtk.Label) and not child.has_css_class("dim-label"):
                    return child.get_text()
                child = child.get_next_sibling()
        return ""
