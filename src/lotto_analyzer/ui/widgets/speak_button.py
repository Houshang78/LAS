"""SpeakButton: MenuButton mit TTS-Popover (Fortschritt, Geschwindigkeit, Sprache)."""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

# Verfügbare TTS-Sprachen (Code → Anzeigename)
TTS_LANGUAGES = [
    ("de", "Deutsch"),
    ("en", "English"),
    ("fr", "Français"),
    ("es", "Español"),
    ("it", "Italiano"),
    ("tr", "Türkçe"),
]


class TtsPopover(Gtk.Popover):
    """Popover mit Fortschritt, Geschwindigkeit und Sprach-Auswahl."""

    def __init__(self, audio_service, config_manager=None):
        super().__init__()
        self._audio = audio_service
        self._config_manager = config_manager
        self._poll_id: int = 0
        self._seeking = False  # Verhindert Feedback-Loop beim programmatischen Update

        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        grid.set_margin_top(12)
        grid.set_margin_bottom(12)
        grid.set_margin_start(12)
        grid.set_margin_end(12)

        # ── Reihe 0: Play/Stop + Fortschrittsbalken + Zeitlabel + Schliessen ──
        self._play_btn = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self._play_btn.add_css_class("flat")
        self._play_btn.set_tooltip_text("Abspielen / Stoppen")
        self._play_btn.connect("clicked", self._on_play_stop)
        grid.attach(self._play_btn, 0, 0, 1, 1)

        self._progress = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.01,
        )
        self._progress.set_draw_value(False)
        self._progress.set_hexpand(True)
        self._progress.set_size_request(180, -1)
        self._progress.connect("change-value", self._on_seek)
        grid.attach(self._progress, 1, 0, 1, 1)

        self._time_label = Gtk.Label(label="0:00 / 0:00")
        self._time_label.add_css_class("dim-label")
        self._time_label.set_width_chars(11)
        grid.attach(self._time_label, 2, 0, 1, 1)

        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.set_tooltip_text("Schliessen")
        close_btn.connect("clicked", self._on_close)
        grid.attach(close_btn, 3, 0, 1, 1)

        # ── Reihe 1: Geschwindigkeit ──
        speed_label = Gtk.Label(label="Geschw.")
        speed_label.set_xalign(1.0)
        grid.attach(speed_label, 0, 1, 1, 1)

        initial_speed = 1.0
        if config_manager:
            initial_speed = config_manager.config.audio.tts_speed

        self._speed_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.5, 2.0, 0.1,
        )
        self._speed_scale.set_value(initial_speed)
        self._speed_scale.set_draw_value(False)
        self._speed_scale.set_hexpand(True)
        self._speed_scale.connect("value-changed", self._on_speed_changed)
        grid.attach(self._speed_scale, 1, 1, 1, 1)

        self._speed_label = Gtk.Label(label=f"{initial_speed:.1f}x")
        self._speed_label.set_width_chars(4)
        grid.attach(self._speed_label, 2, 1, 1, 1)

        # ── Reihe 2: Sprache ──
        lang_label = Gtk.Label(label="Sprache:")
        lang_label.set_xalign(1.0)
        grid.attach(lang_label, 0, 2, 1, 1)

        self._lang_list = Gtk.StringList()
        for _code, name in TTS_LANGUAGES:
            self._lang_list.append(name)
        self._lang_dropdown = Gtk.DropDown(model=self._lang_list)
        self._lang_dropdown.set_hexpand(True)

        # Aktuelle Sprache vorwählen
        current_lang = "de"
        if config_manager:
            current_lang = config_manager.config.audio.tts_language
        for i, (code, _name) in enumerate(TTS_LANGUAGES):
            if code == current_lang:
                self._lang_dropdown.set_selected(i)
                break
        self._lang_dropdown.connect("notify::selected", self._on_lang_changed)
        grid.attach(self._lang_dropdown, 1, 2, 2, 1)

        self.set_child(grid)

    def _fmt_time(self, seconds: float) -> str:
        """Sekunden → m:ss Format."""
        s = max(0, int(seconds))
        return f"{s // 60}:{s % 60:02d}"

    # ── Play/Stop ──

    def _on_play_stop(self, _btn) -> None:
        if not self._audio:
            return
        if self._audio.is_speaking:
            self._stop()
        else:
            self._play()

    def _play(self) -> None:
        """TTS starten mit aktuellem Text."""
        parent = self.get_parent()
        if not parent or not hasattr(parent, "_text") or not parent._text:
            return
        if not self._audio:
            return

        # Rate vor Playback setzen
        self._audio.set_rate(self._speed_scale.get_value())
        self._play_btn.set_icon_name("media-playback-stop-symbolic")
        self._audio.speak(
            parent._text,
            on_done=self._on_done,
            on_error=self._on_error,
        )
        self._start_polling()

    def _stop(self) -> None:
        """Playback stoppen."""
        self._stop_polling()
        if self._audio:
            self._audio.stop_speaking()
        self._play_btn.set_icon_name("media-playback-start-symbolic")
        self._progress.set_value(0.0)
        self._time_label.set_label("0:00 / 0:00")

    def _on_done(self) -> bool:
        self._stop_polling()
        self._play_btn.set_icon_name("media-playback-start-symbolic")
        self._progress.set_value(0.0)
        self._time_label.set_label("0:00 / 0:00")
        return False

    def _on_error(self, msg: str) -> bool:
        self._stop_polling()
        self._play_btn.set_icon_name("media-playback-start-symbolic")
        return False

    # ── Position Polling ──

    def _start_polling(self) -> None:
        if self._poll_id == 0:
            self._poll_id = GLib.timeout_add(200, self._poll_position)

    def _stop_polling(self) -> None:
        if self._poll_id:
            GLib.source_remove(self._poll_id)
            self._poll_id = 0

    def _poll_position(self) -> bool:
        if not self._audio or not self._audio.is_speaking:
            self._poll_id = 0
            return False
        pos = self._audio.get_position()
        dur = self._audio.get_duration()
        if dur > 0 and not self._seeking:
            self._progress.set_value(pos / dur)
        self._time_label.set_label(
            f"{self._fmt_time(pos)} / {self._fmt_time(dur)}"
        )
        return True

    # ── Seek ──

    def _on_seek(self, scale, scroll_type, value) -> bool:
        """User zieht den Fortschrittsbalken."""
        if not self._audio or not self._audio.is_speaking:
            return False
        dur = self._audio.get_duration()
        if dur > 0:
            self._seeking = True
            self._audio.seek_to(value * dur)
            GLib.timeout_add(300, self._reset_seeking)
        return False

    def _reset_seeking(self) -> bool:
        self._seeking = False
        return False

    # ── Geschwindigkeit ──

    def _on_speed_changed(self, scale) -> None:
        rate = round(scale.get_value(), 1)
        self._speed_label.set_label(f"{rate:.1f}x")
        if self._audio:
            self._audio.set_rate(rate)
        # Persistieren
        if self._config_manager:
            self._config_manager.config.audio.tts_speed = rate
            self._config_manager.save()

    # ── Sprache ──

    def _on_lang_changed(self, dropdown, _pspec) -> None:
        idx = dropdown.get_selected()
        if idx < 0 or idx >= len(TTS_LANGUAGES):
            return
        code = TTS_LANGUAGES[idx][0]
        # Laufende Wiedergabe stoppen (Neu-Synthese noetig)
        if self._audio and self._audio.is_speaking:
            self._stop()
        if self._audio:
            self._audio.tts_lang = code
        # Persistieren
        if self._config_manager:
            self._config_manager.config.audio.tts_language = code
            self._config_manager.save()

    def _on_close(self, _btn) -> None:
        """Popover schliessen und Wiedergabe stoppen."""
        self._stop()
        self.popdown()

    def cleanup(self) -> None:
        """Polling stoppen."""
        self._stop_polling()


class SpeakButton(Gtk.MenuButton):
    """Lautsprecher-MenuButton: Oeffnet TtsPopover mit Fortschritt/Speed/Sprache."""

    ICON_SPEAK = "audio-speakers-symbolic"

    def __init__(self, audio_service=None, config_manager=None):
        super().__init__(icon_name=self.ICON_SPEAK)
        self._audio = audio_service
        self._config_manager = config_manager
        self._text = ""
        self._popover: TtsPopover | None = None
        self.set_tooltip_text("Vorlesen")
        self.add_css_class("flat")

        if audio_service:
            self._ensure_popover()

    def _ensure_popover(self) -> None:
        """Popover erstellen/aktualisieren wenn AudioService vorhanden."""
        if self._popover:
            self._popover.cleanup()
        self._popover = TtsPopover(self._audio, self._config_manager)
        self.set_popover(self._popover)

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        self._text = value or ""

    @property
    def audio_service(self):
        return self._audio

    @audio_service.setter
    def audio_service(self, value) -> None:
        self._audio = value
        if value:
            self._ensure_popover()

    @property
    def config_manager(self):
        return self._config_manager

    @config_manager.setter
    def config_manager(self, value) -> None:
        self._config_manager = value
        if self._audio:
            self._ensure_popover()
