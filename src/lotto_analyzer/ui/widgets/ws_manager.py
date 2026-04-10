"""Centralized WebSocket manager for GTK UI.

Maintains a single WebSocket connection and dispatches events
to registered page callbacks. Falls back gracefully if WS unavailable.
"""

from typing import Callable

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib

from lotto_common.utils.logging_config import get_logger

logger = get_logger("ws_manager")


class UIWebSocketManager:
    """Single WS connection shared across all UI pages.

    Usage:
        ws_mgr = UIWebSocketManager()
        ws_mgr.connect_client(api_client)
        ws_mgr.on("task_update", my_callback)
        ws_mgr.off("task_update", my_callback)  # on cleanup
    """

    def __init__(self):
        self._ws = None
        self._callbacks: dict[str, list[Callable]] = {}
        self._connected = False

    def connect_client(self, api_client) -> bool:
        """Connect to server WebSocket using api_client credentials.

        Returns True if connection was established.
        """
        if self._connected:
            return True
        if not api_client or not hasattr(api_client, "_token") or not api_client._token:
            return False
        try:
            from lotto_analyzer.client.ws_client import WebSocketClient
            self._ws = WebSocketClient(api_client.base_url, api_client._token)
            self._ws.on("*", self._dispatch)
            self._ws.start()
            self._connected = True
            logger.info("UI WebSocket connected")
            return True
        except Exception as e:
            logger.debug(f"WebSocket not available: {e}")
            return False

    def disconnect(self) -> None:
        """Stop WebSocket connection."""
        if self._ws:
            self._ws.stop()
            self._ws = None
        self._connected = False

    def on(self, event_type: str, callback: Callable) -> None:
        """Register callback for event type (task_update, scheduler_status, etc.).

        Callback receives event data dict. Called on GTK main thread via GLib.idle_add.
        """
        self._callbacks.setdefault(event_type, [])
        if callback not in self._callbacks[event_type]:
            self._callbacks[event_type].append(callback)

    def off(self, event_type: str, callback: Callable) -> None:
        """Unregister callback (call in page cleanup)."""
        cbs = self._callbacks.get(event_type, [])
        if callback in cbs:
            cbs.remove(callback)

    def off_all(self, callback: Callable) -> None:
        """Remove callback from ALL event types (convenience for cleanup)."""
        for cbs in self._callbacks.values():
            if callback in cbs:
                cbs.remove(callback)

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    def _dispatch(self, event: dict) -> None:
        """Dispatch WS event to registered callbacks (runs on WS thread)."""
        event_type = event.get("type", "")
        data = event.get("data", {})

        # Dispatch to type-specific listeners
        for cb in self._callbacks.get(event_type, []):
            GLib.idle_add(cb, data)

        # Dispatch to wildcard listeners
        for cb in self._callbacks.get("*", []):
            GLib.idle_add(cb, event)


# Singleton instance — shared across all pages
ui_ws_manager = UIWebSocketManager()
