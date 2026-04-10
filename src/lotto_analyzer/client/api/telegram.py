"""Telegram."""
import httpx
from typing import Optional

from lotto_common.utils.logging_config import get_logger

logger = get_logger("api.telegram")


class TelegramMixin:
    """Telegram-API Mixin: Bot-Status, Nachrichten, QR-Login."""

    def telegram_status(self) -> dict:
        """Telegram-Bot Status."""
        return self._request("GET", "/telegram/status").json()

    def telegram_messages(self, limit: int = 50) -> list[dict]:
        """Telegram-Nachrichten-Log abrufen."""
        return self._request(
            "GET", "/telegram/messages", params={"limit": limit},
        ).json().get("messages", [])

    def telegram_send(self, text: str, chat_id: int | None = None) -> dict:
        """Telegram-Nachricht senden."""
        payload: dict = {"text": text}
        if chat_id:
            payload["chat_id"] = chat_id
        return self._request("POST", "/telegram/send", json=payload).json()

    def telegram_update_config(self, **kwargs) -> dict:
        """Telegram-Konfiguration aktualisieren."""
        return self._request("PUT", "/telegram/config", json=kwargs).json()

    def telegram_connect(self) -> dict:
        """Telegram-Bot starten (Connect)."""
        return self._request("POST", "/telegram/connect").json()

    def telegram_disconnect(self) -> dict:
        """Telegram-Bot stoppen (Disconnect)."""
        return self._request("POST", "/telegram/disconnect").json()

    def telegram_bot_link(self) -> dict:
        """Bot-Link (t.me/BOT) für QR-Code."""
        return self._request("GET", "/telegram/bot-link").json()

    def telegram_qr_start(
        self, api_id: int, api_hash: str,
        session_name: str = "lotto_telegram",
    ) -> dict:
        """QR-Code-Login starten (Telethon)."""
        return self._request("POST", "/telegram/qr-start", json={
            "api_id": api_id,
            "api_hash": api_hash,
            "session_name": session_name,
        }).json()

    def telegram_qr_status(self) -> dict:
        """QR-Login Status abfragen."""
        return self._request("GET", "/telegram/qr-status").json()

    def telegram_qr_cancel(self) -> dict:
        """QR-Login abbrechen."""
        return self._request("POST", "/telegram/qr-cancel").json()

    # ── Zyklus-Berichte ──

    def send_report_telegram(self, report_id: str) -> dict:
        """Bericht per Telegram senden."""
        return self._request("POST", f"/reports/{report_id}/send-telegram").json()

    def send_activity_log_telegram(self) -> dict:
        """Aktivitätsprotokoll per Telegram senden."""
        resp = self._request("POST", "/activity-log/send-telegram")
        return resp.json()

    # ── Admin-Endpunkte ──

    def admin_list_telegram_bots(self) -> list[dict]:
        return self._request("GET", "/admin/telegram-bots").json()

    def admin_set_telegram_bot(
        self, user_id: int, bot_token: str, chat_id: int | None = None,
    ) -> dict:
        return self._request(
            "POST", f"/admin/telegram-bots/{user_id}",
            json={"bot_token": bot_token, "chat_id": chat_id},
        ).json()

    def admin_delete_telegram_bot(self, user_id: int) -> dict:
        return self._request("DELETE", f"/admin/telegram-bots/{user_id}").json()

    def admin_toggle_telegram_bot(self, user_id: int, active: bool) -> dict:
        return self._request(
            "POST", f"/admin/telegram-bots/{user_id}/toggle",
            json={"active": active},
        ).json()

    def admin_get_telegram_log(self, user_id: int, limit: int = 100) -> list[str]:
        return self._request(
            "GET", f"/admin/telegram-bots/{user_id}/log",
            params={"limit": limit},
        ).json()

    # ── Firewall / Audit ──

