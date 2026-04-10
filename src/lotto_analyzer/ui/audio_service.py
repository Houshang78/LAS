"""Audio-Service: TTS (gTTS) + STT (OpenAI Whisper) + GStreamer Playback/Recording."""

import tempfile
import threading
from pathlib import Path

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

from lotto_common.utils.logging_config import get_logger

logger = get_logger("audio_service")

# GStreamer einmalig initialisieren
Gst.init(None)


class AudioService:
    """TTS (gTTS) und STT (OpenAI Whisper) mit GStreamer-Playback/Recording."""

    def __init__(self, tts_lang: str = "de", openai_api_key: str = ""):
        self._tts_lang = tts_lang
        self._openai_api_key = openai_api_key
        self._play_pipeline: Gst.Element | None = None
        self._rec_pipeline: Gst.Pipeline | None = None
        self._rec_path: Path | None = None
        self._current_file: str | None = None
        self._play_rate: float = 1.0
        self._speaking = False
        self._recording = False
        self._lock = threading.Lock()

    # ── Properties ──

    @property
    def tts_lang(self) -> str:
        return self._tts_lang

    @tts_lang.setter
    def tts_lang(self, value: str) -> None:
        self._tts_lang = value

    @property
    def openai_api_key(self) -> str:
        return self._openai_api_key

    @openai_api_key.setter
    def openai_api_key(self, value: str) -> None:
        self._openai_api_key = value

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def stt_available(self) -> bool:
        return bool(self._openai_api_key)

    @property
    def play_rate(self) -> float:
        return self._play_rate

    @play_rate.setter
    def play_rate(self, value: float) -> None:
        self._play_rate = max(0.5, min(2.0, value))
        if self._speaking and self._play_pipeline:
            self._apply_rate()

    def get_position(self) -> float:
        """Aktuelle Wiedergabe-Position in Sekunden."""
        if not self._play_pipeline:
            return 0.0
        ok, pos = self._play_pipeline.query_position(Gst.Format.TIME)
        return pos / Gst.SECOND if ok else 0.0

    def get_duration(self) -> float:
        """Gesamtdauer in Sekunden."""
        if not self._play_pipeline:
            return 0.0
        ok, dur = self._play_pipeline.query_duration(Gst.Format.TIME)
        return dur / Gst.SECOND if ok else 0.0

    def seek_to(self, seconds: float) -> bool:
        """Zu Position springen (Sekunden)."""
        if not self._play_pipeline:
            return False
        pos_ns = int(seconds * Gst.SECOND)
        return self._play_pipeline.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            pos_ns,
        )

    def set_rate(self, rate: float) -> bool:
        """Wiedergabe-Geschwindigkeit ändern."""
        self._play_rate = max(0.5, min(2.0, rate))
        if self._play_pipeline and self._speaking:
            return self._apply_rate()
        return True

    def _apply_rate(self) -> bool:
        """Rate auf laufende Pipeline anwenden."""
        ok, pos = self._play_pipeline.query_position(Gst.Format.TIME)
        if not ok:
            return False
        return self._play_pipeline.seek(
            self._play_rate,
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            Gst.SeekType.SET, pos,
            Gst.SeekType.NONE, 0,
        )

    # ── TTS ──

    def speak(self, text: str, on_done: callable = None, on_error: callable = None) -> None:
        """Text per gTTS synthetisieren und via GStreamer abspielen (threaded)."""
        if self._speaking:
            self.stop_speaking()
            return

        def worker():
            tmp_path = None
            played = False
            try:
                from gtts import gTTS
                import os
                tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
                os.close(tmp_fd)
                tts = gTTS(text=text, lang=self._tts_lang)
                tts.save(tmp_path)
                GLib.idle_add(self._play_file, tmp_path, on_done, on_error)
                played = True
            except Exception as e:
                logger.error("TTS-Fehler: %s", e)
                self._speaking = False
                if on_error:
                    GLib.idle_add(on_error, str(e))
            finally:
                # Temp-Datei aufräumen falls nicht an Player uebergeben
                if not played and tmp_path:
                    try:
                        Path(tmp_path).unlink(missing_ok=True)
                    except OSError:
                        pass

        self._speaking = True
        threading.Thread(target=worker, daemon=True).start()

    def _play_file(self, path: str, on_done: callable = None,
                   on_error: callable = None) -> bool:
        """MP3-Datei via GStreamer playbin abspielen (Main-Thread)."""
        try:
            self._current_file = path
            self._play_pipeline = Gst.ElementFactory.make("playbin", "tts_player")
            self._play_pipeline.set_property("uri", f"file://{path}")

            bus = self._play_pipeline.get_bus()
            bus.add_signal_watch()

            def on_message(_bus, msg):
                if msg.type == Gst.MessageType.EOS:
                    self._cleanup_player()
                    if on_done:
                        GLib.idle_add(on_done)
                elif msg.type == Gst.MessageType.ERROR:
                    err, debug = msg.parse_error()
                    logger.error("GStreamer-Fehler: %s (%s)", err.message, debug)
                    self._cleanup_player()
                    if on_error:
                        GLib.idle_add(on_error, err.message)

            bus.connect("message", on_message)
            self._play_pipeline.set_state(Gst.State.PLAYING)

            # Rate anwenden falls != 1.0
            if self._play_rate != 1.0:
                GLib.timeout_add(50, self._deferred_rate)
        except Exception as e:
            logger.error("Playback-Fehler: %s", e)
            Path(path).unlink(missing_ok=True)
            self._current_file = None
            self._speaking = False
            if on_error:
                on_error(str(e))
        return False  # GLib.idle_add einmalig

    def _deferred_rate(self) -> bool:
        """Rate nach kurzem Delay anwenden (Pipeline muss PLAYING sein)."""
        if self._play_pipeline and self._speaking:
            self._apply_rate()
        return False

    def _cleanup_player(self) -> None:
        """Player-Pipeline stoppen und Temp-Datei löschen."""
        if self._play_pipeline:
            self._play_pipeline.set_state(Gst.State.NULL)
            self._play_pipeline = None
        if self._current_file:
            Path(self._current_file).unlink(missing_ok=True)
            self._current_file = None
        self._speaking = False

    def stop_speaking(self) -> None:
        """Laufende TTS-Wiedergabe stoppen."""
        if self._play_pipeline:
            self._play_pipeline.set_state(Gst.State.NULL)
            self._play_pipeline = None
        if self._current_file:
            Path(self._current_file).unlink(missing_ok=True)
            self._current_file = None
        self._speaking = False

    # ── STT ──

    def start_recording(self) -> None:
        """Mikrofon-Aufnahme starten via GStreamer Pipeline."""
        if self._recording:
            return
        if not self._openai_api_key:
            logger.warning("STT: Kein OpenAI API-Key konfiguriert")
            return

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        import os
        os.close(tmp_fd)
        self._rec_path = Path(tmp_path)

        # Pipeline: autoaudiosrc ! audioconvert ! wavenc ! filesink
        pipeline_str = (
            f"autoaudiosrc ! audioconvert ! audioresample ! "
            f"audio/x-raw,rate=16000,channels=1 ! wavenc ! "
            f"filesink location={tmp_path}"
        )
        try:
            self._rec_pipeline = Gst.parse_launch(pipeline_str)
            self._rec_pipeline.set_state(Gst.State.PLAYING)
            self._recording = True
            logger.info("Aufnahme gestartet: %s", tmp_path)
        except Exception as e:
            logger.error("Aufnahme-Fehler: %s", e)
            self._rec_path.unlink(missing_ok=True)
            self._rec_path = None

    def stop_recording(self, on_result: callable = None,
                       on_error: callable = None) -> None:
        """Aufnahme stoppen und WAV an OpenAI Whisper senden (threaded)."""
        if not self._recording or not self._rec_pipeline:
            return

        # Pipeline stoppen — EOS senden für sauberen WAV-Header
        self._rec_pipeline.send_event(Gst.Event.new_eos())

        # Warten bis EOS verarbeitet
        bus = self._rec_pipeline.get_bus()
        bus.timed_pop_filtered(Gst.CLOCK_TIME_NONE, Gst.MessageType.EOS)

        self._rec_pipeline.set_state(Gst.State.NULL)
        self._rec_pipeline = None
        self._recording = False

        wav_path = self._rec_path
        self._rec_path = None

        if not wav_path or not wav_path.exists():
            if on_error:
                GLib.idle_add(on_error, "Aufnahme-Datei nicht gefunden")
            return

        # Whisper-Transkription im Thread
        def worker():
            try:
                import openai
                client = openai.OpenAI(api_key=self._openai_api_key)
                with open(wav_path, "rb") as f:
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=f,
                        language=self._tts_lang[:2],
                    )
                text = transcript.text.strip()
                logger.info("Whisper-Transkription: %s", text[:80])
                if on_result:
                    GLib.idle_add(on_result, text)
            except Exception as e:
                logger.error("Whisper-Fehler: %s", e)
                if on_error:
                    GLib.idle_add(on_error, str(e))
            finally:
                wav_path.unlink(missing_ok=True)

        threading.Thread(target=worker, daemon=True).start()

    def cancel_recording(self) -> None:
        """Laufende Aufnahme abbrechen ohne Transkription."""
        if self._rec_pipeline:
            self._rec_pipeline.set_state(Gst.State.NULL)
            self._rec_pipeline = None
        self._recording = False
        if self._rec_path:
            self._rec_path.unlink(missing_ok=True)
            self._rec_path = None

    def cleanup(self) -> None:
        """Alle Ressourcen freigeben."""
        self.stop_speaking()
        self.cancel_recording()
