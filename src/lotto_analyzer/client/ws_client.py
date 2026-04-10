"""WebSocket client for receiving live updates from server.

Connects to ws(s)://server/ws?token=... and dispatches events
to registered callbacks. Falls back to polling if WebSocket fails.
"""

import json
import threading
from typing import Callable, Optional

from lotto_common.utils.logging_config import get_logger

logger = get_logger("ws_client")


class WebSocketClient:
    """Listens for server push events via WebSocket."""

    def __init__(self, base_url: str, token: str):
        # Convert https:// to wss:// or http:// to ws://
        ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://")
        self._url = f"{ws_url}/ws?token={token}"
        self._callbacks: dict[str, list[Callable]] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._ws = None

    def on(self, event_type: str, callback: Callable) -> None:
        """Register callback for an event type (task_update, draw_update, etc.)."""
        self._callbacks.setdefault(event_type, []).append(callback)

    def start(self) -> None:
        """Start listening in background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop listening."""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _listen(self) -> None:
        """WebSocket listen loop with auto-reconnect."""
        import time
        while self._running:
            try:
                import websocket
                self._ws = websocket.WebSocket(sslopt={"cert_reqs": 0})
                self._ws.connect(self._url)
                logger.info("WebSocket connected")

                while self._running:
                    try:
                        raw = self._ws.recv()
                        if not raw:
                            break
                        event = json.loads(raw)
                        self._dispatch(event)
                    except Exception as e:
                        if self._running:
                            logger.debug(f"WebSocket recv error: {e}")
                        break

            except ImportError:
                logger.info("websocket-client not installed — WebSocket disabled")
                self._running = False
                return
            except Exception as e:
                if self._running:
                    logger.debug(f"WebSocket connection failed: {e}")
                    time.sleep(5)  # Reconnect delay

        logger.info("WebSocket listener stopped")

    def _dispatch(self, event: dict) -> None:
        """Dispatch event to registered callbacks."""
        event_type = event.get("type", "")
        for cb in self._callbacks.get(event_type, []):
            try:
                cb(event.get("data", {}))
            except Exception as e:
                logger.debug(f"WebSocket callback error for {event_type}: {e}")
        # Also dispatch to wildcard listeners
        for cb in self._callbacks.get("*", []):
            try:
                cb(event)
            except Exception:
                pass

    @property
    def is_connected(self) -> bool:
        return self._running and self._ws is not None
