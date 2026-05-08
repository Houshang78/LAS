"""REST client: connects GTK4 GUI to lotto-analyzer server."""

import threading
import time
from typing import Optional

import httpx

from lotto_common.models.ai_config import ServerConfig
from lotto_common.utils.logging_config import get_logger
from datetime import date, datetime

# Retry config for transient network errors
MAX_RETRIES = 2
RETRY_DELAY = 1.0  # seconds (linear backoff: 1s, 2s)

logger = get_logger("api_client")



from lotto_analyzer.client.api.auth import AuthMixin
from lotto_analyzer.client.api.settings import SettingsMixin
from lotto_analyzer.client.api.draws import DrawsMixin
from lotto_analyzer.client.api.generation import GenerationMixin
from lotto_analyzer.client.api.ml_training import MlTrainingMixin
from lotto_analyzer.client.api.predictions import PredictionsMixin
from lotto_analyzer.client.api.telegram import TelegramMixin
from lotto_analyzer.client.api.admin import AdminMixin


class APIClient(AuthMixin, SettingsMixin, DrawsMixin, GenerationMixin, MlTrainingMixin, PredictionsMixin, TelegramMixin, AdminMixin):
    """APIClient."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self.base_url = config.base_url
        self._token: Optional[str] = None
        # Lock serializes token refresh — prevents race conditions when
        # multiple threads hit 401 simultaneously
        self._token_lock = threading.Lock()
        self._refreshing = False
        headers = {}
        if config.api_key:
            headers["X-API-Key"] = config.api_key
        # Use cached server cert for verification if available
        verify = self._get_cert_verify_path()
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=config.timeout,
            headers=headers,
            verify=verify,
        )

    @staticmethod
    def _get_cert_verify_path():
        """Get TLS verification setting.

        Self-signed certs (CN=LottoAnalyzer) can't be verified against
        IP addresses, so we use verify=False for those. Only real certs
        (Let's Encrypt etc.) would use actual verification.
        """
        from pathlib import Path
        for base in [
            Path("/etc/lotto-analyzer/tls"),
            Path.home() / ".config" / "lotto-analyzer" / "tls",
        ]:
            cert = base / "server.crt"
            if cert.exists():
                # Check if it's a Let's Encrypt or real CA cert
                try:
                    content = cert.read_text()
                    if "Let's Encrypt" in content or "ISRG" in content:
                        return str(cert)
                except Exception:
                    pass
        # Self-signed or no cert: skip verification
        return False

    def fetch_and_trust_server_cert(self) -> bool:
        """Fetch server's public cert and store in /etc/lotto-analyzer/tls/.

        Falls back to ~/.config/lotto-analyzer/tls/ if /etc not writable.
        Called after first successful connection (Trust on First Use).
        """
        try:
            resp = self._client.get("/tls/public-cert")
            if resp.status_code != 200:
                return False
            cert_pem = resp.text
            if not cert_pem.startswith("-----BEGIN CERTIFICATE"):
                return False

            from pathlib import Path
            # Try system dir first, fallback to user config
            for tls_dir in [
                Path("/etc/lotto-analyzer/tls"),
                Path.home() / ".config" / "lotto-analyzer" / "tls",
            ]:
                try:
                    tls_dir.mkdir(parents=True, exist_ok=True)
                    cert_file = tls_dir / "server.crt"
                    cert_file.write_text(cert_pem)
                    logger.info(f"Server cert stored: {cert_file}")
                    return True
                except PermissionError:
                    continue
            return False
        except Exception as e:
            logger.debug(f"Server cert fetch failed: {e}")
            return False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            pass

    def _token_expires_soon(self) -> bool:
        """Prüft ob JWT-Token in < 60s abläuft."""
        if not self._token:
            return False
        try:
            import base64, json, time
            payload = self._token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)  # Padding
            data = json.loads(base64.urlsafe_b64decode(payload))
            exp = data.get("exp", 0)
            return time.time() > exp - 60
        except Exception:
            return False

    def _ensure_valid_token(self) -> None:
        """Proactively refresh token if it expires soon. Thread-safe."""
        if not self._token or not self._token_expires_soon():
            return
        with self._token_lock:
            # Double-check after acquiring lock (another thread may have refreshed)
            if self._token and self._token_expires_soon():
                logger.debug("Token expires soon — proactive refresh")
                self._try_refresh_token()

    def _handle_401(self) -> bool:
        """Handle 401 by refreshing token or re-logging in. Thread-safe.

        Returns True if a new valid token was obtained.
        """
        with self._token_lock:
            # Another thread may have already refreshed while we waited
            if self._token and not self._token_expires_soon():
                logger.debug("Token already refreshed by another thread")
                return True
            new_token = self._try_refresh_token() if self._token else None
            if not new_token:
                new_token = self._try_relogin()
            return new_token is not None

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Execute request with auth headers and automatic token recovery.

        Token refresh is serialized via lock — concurrent requests wait
        for the refresh to complete instead of triggering parallel refreshes.

        Retry logic: transient network errors (ConnectError, ConnectTimeout,
        ReadTimeout) are retried up to MAX_RETRIES times with linear backoff.
        HTTP errors (4xx/5xx) are NOT retried.
        """
        self._ensure_valid_token()

        headers = kwargs.pop("headers", {})
        headers.update(self._auth_headers())

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self._client.request(method, url, headers=headers, **kwargs)

                if resp.status_code == 401:
                    if self._handle_401():
                        headers.update(self._auth_headers())
                        resp = self._client.request(method, url, headers=headers, **kwargs)

                resp.raise_for_status()
                return resp

            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY * (attempt + 1)
                    logger.warning(
                        f"Network error {method} {url} "
                        f"(attempt {attempt + 1}/{MAX_RETRIES + 1}): {e} "
                        f"— retry in {delay:.0f}s"
                    )
                    time.sleep(delay)
                    continue
                logger.error(
                    f"Network error {method} {url} after "
                    f"{MAX_RETRIES + 1} attempts: {e}"
                )
                raise

            except httpx.HTTPStatusError:
                raise

        raise last_error

    def _json_request(self, method: str, url: str, **kwargs) -> dict:
        """Request ausführen und JSON-Antwort zurückgeben.

        Bei ungültigem JSON wird ein leeres Dict zurückgegeben statt Exception.
        """
        resp = self._request(method, url, **kwargs)
        try:
            return resp.json()
        except (ValueError, Exception):
            logger.warning(f"Ungültige JSON-Antwort von {url}")
            return {}

    def poll_2fa_status(self, challenge_id: str) -> dict:
        """Poll 2FA status (for Telegram approve button).

        Uses _client directly (no auth needed — challenge_id is the auth).
        But we add retry logic for transient network errors.
        """
        try:
            resp = self._client.get(f"/auth/2fa-status/{challenge_id}")
            resp.raise_for_status()
            data = resp.json()
            if data.get("token"):
                with self._token_lock:
                    self._token = data["token"]
                logger.info("2FA approved via Telegram")
            return data
        except (httpx.ConnectError, httpx.ReadTimeout):
            return {"status": "pending", "error": "network"}

    def health(self) -> dict:
        """Server-Health prüfen."""
        resp = self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    # ── D2: Server-side replacements für direkte DB-Calls ──
    # Diese Methoden lösen das Architektur-Problem auf: Pages nutzten
    # vorher self.db.* (lokale SQLite-Query gegen Server-DB → Pfad-
    # Annahme), jetzt sprechen sie über HTTP gegen den Server.

    def get_latest_draw(self, draw_day: str) -> dict | None:
        """GET /draws/latest/{draw_day} — None bei 404."""
        try:
            return self._request("GET", f"/draws/latest/{draw_day}").json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    def get_draw_count(self, draw_day: str) -> int:
        """GET /draws/count/{draw_day} — 0 wenn unbekannt/nicht-erreichbar."""
        try:
            data = self._request("GET", f"/draws/count/{draw_day}").json()
            return int(data.get("count", 0))
        except Exception:
            return 0

    def get_strategy_performance(self, draw_day: str) -> list[dict]:
        """GET /performance/{draw_day} — leere Liste bei Fehler."""
        try:
            data = self._request("GET", f"/performance/{draw_day}").json()
            perf = data.get("performance") or []
            return perf if isinstance(perf, list) else []
        except Exception:
            return []

    def get_cycle_reports(self, draw_day: str | None = None, limit: int = 50) -> list[dict]:
        """GET /reports — alle Cycle-Reports (optional gefiltert)."""
        params: dict = {"limit": int(limit)}
        if draw_day:
            params["draw_day"] = draw_day
        try:
            data = self._request("GET", "/reports", params=params).json()
            rep = data.get("reports") or []
            return rep if isinstance(rep, list) else []
        except Exception:
            return []

    def get_training_runs(self, draw_day: str, limit: int = 20) -> list[dict]:
        """GET /ml/training-history/{draw_day} — leere Liste bei Fehler."""
        try:
            data = self._request(
                "GET", f"/ml/training-history/{draw_day}",
                params={"limit": int(limit)},
            ).json()
            runs = data.get("runs") or data.get("history") or data
            return runs if isinstance(runs, list) else []
        except Exception:
            return []

    # ── D3: User/SSH-Key/Cert-Verwaltung (admin) ──
    # Spiegeln die /admin/users + /admin/keys + /admin/certificates
    # Endpoints. Vorher importierte der Client UserDatabase + key_auth
    # direkt aus dem Server-Modul — Architekturbruch + Sicherheitsrisiko.

    def list_users(self) -> list[dict]:
        """GET /admin/users — alle registrierten User."""
        try:
            return self._request("GET", "/admin/users").json()
        except Exception:
            return []

    def add_user_key(self, user_id: int, public_key: str, description: str = "") -> dict:
        """POST /admin/users/{user_id}/keys — SSH-Key registrieren.

        Server validiert den Key (parse_public_key), berechnet Fingerprint
        und PEM. Client schickt nur den Roh-Key + Beschreibung.
        """
        return self._request(
            "POST", f"/admin/users/{int(user_id)}/keys",
            json={"public_key": public_key, "description": description},
        ).json()

    def remove_user_key(self, fingerprint: str) -> dict:
        """DELETE /admin/keys/{fingerprint}."""
        return self._request("DELETE", f"/admin/keys/{fingerprint}").json()

    def list_user_keys(self, user_id: int) -> list[dict]:
        """GET /admin/users/{user_id}/keys."""
        try:
            return self._request("GET", f"/admin/users/{int(user_id)}/keys").json()
        except Exception:
            return []

    def issue_certificate(self, user_id: int, days_valid: int) -> dict:
        """POST /admin/users/{user_id}/certificates — Cert + Key zurück.

        Response enthält cert_pem + key_pem + serial + fingerprint. Der
        Client zeigt Serial dem Admin an, der Cert/Key dem Endbenutzer
        weitergibt (out-of-band).
        """
        return self._request(
            "POST", f"/admin/users/{int(user_id)}/certificates",
            json={"days_valid": int(days_valid)},
        ).json()

    def list_certificates(self) -> list[dict]:
        """GET /admin/certificates — alle Client-Certs."""
        try:
            return self._request("GET", "/admin/certificates").json()
        except Exception:
            return []

    def revoke_certificate(self, serial: str) -> dict:
        """POST /admin/certificates/{serial}/revoke."""
        return self._request("POST", f"/admin/certificates/{serial}/revoke").json()

    # ── D3: User-CRUD + Audit + API-Key (admin) ──

    def create_user(
        self, username: str, password: str, role: str,
        permissions: list[str] | None = None,
        create_linux_account: bool = False,
        ssh_public_keys: list[str] | None = None,
    ) -> dict:
        """POST /admin/users — neuen User anlegen.

        Server hashed das Passwort, validiert Rolle + Permissions, legt
        optional Linux-Account an. Client schickt nur Roh-Daten.
        """
        body: dict = {"username": username, "password": password, "role": role}
        if permissions is not None:
            body["permissions"] = permissions
        if create_linux_account:
            body["create_linux_account"] = True
        if ssh_public_keys:
            body["ssh_public_keys"] = ssh_public_keys
        return self._request("POST", "/admin/users", json=body).json()

    def update_user(self, user_id: int, **fields) -> dict:
        """PUT /admin/users/{user_id} — Felder aktualisieren.

        Akzeptiert: password, permissions, is_active, ban_reason, role.
        Server hashed neue Passwörter selbst.
        """
        return self._request(
            "PUT", f"/admin/users/{int(user_id)}", json=fields,
        ).json()

    def admin_delete_user(self, user_id: int) -> dict:
        """DELETE /admin/users/{user_id}."""
        return self._request("DELETE", f"/admin/users/{int(user_id)}").json()

    def admin_ban_user(self, user_id: int, reason: str = "") -> dict:
        """POST /admin/users/{user_id}/ban."""
        return self._request(
            "POST", f"/admin/users/{int(user_id)}/ban",
            json={"reason": reason},
        ).json()

    def admin_disconnect_user(self, user_id: int) -> dict:
        """POST /admin/users/{user_id}/disconnect — aktive Sessions kappen."""
        return self._request(
            "POST", f"/admin/users/{int(user_id)}/disconnect",
        ).json()

    def admin_activate_user(self, user_id: int) -> dict:
        """POST /admin/users/{user_id}/activate."""
        return self._request(
            "POST", f"/admin/users/{int(user_id)}/activate",
        ).json()

    def admin_deactivate_user(self, user_id: int) -> dict:
        """POST /admin/users/{user_id}/deactivate."""
        return self._request(
            "POST", f"/admin/users/{int(user_id)}/deactivate",
        ).json()

    def delete_audit_entry(self, entry_id: int) -> dict:
        """DELETE /admin/audit-log/{entry_id}."""
        return self._request(
            "DELETE", f"/admin/audit-log/{int(entry_id)}",
        ).json()

    def rotate_api_key(self) -> dict:
        """POST /admin/api-keys/rotate — neuer Key im Klartext zurück."""
        return self._request("POST", "/admin/api-keys/rotate").json()

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        """GET /admin/audit-log — letzte N Audit-Einträge."""
        try:
            data = self._request(
                "GET", "/admin/audit-log", params={"limit": int(limit)},
            ).json()
            return data if isinstance(data, list) else data.get("entries", [])
        except Exception:
            return []

    def list_api_keys(self) -> list[dict]:
        """GET /admin/api-keys — alle API-Keys (Hash + Prefix)."""
        try:
            return self._request("GET", "/admin/api-keys").json()
        except Exception:
            return []

    def list_public_keys(self, user_id: int | None = None) -> list[dict]:
        """GET /admin/users/{id}/keys oder /admin/keys (alle)."""
        try:
            if user_id is not None:
                return self._request(
                    "GET", f"/admin/users/{int(user_id)}/keys",
                ).json()
            return self._request("GET", "/admin/keys").json()
        except Exception:
            return []

    # ── B: TLS + Service-Status (B.1 Endpoints) ──

    def get_tls_status(self) -> dict:
        """GET /admin/tls/status — {configured, status, expires_at, days_remaining}."""
        try:
            return self._request("GET", "/admin/tls/status").json()
        except Exception as e:
            return {"configured": False, "status": "error", "error": str(e)}

    def generate_tls_cert(self) -> dict:
        """POST /admin/tls/generate — Self-Signed-Cert auf dem Server erzeugen."""
        return self._request("POST", "/admin/tls/generate").json()

    def get_service_status(self) -> dict:
        """GET /admin/service/status — {running, enabled, name}."""
        try:
            return self._request("GET", "/admin/service/status").json()
        except Exception as e:
            return {"running": False, "enabled": False, "error": str(e)}

    def service_action(self, action: str) -> dict:
        """POST /admin/service/{action} — start/stop/restart/enable/disable."""
        return self._request("POST", f"/admin/service/{action}").json()

    # ── B.3: Reports + Prizes + Predictions (Replacements) ──

    def get_cycle_report(self, report_id: str) -> dict | None:
        """GET /reports/{report_id} — einzelner Cycle-Report."""
        try:
            return self._request("GET", f"/reports/{report_id}").json()
        except Exception:
            return None

    def get_draw_prizes(self, draw_day: str, draw_date: str) -> list[dict]:
        """GET /prizes/{draw_day}/{draw_date} — Gewinnquoten der Ziehung."""
        try:
            data = self._request(
                "GET", f"/prizes/{draw_day}/{draw_date}",
            ).json()
            if isinstance(data, list):
                return data
            return data.get("prizes") or data.get("classes") or []
        except Exception:
            return []

    def get_predictions_for_date(
        self, draw_day: str, draw_date: str,
    ) -> list[dict]:
        """GET /predictions/{draw_day}/{draw_date} — alle Predictions."""
        try:
            data = self._request(
                "GET", f"/predictions/{draw_day}/{draw_date}",
            ).json()
            if isinstance(data, list):
                return data
            return data.get("predictions") or []
        except Exception:
            return []

    def get_draws(
        self, draw_day: str,
        year_from: int | None = None, year_to: int | None = None,
    ) -> list[dict]:
        """GET /draws/{draw_day} — alle Draws des Tages, optional Jahr-Filter."""
        params: dict = {}
        if year_from is not None:
            params["year_from"] = int(year_from)
        if year_to is not None:
            params["year_to"] = int(year_to)
        try:
            data = self._request(
                "GET", f"/draws/{draw_day}",
                params=params if params else None,
            ).json()
            if isinstance(data, list):
                return data
            return data.get("draws") or []
        except Exception:
            return []

    def get_prediction_dates(self, draw_day: str) -> list[str]:
        """GET /predictions/dates/{draw_day} — alle Daten mit Predictions."""
        try:
            data = self._request(
                "GET", f"/predictions/dates/{draw_day}",
            ).json()
            if isinstance(data, list):
                return data
            return data.get("dates") or []
        except Exception:
            return []

    def get_predictions_paginated(
        self, draw_day: str, draw_date: str,
        offset: int = 0, limit: int = 200,
    ) -> dict:
        """GET /predictions/{draw_day}/{draw_date}?offset=&limit=

        Response: `{predictions: [...], total: int, offset, limit}`.
        """
        try:
            return self._request(
                "GET", f"/predictions/{draw_day}/{draw_date}",
                params={"offset": int(offset), "limit": int(limit)},
            ).json()
        except Exception:
            return {"predictions": [], "total": 0, "offset": offset, "limit": limit}

    def delete_low_match_predictions(
        self, draw_day: str, draw_date: str, min_matches: int = 3,
    ) -> dict:
        """DELETE /predictions/cleanup/{draw_day}/{draw_date}?min_matches=N.

        Löscht alle Predictions mit `matches < min_matches`.
        """
        return self._request(
            "DELETE", f"/predictions/cleanup/{draw_day}/{draw_date}",
            params={"min_matches": int(min_matches)},
        ).json()

    def get_latest_prizes(self, draw_day: str) -> list[dict]:
        """GET /prizes/latest/{draw_day} — letzte Gewinnquoten."""
        try:
            data = self._request("GET", f"/prizes/latest/{draw_day}").json()
            if isinstance(data, list):
                return data
            return data.get("prizes") or []
        except Exception:
            return []

    def get_jackpot(self, draw_day: str) -> dict | None:
        """GET /jackpot/{draw_day} — Aktueller Jackpot (Klasse 1)."""
        try:
            data = self._request("GET", f"/jackpot/{draw_day}").json()
            return data.get("jackpot")
        except Exception:
            return None

    def get_purchased_dates(self, draw_day: str) -> list[str]:
        """GET /predictions/purchased/dates/{draw_day} — Daten gekaufter Tipps."""
        try:
            data = self._request(
                "GET", f"/predictions/purchased/dates/{draw_day}",
            ).json()
            if isinstance(data, list):
                return data
            return data.get("dates") or []
        except Exception:
            return []

    def get_purchased_predictions(
        self, draw_day: str, draw_date: str,
    ) -> list[dict]:
        """GET /predictions/purchased/{draw_day}/{draw_date} — gekaufte Tipps."""
        try:
            data = self._request(
                "GET", f"/predictions/purchased/{draw_day}/{draw_date}",
            ).json()
            if isinstance(data, list):
                return data
            return data.get("predictions") or []
        except Exception:
            return []

    def get_activity_log(self, limit: int = 30) -> list[dict]:
        """GET /activity-log — letzte data_fetch_log Einträge."""
        try:
            data = self._request(
                "GET", "/activity-log", params={"limit": int(limit)},
            ).json()
            if isinstance(data, list):
                return data
            return data.get("entries") or []
        except Exception:
            return []

    def generate_batch(
        self,
        strategy: str,
        draw_day: str,
        count: int,
        custom_weights: dict | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> dict:
        """POST /generate/batch — startet Server-side-Generation.

        Antwort enthält `task_id` für asynchrone Generation. Der Caller
        soll dann via `get_task(task_id)` den Status pollen.
        """
        body: dict = {
            "strategy": strategy,
            "draw_day": draw_day,
            "count": int(count),
        }
        if custom_weights:
            body["custom_weights"] = custom_weights
        if year_from is not None:
            body["year_from"] = int(year_from)
        if year_to is not None:
            body["year_to"] = int(year_to)
        return self._request("POST", "/generate/batch", json=body).json()

    def test_connection(self) -> tuple[bool, str]:
        """Verbindung zum Server testen."""
        try:
            result = self.health()
            return True, f"Verbunden (v{result.get('version', '?')})"
        except httpx.ConnectError:
            return False, f"Server nicht erreichbar: {self.base_url}"
        except httpx.HTTPStatusError as e:
            return False, f"HTTP-Fehler: {e.response.status_code}"
        except Exception as e:
            return False, str(e)

    # ── Settings ──

    def get_db_stats(self) -> dict:
        return self._request("GET", "/stats/db").json()

    def db_tables(self) -> list[dict]:
        """Alle Tabellen mit Spalten und Zeilenanzahl."""
        return self._request("GET", "/db/tables").json()

    def db_integrity(self) -> dict:
        """DB-Integritätsbericht (Lücken-Erkennung pro Ziehtag)."""
        return self._request("GET", "/db/integrity").json()

    def delete_predictions_for_date(
        self, draw_day: str, draw_date: str, keep_purchased: bool = True,
    ) -> dict:
        """Alle Predictions einer Ziehung löschen (gekaufte bleiben default)."""
        return self._request(
            "DELETE", f"/predictions/{draw_day}/{draw_date}",
            params={"keep_purchased": "true" if keep_purchased else "false"},
        ).json()

    def regenerate_predictions(
        self, draw_day: str, keep_purchased: bool = True,
    ) -> dict:
        """Aktuelle Ziehung loeschen + neu generieren mit User-Counts."""
        return self._request(
            "POST", f"/generate/regenerate/{draw_day}",
            params={"keep_purchased": "true" if keep_purchased else "false"},
        ).json()

    def list_db_backups(self) -> list[dict]:
        """Liste der vorhandenen DB-Backups (Datei, Größe, Datum)."""
        return self._request("GET", "/admin/db/backups").json()

    def create_db_backup(self) -> dict:
        """DB-Backup jetzt erstellen (manueller Trigger)."""
        return self._request("POST", "/admin/db/backup-now").json()

    def db_table_rows(
        self, table_name: str, page: int = 1, page_size: int = 100,
        search: str = "", sort_col: str = "", sort_dir: str = "ASC",
    ) -> dict:
        """Zeilen einer Tabelle (paginiert)."""
        return self._request("GET", f"/db/tables/{table_name}/rows", params={
            "page": page, "page_size": page_size,
            "search": search, "sort_col": sort_col, "sort_dir": sort_dir,
        }).json()

    def db_delete_row(self, table_name: str, row_id: int) -> dict:
        """Zeile löschen."""
        return self._request("DELETE", f"/db/tables/{table_name}/rows/{row_id}").json()

    def check_ticket(
        self, numbers: list[int], super_number: int,
        draw_day: str, draw_date: Optional[str] = None,
    ) -> dict:
        return self._request("POST", "/check", json={
            "numbers": numbers,
            "super_number": super_number,
            "draw_day": draw_day,
            "draw_date": draw_date,
        }).json()

    def chat(self, message: str) -> str:
        resp = self._request("POST", "/chat", json={"message": message})
        return resp.json().get("reply", "")

    def clear_chat(self) -> dict:
        return self._request("POST", "/chat/clear").json()

    def get_chat_sessions(self, page: str) -> list[dict]:
        return self._request("GET", "/chat/sessions", params={"page": page}).json()

    def create_chat_session(self, page: str) -> int:
        resp = self._request("POST", "/chat/sessions", json={"page": page})
        return resp.json().get("session_id", 0)

    def get_chat_messages(self, session_id: int) -> list[dict]:
        return self._request("GET", f"/chat/sessions/{session_id}/messages").json()

    def add_chat_message(self, session_id: int, role: str, content: str) -> None:
        self._request("POST", f"/chat/sessions/{session_id}/messages",
                       json={"role": role, "content": content})

    def delete_chat_session(self, session_id: int) -> dict:
        return self._request("DELETE", f"/chat/sessions/{session_id}").json()

    def get_scheduler_status(self) -> dict:
        return self._request("GET", "/scheduler/status").json()

    def get_live_feed(self, limit: int = 30) -> list:
        resp = self._request("GET", "/monitor/live-feed", params={"limit": limit})
        return resp.json().get("events", [])

    def request_ai_oversight(self) -> dict:
        return self._request("POST", "/monitor/ai-oversight", timeout=120).json()

    # ── L4.1: Worker-Endpoints (entspricht L2.3 Backend) ──

    def get_workers_config(self) -> dict:
        """Aktuelle Worker-Count-Konfig (env/db/default)."""
        return self._request("GET", "/workers/config").json()

    def put_workers_config(self, worker_count: int) -> dict:
        """Worker-Count in DB setzen. Restart erforderlich für Wirkung."""
        return self._request(
            "PUT", "/workers/config",
            json={"worker_count": int(worker_count)},
        ).json()

    def get_workers_status(self, limit: int = 50, job_name: str | None = None) -> dict:
        """Live: geplante Jobs + 7d-Statistik pro Job + recent_runs."""
        params: dict = {"limit": int(limit)}
        if job_name:
            params["job_name"] = job_name
        return self._request("GET", "/workers/status", params=params).json()

    def get_health_detailed(self) -> dict:
        """Erweiterter Health: Models/Predictions/Crawl/Scheduler/7d-Job-Stats."""
        return self._request("GET", "/health/detailed", timeout=30).json()

    # ── Backtest ──

    def get_tasks(self, status: str | None = None) -> list[dict]:
        """Alle Server-Tasks abfragen, optional nach Status filtern."""
        params = {}
        if status:
            params["status"] = status
        return self._request("GET", "/tasks", params=params).json().get("tasks", [])

    def get_task(self, task_id: str) -> dict:
        """Einzelnen Task abfragen."""
        return self._request("GET", f"/tasks/{task_id}").json()

    def cancel_task(self, task_id: str) -> dict:
        """Laufenden Task abbrechen."""
        return self._request("POST", f"/tasks/{task_id}/cancel").json()

    # ── AI-gesteuertes ML-Training (geben jetzt task_id zurück) ──

    def hypersearch(self, draw_day: str, param_grid: dict | None = None) -> dict:
        return self._request("POST", "/ml/hypersearch", json={
            "draw_day": draw_day, "param_grid": param_grid,
        }).json()

    def tournament(self, draw_day: str, n_rounds: int = 5) -> dict:
        return self._request("POST", "/ml/tournament", json={
            "draw_day": draw_day, "n_rounds": n_rounds,
        }).json()

    def best_run(self, draw_day: str) -> dict:
        return self._request("GET", f"/ml/best-run/{draw_day}").json()

    # ── Self-Improvement & Sandbox ──

    def get_reports(
        self, draw_day: str | None = None, limit: int = 20,
        draw_days: list[str] | None = None,
    ) -> list[dict]:
        """Zyklus-Berichte auflisten."""
        params: dict = {"limit": limit}
        if draw_days:
            params["draw_days"] = ",".join(draw_days)
        elif draw_day:
            params["draw_day"] = draw_day
        return self._request("GET", "/reports", params=params).json().get("reports", [])

    def get_report(self, report_id: str) -> dict:
        """Einzelnen Zyklus-Bericht laden."""
        return self._request("GET", f"/reports/{report_id}").json()

    def get_latest_report(self, draw_day: str) -> dict:
        """Neuesten Zyklus-Bericht für einen Ziehungstag laden."""
        return self._request("GET", f"/reports/latest/{draw_day}").json()

    def get_report_hits(self, report_id: str, min_matches: int = 3) -> dict:
        """Detail-Treffer und Accuracy-Stats für einen Bericht."""
        return self._request(
            "GET", f"/reports/{report_id}/hits",
            params={"min_matches": min_matches},
        ).json()

    def analyze_report_hits(self, report_id: str) -> dict:
        """AI-Analyse der Treffer-Muster eines Berichts."""
        return self._request("POST", f"/reports/{report_id}/analyze-hits").json()

    # ── Gewinnquoten / Jackpot ──

    def get_jackpot(self, draw_day: str) -> dict:
        """Neuester Jackpot für einen Ziehungstag."""
        return self._request("GET", f"/jackpot/{draw_day}").json()

    def get_latest_prizes(self, draw_day: str) -> dict:
        """Alle Gewinnklassen der letzten Ziehung für einen Tag."""
        return self._request("GET", f"/prizes/latest/{draw_day}").json()

    def get_live_jackpot(self) -> dict:
        """Live-Jackpot-Beträge vom Server (aus Settings-Tabelle)."""
        return self._request("GET", "/jackpot/live").json()

    def scrape_prizes(self) -> dict:
        """Manuelles Scrapen der Gewinnquoten."""
        return self._request("POST", "/prizes/scrape").json()

    # ── Auto-Generate ──

    def get_adaptive_count(self, draw_day: str) -> dict:
        """Adaptive-Count-Status für einen Ziehungstag."""
        return self._request(
            "GET", "/generate/adaptive-count", params={"draw_day": draw_day},
        ).json()

    def get_activity_log(self, limit: int = 50) -> list[dict]:
        """Datenquellen-Aktivitätsprotokoll laden."""
        resp = self._request("GET", "/activity-log", params={"limit": limit})
        return resp.json().get("entries", [])

    # ── Crawl Monitor ──

    def get_crawl_monitor(self) -> dict:
        """Alle Crawl-Monitor-Daten in einem Aufruf."""
        return self._request("GET", "/crawl/monitor").json()

    def update_crawl_schedule(self, **kwargs) -> dict:
        """Crawl-Zeitplan aktualisieren."""
        return self._request("PUT", "/crawl/schedule", json=kwargs).json()

    def get_crawl_history(self, draw_day: str | None = None, limit: int = 50) -> list:
        """Crawl-Historie laden."""
        params: dict = {"limit": limit}
        if draw_day:
            params["draw_day"] = draw_day
        return self._request("GET", "/crawl/history", params=params).json().get("entries", [])

    def trigger_crawl(self, draw_day: str) -> dict:
        """Manuellen Crawl auslösen."""
        return self._request("POST", f"/crawl/trigger/{draw_day}").json()

    def reset_crawl_retry(self, draw_day: str) -> dict:
        """Retry-Counter zurücksetzen + sofort crawlen."""
        return self._request("POST", f"/crawl/reset-retry/{draw_day}").json()

    def reset_crawl_timing(self) -> dict:
        """ML-gelernte Crawl-Zeiten zurücksetzen."""
        return self._request("POST", "/crawl/reset-timing").json()

    # ── Mass Generation ──

    def mass_generate(self, draw_day: str, strategy: str, count: int) -> dict:
        """Start mass prediction generation."""
        return self._request("POST", "/mass-gen/generate", json={
            "draw_day": draw_day, "strategy": strategy, "count": count,
        }).json()

    def mass_compare(self, batch_id: str, numbers: list, bonus: list) -> dict:
        """Compare batch against draw results."""
        return self._request("POST", "/mass-gen/compare", json={
            "batch_id": batch_id, "drawn_numbers": numbers, "drawn_bonus": bonus,
        }).json()

    def mass_batches(self, limit: int = 20) -> list:
        """List mass generation batches."""
        return self._request("GET", "/mass-gen/batches", params={"limit": limit}).json().get("batches", [])

    def mass_hits(self, batch_id: str) -> list:
        """Get hits for a batch."""
        return self._request("GET", f"/mass-gen/hits/{batch_id}").json().get("hits", [])

    def mass_generate_pipeline(
        self, draw_day: str, strategy: str, count: int, telegram: bool = True,
    ) -> dict:
        """Start full mass-gen pipeline (generate + dedup + regen + report)."""
        return self._request("POST", "/mass-gen/pipeline", json={
            "draw_day": draw_day, "strategy": strategy,
            "count": count, "telegram": telegram,
        }).json()

    def mass_dedup(self, batch_id: str) -> dict:
        """Trigger dedup on existing batch."""
        return self._request("POST", f"/mass-gen/dedup/{batch_id}").json()

    def firewall_status(self) -> dict:
        return self._request("GET", "/firewall/status").json()

    def firewall_list_whitelist(self) -> list:
        return self._request("GET", "/firewall/whitelist").json()

    def firewall_add_whitelist(
        self, ip_or_cidr: str, entry_type: str = "ip", description: str = "",
    ) -> dict:
        return self._request("POST", "/firewall/whitelist", json={
            "ip_or_cidr": ip_or_cidr,
            "entry_type": entry_type,
            "description": description,
        }).json()

    def firewall_remove_whitelist(self, entry_id: int) -> dict:
        return self._request("DELETE", f"/firewall/whitelist/{entry_id}").json()

    def firewall_toggle_whitelist(self, entry_id: int) -> dict:
        return self._request("PUT", f"/firewall/whitelist/{entry_id}/toggle").json()

    def firewall_list_blacklist(self, include_expired: bool = False) -> list:
        params = {"include_expired": include_expired} if include_expired else {}
        return self._request("GET", "/firewall/blacklist", params=params).json()

    def firewall_add_blacklist(
        self, ip_or_cidr: str, entry_type: str = "ip", reason: str = "",
    ) -> dict:
        return self._request("POST", "/firewall/blacklist", json={
            "ip_or_cidr": ip_or_cidr,
            "entry_type": entry_type,
            "reason": reason,
        }).json()

    def firewall_remove_blacklist(self, entry_id: int) -> dict:
        return self._request("DELETE", f"/firewall/blacklist/{entry_id}").json()

    def firewall_unblock(self, entry_id: int) -> dict:
        return self._request("POST", f"/firewall/blacklist/{entry_id}/unblock").json()

    def firewall_list_blocked(self) -> list:
        return self._request("GET", "/firewall/blocked").json()

    def firewall_unblock_auto(self, entry_id: int) -> dict:
        return self._request("POST", f"/firewall/blocked/{entry_id}/unblock").json()

    def firewall_list_failed_attempts(self, ip: str | None = None) -> list:
        params = {}
        if ip:
            params["ip"] = ip
        return self._request("GET", "/firewall/failed-attempts", params=params).json()

    def firewall_clear_failed_attempts(self, ip: str) -> dict:
        return self._request("DELETE", f"/firewall/failed-attempts/{ip}").json()

    def firewall_check_ip(self, ip: str) -> dict:
        return self._request("POST", "/firewall/check-ip", json={"ip": ip}).json()

    def firewall_geoip_status(self) -> dict:
        return self._request("GET", "/firewall/geoip/status").json()

    def firewall_geoip_lookup(self, ip: str) -> dict:
        return self._request("POST", "/firewall/geoip/lookup", json={"ip": ip}).json()

    def firewall_geoip_update(self) -> dict:
        return self._request("POST", "/firewall/geoip/update-db").json()

    def firewall_fail2ban_status(self) -> dict:
        return self._request("GET", "/firewall/fail2ban/status").json()

    def firewall_fail2ban_install(self) -> dict:
        return self._request("POST", "/firewall/fail2ban/install").json()

    def firewall_fail2ban_remove(self) -> dict:
        return self._request("POST", "/firewall/fail2ban/remove").json()

    def firewall_fail2ban_ban(self, ip: str) -> dict:
        return self._request("POST", "/firewall/fail2ban/ban", json={"ip": ip}).json()

    def firewall_fail2ban_unban(self, ip: str) -> dict:
        return self._request("POST", "/firewall/fail2ban/unban", json={"ip": ip}).json()

    def firewall_log(self, limit: int = 100, offset: int = 0) -> list:
        return self._request(
            "GET", "/firewall/log", params={"limit": limit, "offset": offset},
        ).json()

    def firewall_log_stats(self) -> dict:
        return self._request("GET", "/firewall/log/stats").json()

    def firewall_log_cleanup(self) -> dict:
        return self._request("DELETE", "/firewall/log/cleanup").json()

    def firewall_chat(self, message: str) -> str | dict:
        """Security-Chat: Frage an AI-Sicherheitsassistenten.

        Returns str bei Erfolg, dict mit 'error'+'hint' bei fehlender AI-Konfiguration.
        """
        resp = self._request("POST", "/firewall/chat", json={"message": message})
        data = resp.json()
        if "error" in data:
            return data
        return data.get("reply", "")

    # ── TLS / Let's Encrypt ──

    def tls_status(self) -> dict:
        """Aktuelles Zertifikat-Info: Issuer, Ablauf, Self-Signed."""
        return self._request("GET", "/tls/status").json()

    def tls_le_request(
        self,
        domain: str,
        email: str,
        webroot: str,
        dry_run: bool = False,
    ) -> dict:
        """Neues LE-Cert anfordern."""
        return self._request("POST", "/tls/letsencrypt/request", json={
            "domain": domain,
            "email": email,
            "webroot": webroot,
            "dry_run": dry_run,
        }).json()

    def tls_le_renew(self) -> dict:
        """LE-Cert manuell erneuern."""
        return self._request("POST", "/tls/letsencrypt/renew").json()

    def tls_le_detect(self, domain: str = "") -> dict:
        """Vorhandenes LE-Cert suchen."""
        payload = {"domain": domain} if domain else {}
        return self._request("POST", "/tls/letsencrypt/detect", json=payload).json()

    # ── User-Management (Admin) ──

    def close(self) -> None:
        self._client.close()
