"""Admin."""
import httpx
from typing import Optional

from lotto_common.utils.logging_config import get_logger

logger = get_logger("api.admin")


class AdminMixin:
    """Admin-API Mixin: Benutzerverwaltung, Audit, Firewall."""

    def list_users(self) -> list[dict]:
        return self._request("GET", "/admin/users").json()

    def create_user(
        self, username: str, password: str, role: str = "user",
        permissions: list[str] | None = None,
        ssh_public_keys: list[str] | None = None,
        create_linux_account: bool = False,
    ) -> dict:
        payload = {
            "username": username,
            "password": password,
            "role": role,
        }
        if permissions is not None:
            payload["permissions"] = permissions
        if ssh_public_keys:
            payload["ssh_public_keys"] = ssh_public_keys
        if create_linux_account:
            payload["create_linux_account"] = True
        return self._request("POST", "/admin/users", json=payload).json()

    def update_user(self, user_id: int, **kwargs) -> dict:
        return self._request("PUT", f"/admin/users/{user_id}", json=kwargs).json()

    def delete_user(self, user_id: int) -> dict:
        return self._request("DELETE", f"/admin/users/{user_id}").json()

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        return self._request("GET", "/admin/audit-log", params={"limit": limit}).json()

    def delete_audit_entry(self, entry_id: int) -> dict:
        return self._request("DELETE", f"/admin/audit-log/{entry_id}").json()

    def rotate_api_key(self) -> dict:
        return self._request("POST", "/admin/api-keys/rotate").json()

    def list_api_keys(self) -> list[dict]:
        return self._request("GET", "/admin/api-keys").json()

    # ── SSH-Key & Zertifikat Auth ──

    def add_user_key(self, user_id: int, public_key: str, description: str = "") -> dict:
        return self._request("POST", f"/admin/users/{user_id}/keys", json={
            "public_key": public_key,
            "description": description,
        }).json()

    def list_user_keys(self, user_id: int) -> list[dict]:
        return self._request("GET", f"/admin/users/{user_id}/keys").json()

    def remove_user_key(self, fingerprint: str) -> dict:
        return self._request("DELETE", f"/admin/keys/{fingerprint}").json()

    def issue_certificate(self, user_id: int, days_valid: int = 365) -> dict:
        return self._request("POST", f"/admin/users/{user_id}/certificates", json={
            "days_valid": days_valid,
        }).json()

    def list_certificates(self) -> list[dict]:
        return self._request("GET", "/admin/certificates").json()

    def revoke_certificate(self, serial: str) -> dict:
        return self._request("POST", f"/admin/certificates/{serial}/revoke").json()

    # ── Firewall ──

    def admin_ban_user(self, user_id: int) -> dict:
        return self._request("POST", f"/admin/users/{user_id}/ban").json()

    def admin_disconnect_user(self, user_id: int) -> dict:
        return self._request("POST", f"/admin/users/{user_id}/disconnect").json()

    def admin_deactivate_user(self, user_id: int) -> dict:
        return self._request("POST", f"/admin/users/{user_id}/deactivate").json()

    def admin_activate_user(self, user_id: int) -> dict:
        return self._request("POST", f"/admin/users/{user_id}/activate").json()

    # ── Per-User Telegram-Bots (Admin) ──

    def firewall_audit_settings(self) -> dict:
        """Audit-Check-Einstellungen abrufen."""
        return self._request("GET", "/firewall/audit-settings").json()

    def firewall_set_audit_settings(self, settings: dict) -> dict:
        """Audit-Check-Einstellungen speichern."""
        return self._request("PUT", "/firewall/audit-settings", json=settings).json()

    def firewall_system_audit(self) -> dict:
        """System-Sicherheitsaudit durchfuehren."""
        return self._request("GET", "/firewall/system-audit").json()

    # ── Profile & Change Requests ──

    def get_my_profile(self) -> dict:
        """Own profile data."""
        return self._request("GET", "/profile/me").json()

    def update_my_profile(self, field_name: str, new_value: str) -> dict:
        """Request a profile field change (needs admin approval)."""
        return self._request(
            "PUT", "/profile/me",
            json={"field_name": field_name, "new_value": new_value},
        ).json()

    def get_my_changes(self) -> list[dict]:
        """Own pending change requests."""
        return self._request("GET", "/profile/me/changes").json()

    def get_change_requests(self, status: str = "pending") -> list[dict]:
        """All change requests (admin)."""
        return self._request(
            "GET", "/admin/change-requests",
            params={"status": status},
        ).json()

    def review_change_request(
        self, change_id: int, approved: bool, note: str = "",
    ) -> dict:
        """Approve or reject a change request (admin)."""
        return self._request(
            "PUT", f"/admin/change-requests/{change_id}",
            json={"approved": approved, "note": note},
        ).json()

    # ── Telegram Notification Permissions ──

    def get_telegram_permissions(self) -> dict:
        """Get all users with their telegram notification permissions."""
        return self._request("GET", "/admin/telegram-permissions").json()

    def get_user_telegram_permissions(self, user_id: int) -> dict:
        """Get telegram permissions for a specific user."""
        return self._request("GET", f"/admin/telegram-permissions/{user_id}").json()

    def set_user_telegram_permissions(self, user_id: int, permissions: dict) -> dict:
        """Set telegram notification permissions for a user."""
        return self._request(
            "PUT", f"/admin/telegram-permissions/{user_id}",
            json=permissions,
        ).json()
