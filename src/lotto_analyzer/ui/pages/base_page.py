"""BasePage — Gemeinsame Basisklasse für alle UI-Seiten.

Bietet zentrales Management für:
- Timer (GLib.timeout_add) mit automatischem Cleanup
- Threading (Lock, Cancel-Event)
- API-Client, GameType, UserRole Verwaltung
- Readonly-Schutz
"""

import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import GameType, get_config
from lotto_common.models.user import Role

logger = get_logger("base_page")


class BasePage(Gtk.Box):
    """Basisklasse für alle UI-Seiten mit Timer/Thread/Lock Management."""

    def __init__(
        self,
        config_manager,
        db=None,
        app_mode: str = "client",
        api_client=None,
        app_db=None,
        backtest_db=None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.config_manager = config_manager
        self.db = db
        self.app_mode = app_mode
        self.api_client = api_client
        self.app_db = app_db
        self.backtest_db = backtest_db

        # Timer-Verwaltung
        self._timers: list[int] = []

        # Thread-Safety
        self._op_lock = threading.Lock()
        self._cancel_event = threading.Event()

        # Benutzerrolle
        self._user_role: str = ""
        self._readonly_buttons: list[Gtk.Widget] = []

        # Stale-Check: letzter Refresh-Zeitpunkt
        self._last_refresh: float = 0.0
        self._refresh_interval: float = 300.0  # 5 Minuten

    # ── Timer-Verwaltung ──

    def add_timer(self, interval_seconds: int, callback, *args) -> int:
        """Timer registrieren — wird bei cleanup() automatisch entfernt.

        Returns: Timer-ID (kann für manuelles Entfernen genutzt werden)
        """
        if args:
            timer_id = GLib.timeout_add_seconds(interval_seconds, callback, *args)
        else:
            timer_id = GLib.timeout_add_seconds(interval_seconds, callback)
        self._timers.append(timer_id)
        return timer_id

    def add_timer_ms(self, interval_ms: int, callback, *args) -> int:
        """Timer in Millisekunden registrieren."""
        if args:
            timer_id = GLib.timeout_add(interval_ms, callback, *args)
        else:
            timer_id = GLib.timeout_add(interval_ms, callback)
        self._timers.append(timer_id)
        return timer_id

    def remove_timer(self, timer_id: int) -> None:
        """Einzelnen Timer entfernen."""
        if timer_id and timer_id in self._timers:
            try:
                GLib.source_remove(timer_id)
            except Exception as e:
                logger.debug(f"Timer {timer_id} entfernen fehlgeschlagen: {e}")
            self._timers.remove(timer_id)

    # ── Thread-Safety ──

    def start_operation(self, flag_name: str = "_busy") -> bool:
        """Operation starten mit Lock-Schutz. Returns True wenn erfolgreich.

        Beispiel:
            if not self.start_operation("_generating"):
                return  # Bereits aktiv
            try:
                ...
            finally:
                self.end_operation("_generating")
        """
        with self._op_lock:
            if getattr(self, flag_name, False):
                return False
            setattr(self, flag_name, True)
            return True

    def end_operation(self, flag_name: str = "_busy") -> None:
        """Operation beenden."""
        with self._op_lock:
            setattr(self, flag_name, False)

    # ── Benutzerrolle ──

    @property
    def _is_readonly(self) -> bool:
        """Prüft ob der Benutzer nur Lesezugriff hat."""
        return self._user_role.lower() == "readonly"

    def set_user_role(self, role: str) -> None:
        """Benutzerrolle setzen und registrierte Buttons einschraenken."""
        self._user_role = role
        if self._is_readonly:
            for btn in self._readonly_buttons:
                btn.set_sensitive(False)
                btn.set_tooltip_text(_("Nur Lesezugriff — keine Berechtigung"))

    def register_readonly_button(self, button: Gtk.Widget) -> None:
        """Button registrieren der bei READONLY deaktiviert werden soll."""
        self._readonly_buttons.append(button)

    # ── Stale-Check ──

    def is_stale(self) -> bool:
        """Prüft ob Daten veraltet sind (aelter als _refresh_interval)."""
        return (time.monotonic() - self._last_refresh) > self._refresh_interval

    def mark_refreshed(self) -> None:
        """Markiert die Seite als gerade aktualisiert."""
        self._last_refresh = time.monotonic()

    # ── API-Client ──

    def set_api_client(self, client) -> None:
        """API-Client setzen. Markiert Seite als stale (Daten veraltet).

        WICHTIG: Kein refresh() hier aufrufen! Das Window ruft refresh()
        nur für die aktive Seite auf. Lazy-Loading: Daten werden erst
        beim Tab-Wechsel geladen.
        """
        self.api_client = client
        self._last_refresh = 0.0  # Als stale markieren → nächster Tab-Wechsel lädt

    # ── WebSocket Task-Polling ──

    _ws_task_callbacks: dict  # task_id → callback

    def ws_watch_task(self, task_id: str, callback) -> None:
        """Watch a task via WebSocket. Falls back to polling if WS unavailable.

        callback(data: dict) is called on GTK main thread when task updates.
        data contains: task_id, status, progress, result, error.
        """
        if not hasattr(self, "_ws_task_callbacks"):
            self._ws_task_callbacks = {}
            # Register WS listener once
            try:
                from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
                ui_ws_manager.on("task_update", self._on_ws_task_event)
            except Exception:
                pass
        self._ws_task_callbacks[task_id] = callback

    def ws_unwatch_task(self, task_id: str) -> None:
        """Stop watching a task."""
        if hasattr(self, "_ws_task_callbacks"):
            self._ws_task_callbacks.pop(task_id, None)

    def _on_ws_task_event(self, data: dict) -> bool:
        """Handle task_update WS event — dispatch to registered callbacks."""
        if not hasattr(self, "_ws_task_callbacks"):
            return False
        task_id = data.get("id", "")
        cb = self._ws_task_callbacks.get(task_id)
        if cb:
            try:
                cb(data)
            except Exception as e:
                logger.debug(f"WS task callback error: {e}")
            # Remove if terminal
            status = data.get("status", "")
            if status in ("completed", "failed", "cancelled"):
                self._ws_task_callbacks.pop(task_id, None)
        return False  # GLib.idle_add: don't repeat

    def poll_task(self, task_id: str, callback, interval: int = 3) -> None:
        """Poll task status with WS upgrade. Hybrid: WS if available, else timer.

        callback(data: dict) called with task status dict.
        Automatically stops when task reaches terminal state.
        """
        # Register WS watcher
        self.ws_watch_task(task_id, callback)

        # Also start polling as fallback
        def _poll_tick():
            if self._cancel_event.is_set():
                return False
            if not self.api_client:
                return False
            try:
                task = self.api_client.get_task(task_id)
                if task:
                    callback(task)
                    status = task.get("status", "")
                    if status in ("completed", "failed", "cancelled"):
                        self.ws_unwatch_task(task_id)
                        return False  # Stop polling
            except Exception as e:
                logger.debug(f"Task poll error: {e}")
            return True  # Continue polling

        self.add_timer(interval, _poll_tick)

    # ── Cleanup ──

    def cleanup(self) -> None:
        """Alle Timer entfernen und Cancel-Event setzen.

        Wird von Window bei Seitenwechsel und beim Schliessen aufgerufen.
        Unterklassen koennen ueberschreiben (super().cleanup() aufrufen!).
        """
        # Alle registrierten Timer entfernen
        for timer_id in list(self._timers):
            try:
                GLib.source_remove(timer_id)
            except Exception as e:
                logger.debug(f"Timer {timer_id} cleanup fehlgeschlagen: {e}")
        self._timers.clear()

        # WS task watchers entfernen
        if hasattr(self, "_ws_task_callbacks"):
            self._ws_task_callbacks.clear()
            try:
                from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
                ui_ws_manager.off("task_update", self._on_ws_task_event)
            except Exception:
                pass

        # Laufende Threads signalisieren
        self._cancel_event.set()
