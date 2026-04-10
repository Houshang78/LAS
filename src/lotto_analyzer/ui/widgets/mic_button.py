"""MicButton: Mikrofon-Button für Spracheingabe via OpenAI Whisper."""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject, GLib


class MicButton(Gtk.Button):
    """Toggle-Button für Mikrofon-Aufnahme mit Whisper-Transkription."""

    __gsignals__ = {
        "transcribed": (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    ICON_MIC = "audio-input-microphone-symbolic"
    ICON_REC = "media-record-symbolic"

    def __init__(self, audio_service=None):
        super().__init__(icon_name=self.ICON_MIC)
        self._audio = audio_service
        self.set_tooltip_text("Spracheingabe")
        self.add_css_class("flat")
        self.connect("clicked", self._on_clicked)
        self._update_sensitivity()

    @property
    def audio_service(self):
        return self._audio

    @audio_service.setter
    def audio_service(self, value) -> None:
        self._audio = value
        self._update_sensitivity()

    def _update_sensitivity(self) -> None:
        """Deaktiviert wenn kein OpenAI-Key vorhanden."""
        available = self._audio and self._audio.stt_available
        self.set_sensitive(available)
        if not available:
            self.set_tooltip_text("OpenAI API-Key in Einstellungen eintragen")
        else:
            self.set_tooltip_text("Spracheingabe")

    def _on_clicked(self, _btn) -> None:
        if not self._audio or not self._audio.stt_available:
            return

        if self._audio.is_recording:
            # Stop + Transkription
            self.set_icon_name(self.ICON_MIC)
            self.remove_css_class("destructive-action")
            self.set_tooltip_text("Spracheingabe")
            self.set_sensitive(False)  # Warten auf Transkription
            self._audio.stop_recording(
                on_result=self._on_result,
                on_error=self._on_error,
            )
        else:
            # Aufnahme starten
            self._audio.start_recording()
            if self._audio.is_recording:
                self.set_icon_name(self.ICON_REC)
                self.add_css_class("destructive-action")
                self.set_tooltip_text("Aufnahme stoppen")

    def _on_result(self, text: str) -> bool:
        self.set_sensitive(True)
        if text:
            self.emit("transcribed", text)
        return False

    def _on_error(self, msg: str) -> bool:
        self.set_sensitive(True)
        self.set_icon_name(self.ICON_MIC)
        self.remove_css_class("destructive-action")
        return False
