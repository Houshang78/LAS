"""Auth."""
import httpx
from typing import Optional

from lotto_common.utils.logging_config import get_logger

logger = get_logger("api.auth")


class AuthMixin:
    """Auth-API Mixin: Login, Token, 2FA, SSH-Key, Zertifikat."""

    def _auth_headers(self) -> dict:
        """Aktuelle Auth-Header (Bearer Token oder X-API-Key)."""
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    def _try_refresh_token(self) -> Optional[str]:
        """Token erneuern (intern, ohne raise_for_status)."""
        try:
            resp = self._client.post(
                "/auth/refresh",
                headers=self._auth_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                self._token = data.get("token")
                logger.info("Token automatisch erneuert")
                return self._token
            logger.debug(f"Token-Refresh abgelehnt: HTTP {resp.status_code}")
        except httpx.ConnectError:
            logger.debug("Token-Refresh: Server nicht erreichbar")
        except Exception as e:
            logger.warning(f"Token-Refresh fehlgeschlagen: {e}")
        self._token = None
        return None

    def _try_relogin(self) -> Optional[str]:
        """Automatisch neu einloggen (localhost-trust oder gespeicherte Credentials)."""
        try:
            import getpass
            system_user = getpass.getuser()
            resp = self._client.post(
                "/auth/login-local", params={"username": system_user},
            )
            if resp.status_code == 200:
                data = resp.json()
                self._token = data.get("token")
                logger.info(f"Auto-Relogin erfolgreich: {data.get('username', system_user)}")
                return self._token
            logger.debug(f"Auto-Relogin abgelehnt: HTTP {resp.status_code}")
        except Exception as e:
            logger.debug(f"Auto-Relogin fehlgeschlagen: {e}")
        return None

    # ── Authentifizierung ──

    def login(self, username: str, password: str | None = None, *, api_key: str | None = None) -> dict:
        """Login — Token speichern oder 2FA-Challenge zurückgeben.

        Genau eins von password / api_key muss angegeben sein.
        """
        payload = {"username": username}
        if api_key:
            payload["api_key"] = api_key
        else:
            payload["password"] = password
        resp = self._client.post("/auth/login", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "2fa_required":
            logger.info(f"2FA erforderlich für: {username}")
            return data
        self._token = data.get("token")
        logger.info(f"Login erfolgreich: {username}")
        return data

    def login_local(self, username: str) -> dict:
        """Localhost-Trust-Login — kein Passwort noetig."""
        resp = self._client.post("/auth/login-local", params={"username": username})
        resp.raise_for_status()
        data = resp.json()
        self._token = data.get("token")
        logger.info(f"Localhost-Trust-Login erfolgreich: {data.get('username')}")
        return data

    def verify_2fa(self, challenge_id: str, code: str) -> dict:
        """2FA-Code prüfen und Token speichern."""
        resp = self._client.post(
            "/auth/verify-2fa",
            json={"challenge_id": challenge_id, "code": code},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data.get("token")
        logger.info("2FA-Verifizierung erfolgreich")
        return data

    def refresh_token(self) -> Optional[str]:
        """Token erneuern."""
        if not self._token:
            return None
        try:
            resp = self._request("POST", "/auth/refresh")
            data = resp.json()
            self._token = data.get("token")
            return self._token
        except httpx.HTTPStatusError:
            self._token = None
            return None

    def logout(self) -> None:
        """Abmelden und Token löschen."""
        if self._token:
            try:
                self._request("POST", "/auth/logout")
            except Exception as e:
                logger.debug(f"Logout-Request fehlgeschlagen: {e}")
            self._token = None

    @property
    def is_authenticated(self) -> bool:
        return self._token is not None

    # ── Password Reset ──

    def request_password_reset(self, username: str) -> dict:
        """Step 1: Request password reset — triggers Telegram 2FA."""
        resp = self._client.post(
            "/auth/reset-password/request",
            json={"username": username},
        )
        resp.raise_for_status()
        return resp.json()

    def confirm_password_reset(
        self, challenge_id: str, code: str, new_password: str,
    ) -> dict:
        """Step 2: Confirm reset with 2FA code + new password."""
        resp = self._client.post(
            "/auth/reset-password/confirm",
            json={
                "challenge_id": challenge_id,
                "code": code,
                "new_password": new_password,
            },
        )
        resp.raise_for_status()
        return resp.json()

    # ── Bestehende Endpunkte ──

    def login_ssh_key(self, username: str, private_key_path: str) -> dict:
        """SSH-Key-Login: Challenge-Response automatisch durchfuehren."""
        import base64
        from pathlib import Path
        from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_ssh_private_key
        from cryptography.hazmat.primitives.asymmetric import rsa, ed25519, padding
        from cryptography.hazmat.primitives import hashes

        # Private Key laden
        key_data = Path(private_key_path).expanduser().read_bytes()
        try:
            priv_key = load_ssh_private_key(key_data, password=None)
        except Exception as e:
            logger.debug(f"SSH-Key als OpenSSH-Format fehlgeschlagen, versuche PEM: {e}")
            priv_key = load_pem_private_key(key_data, password=None)

        # Fingerprint berechnen (aus Public Key)
        from lotto_common.utils.crypto import compute_key_fingerprint
        fingerprint = compute_key_fingerprint(priv_key.public_key())

        # 1. Challenge anfordern
        resp = self._client.post("/auth/key-challenge", json={
            "username": username,
            "key_fingerprint": fingerprint,
        })
        resp.raise_for_status()
        challenge = resp.json()

        # 2. Nonce signieren
        nonce = base64.b64decode(challenge["nonce"])
        if isinstance(priv_key, rsa.RSAPrivateKey):
            signature = priv_key.sign(nonce, padding.PKCS1v15(), hashes.SHA256())
        elif isinstance(priv_key, ed25519.Ed25519PrivateKey):
            signature = priv_key.sign(nonce)
        else:
            raise ValueError(f"Nicht unterstützter Key-Typ: {type(priv_key).__name__}")

        # 3. Signatur senden
        resp = self._client.post("/auth/key-verify", json={
            "challenge_id": challenge["challenge_id"],
            "signature": base64.b64encode(signature).decode(),
        })
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "2fa_required":
            logger.info(f"2FA erforderlich für: {username}")
            return data
        self._token = data.get("token")
        logger.info(f"SSH-Key-Login erfolgreich: {username}")
        return data

    def login_certificate(self, username: str, cert_path: str, key_path: str) -> dict:
        """Zertifikat-Login: Challenge-Response automatisch durchfuehren."""
        import base64
        from pathlib import Path
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric import rsa, padding
        from cryptography.hazmat.primitives import hashes

        cert_pem = Path(cert_path).expanduser().read_text()
        priv_key = load_pem_private_key(
            Path(key_path).expanduser().read_bytes(), password=None,
        )

        # 1. Challenge anfordern (mit Zertifikat)
        resp = self._client.post("/auth/cert-challenge", json={
            "username": username,
            "certificate_pem": cert_pem,
        })
        resp.raise_for_status()
        challenge = resp.json()

        # 2. Nonce signieren
        nonce = base64.b64decode(challenge["nonce"])
        if isinstance(priv_key, rsa.RSAPrivateKey):
            signature = priv_key.sign(nonce, padding.PKCS1v15(), hashes.SHA256())
        else:
            raise ValueError(f"Nicht unterstützter Key-Typ: {type(priv_key).__name__}")

        # 3. Signatur senden
        resp = self._client.post("/auth/cert-verify", json={
            "challenge_id": challenge["challenge_id"],
            "signature": base64.b64encode(signature).decode(),
        })
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "2fa_required":
            logger.info(f"2FA erforderlich für: {username}")
            return data
        self._token = data.get("token")
        logger.info(f"Zertifikat-Login erfolgreich: {username}")
        return data

    # ── SSH-Key & Zertifikat Admin ──

