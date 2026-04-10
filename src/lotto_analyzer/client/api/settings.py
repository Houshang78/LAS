"""Settings."""
import httpx
from typing import Optional

from lotto_common.utils.logging_config import get_logger

logger = get_logger("api.settings")


class SettingsMixin:
    """Einstellungen-API Mixin: AI, Crawl, Learning, Preferences."""

    def get_ai_settings(self) -> dict:
        """AI-Konfiguration des Servers abfragen."""
        return self._request("GET", "/settings/ai").json()

    def update_ai_settings(
        self, mode: str | None = None, model: str | None = None,
        api_key: str | None = None, cli_path: str | None = None,
    ) -> dict:
        """AI-Konfiguration des Servers ändern."""
        data = {}
        if mode is not None:
            data["mode"] = mode
        if model is not None:
            data["model"] = model
        if api_key is not None:
            data["api_key"] = api_key
        if cli_path is not None:
            data["cli_path"] = cli_path
        return self._request("PUT", "/settings/ai", json=data).json()

    def get_learning_settings(self) -> dict:
        """Lern-Engine-Einstellungen vom Server."""
        return self._request("GET", "/settings/learning").json()

    def update_learning_settings(self, **kwargs) -> dict:
        """Lern-Engine-Einstellungen auf dem Server ändern."""
        return self._request("PUT", "/settings/learning", json=kwargs).json()

    def get_generation_settings(self) -> dict:
        """Auto-Generierung-Einstellungen vom Server."""
        return self._request("GET", "/settings/generation").json()

    def update_generation_settings(self, **kwargs) -> dict:
        """Auto-Generierung-Einstellungen auf dem Server ändern."""
        return self._request("PUT", "/settings/generation", json=kwargs).json()

    def get_generator_ui_settings(self) -> dict:
        """Generator-UI-Einstellungen (tip_count, strategies) vom Server."""
        return self._request("GET", "/settings/generator-ui").json()

    def update_generator_ui_settings(self, **kwargs) -> dict:
        """Generator-UI-Einstellungen auf dem Server speichern."""
        return self._request("PUT", "/settings/generator-ui", json=kwargs).json()

    # ── DB ──

    def get_preferences(self) -> dict:
        return self._request("GET", "/preferences").json()

    def set_preferences(self, **kwargs) -> dict:
        return self._request("PUT", "/preferences", json=kwargs).json()

    def get_cycle_config(self) -> dict:
        return self._request("GET", "/scheduler/cycle-config").json()

    def update_cycle_config(self, **kwargs) -> dict:
        return self._request("PUT", "/scheduler/cycle-config", json=kwargs).json()

    def firewall_config(self) -> dict:
        return self._request("GET", "/firewall/config").json()

    def firewall_update_config(self, data: dict) -> dict:
        return self._request("PUT", "/firewall/config", json=data).json()

    def firewall_fail2ban_configure(self) -> dict:
        return self._request("POST", "/firewall/fail2ban/configure").json()

    def tls_le_config(self) -> dict:
        """LE-Konfiguration + certbot_available."""
        return self._request("GET", "/tls/letsencrypt/config").json()

    def tls_le_update_config(self, data: dict) -> dict:
        """LE-Konfiguration aktualisieren."""
        return self._request("PUT", "/tls/letsencrypt/config", json=data).json()

