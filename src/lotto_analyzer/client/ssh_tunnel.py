"""SSH-Tunnel Manager: Verschlüsselte Verbindung zum Server."""

import subprocess
import threading
import time
from typing import Optional

from lotto_common.utils.logging_config import get_logger

logger = get_logger("ssh_tunnel")


class SSHTunnel:
    """SSH-Tunnel via subprocess (ssh -N -L)."""

    def __init__(
        self,
        ssh_host: str,
        ssh_user: str,
        remote_port: int = 8049,
        local_port: int = 8049,
        ssh_port: int = 22,
        ssh_key_path: str = "",
    ):
        self.ssh_host = ssh_host
        self.ssh_user = ssh_user
        self.remote_port = remote_port
        self.local_port = local_port
        self.ssh_port = ssh_port
        self.ssh_key_path = ssh_key_path
        self._process: Optional[subprocess.Popen] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> bool:
        """SSH-Tunnel starten."""
        if self.is_alive:
            logger.info("Tunnel läuft bereits")
            return True

        cmd = [
            "ssh", "-N", "-L",
            f"{self.local_port}:localhost:{self.remote_port}",
            f"{self.ssh_user}@{self.ssh_host}",
            "-p", str(self.ssh_port),
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ConnectTimeout=10",
        ]
        if self.ssh_key_path:
            cmd.extend(["-i", self.ssh_key_path])

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            # Kurz warten um sicherzustellen dass der Tunnel steht
            time.sleep(1)
            if self._process.poll() is not None:
                stderr = self._process.stderr.read().decode() if self._process.stderr else ""
                logger.error(f"Tunnel-Start fehlgeschlagen: {stderr}")
                return False

            logger.info(
                f"SSH-Tunnel gestartet: localhost:{self.local_port} → "
                f"{self.ssh_host}:{self.remote_port}"
            )

            # Monitor-Thread starten
            self._stop_event.clear()
            self._monitor_thread = threading.Thread(
                target=self._monitor, daemon=True,
            )
            self._monitor_thread.start()
            return True

        except FileNotFoundError:
            logger.error("ssh nicht gefunden – OpenSSH installiert?")
            return False
        except Exception as e:
            logger.error(f"Tunnel-Fehler: {e}")
            return False

    def stop(self) -> None:
        """SSH-Tunnel beenden."""
        self._stop_event.set()
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            self._process = None
            logger.info("SSH-Tunnel gestoppt")

    @property
    def is_alive(self) -> bool:
        """Prüft ob der Tunnel-Prozess läuft."""
        return self._process is not None and self._process.poll() is None

    def _monitor(self) -> None:
        """Monitor-Thread: Prüft regelmäßig ob der Tunnel noch steht. Auto-Reconnect."""
        reconnect_attempts = 0
        max_reconnects = 5

        while not self._stop_event.is_set():
            if self._process and self._process.poll() is not None:
                logger.warning("SSH-Tunnel unerwartet beendet")
                self._process = None

                # Auto-Reconnect
                if reconnect_attempts < max_reconnects:
                    reconnect_attempts += 1
                    wait = min(reconnect_attempts * 5, 30)
                    logger.info(f"Reconnect in {wait}s (Versuch {reconnect_attempts}/{max_reconnects})")
                    self._stop_event.wait(wait)
                    if self._stop_event.is_set():
                        break
                    if self.start():
                        reconnect_attempts = 0
                        logger.info("SSH-Tunnel wiederhergestellt")
                        continue
                else:
                    logger.error(f"SSH-Tunnel: {max_reconnects} Reconnect-Versuche fehlgeschlagen")
                    break
            else:
                reconnect_attempts = 0  # Reset bei stabilem Tunnel

            self._stop_event.wait(5)
