"""Verbindungsprofil-Verwaltung für den Client."""

from pathlib import Path
from typing import Optional

from lotto_analyzer.client.api_client import APIClient
from lotto_analyzer.client.ssh_tunnel import SSHTunnel
from lotto_common.config import ConfigManager
from lotto_common.models.ai_config import ServerConfig
from lotto_common.models.user import ConnectionProfile
from lotto_common.utils.logging_config import get_logger

logger = get_logger("profile_manager")


class ProfileManager:
    """Verwaltet Verbindungsprofile und aktive Verbindungen."""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self._tunnel: Optional[SSHTunnel] = None
        self._client: Optional[APIClient] = None
        self._active_profile: Optional[ConnectionProfile] = None

    @property
    def profiles(self) -> list[ConnectionProfile]:
        return self.config_manager.config.connection_profiles

    @property
    def active_profile(self) -> Optional[ConnectionProfile]:
        return self._active_profile

    @property
    def client(self) -> Optional[APIClient]:
        return self._client

    @property
    def tunnel(self) -> Optional[SSHTunnel]:
        return self._tunnel

    def get_default_profile(self) -> Optional[ConnectionProfile]:
        for p in self.profiles:
            if p.is_default:
                return p
        return self.profiles[0] if self.profiles else None

    def get_profile(self, name: str) -> Optional[ConnectionProfile]:
        for p in self.profiles:
            if p.name == name:
                return p
        return None

    def add_profile(self, profile: ConnectionProfile) -> None:
        if profile.is_default:
            for p in self.profiles:
                p.is_default = False
        self.config_manager.config.connection_profiles.append(profile)
        self.config_manager.save()

    def update_profile(self, name: str, profile: ConnectionProfile) -> bool:
        for i, p in enumerate(self.profiles):
            if p.name == name:
                if profile.is_default:
                    for other in self.profiles:
                        other.is_default = False
                self.config_manager.config.connection_profiles[i] = profile
                self.config_manager.save()
                return True
        return False

    def delete_profile(self, name: str) -> bool:
        profiles = self.config_manager.config.connection_profiles
        for i, p in enumerate(profiles):
            if p.name == name:
                profiles.pop(i)
                self.config_manager.save()
                return True
        return False

    def connect(self, profile: ConnectionProfile) -> tuple[bool, str]:
        """Verbindung mit Profil herstellen (SSH-Tunnel + APIClient)."""
        # Alte Verbindung trennen
        self.disconnect()

        # SSH-Tunnel starten wenn konfiguriert
        host = profile.host
        port = profile.port
        if profile.use_ssh:
            if profile.ssh_key_path and not Path(profile.ssh_key_path).exists():
                logger.warning(f"SSH-Key nicht gefunden: {profile.ssh_key_path}")
            self._tunnel = SSHTunnel(
                ssh_host=profile.ssh_host or profile.host,
                ssh_user=profile.ssh_user,
                remote_port=profile.port,
                local_port=profile.port,
                ssh_port=profile.ssh_port,
                ssh_key_path=profile.ssh_key_path,
            )
            if not self._tunnel.start():
                self._tunnel = None
                return False, "SSH-Tunnel konnte nicht gestartet werden"
            host = "localhost"
            port = profile.port

        # API-Client erstellen
        server_config = ServerConfig(
            host=host,
            port=port,
            api_key=profile.api_key,
            use_https=profile.use_https,
        )
        self._client = APIClient(server_config)
        self._active_profile = profile

        # Verbindung testen
        ok, msg = self._client.test_connection()
        if not ok:
            self.disconnect()
            return False, msg

        logger.info(f"Verbunden mit Profil: {profile.name}")
        return True, msg

    def disconnect(self) -> None:
        """Aktive Verbindung und Tunnel trennen."""
        if self._client:
            self._client.close()
            self._client = None
        if self._tunnel:
            self._tunnel.stop()
            self._tunnel = None
        self._active_profile = None

    def migrate_legacy_config(self) -> None:
        """Alte Server-Config in 'Standard'-Profil migrieren."""
        if self.profiles:
            return  # Bereits Profile vorhanden

        server = self.config_manager.config.server
        if server.host == "localhost" and not server.api_key:
            return  # Default-Config, keine Migration noetig

        profile = ConnectionProfile(
            name="Standard",
            host=server.host,
            port=server.port,
            use_https=server.use_https,
            api_key=server.api_key,
            is_default=True,
        )
        self.add_profile(profile)
        logger.info("Legacy-Config zu Profil 'Standard' migriert")
