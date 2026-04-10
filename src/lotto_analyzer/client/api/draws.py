"""Draws."""
import httpx
from typing import Optional

from lotto_common.utils.logging_config import get_logger

logger = get_logger("api.draws")


class DrawsMixin:
    """Ziehungs-API Mixin: Crawling, Import, Statistik."""

    def get_crawl_settings(self) -> dict:
        """Crawl-Einstellungen vom Server."""
        return self._request("GET", "/settings/crawl").json()

    def update_crawl_settings(self, **kwargs) -> dict:
        """Crawl-Einstellungen auf dem Server ändern."""
        return self._request("PUT", "/settings/crawl", json=kwargs).json()

    def db_integrity(self) -> dict:
        """DB-Integritätspruefung: Lücken erkennen."""
        return self._request("GET", "/db/integrity").json()

    def get_latest_draw(self, draw_day: str) -> dict:
        return self._request("GET", f"/draws/latest/{draw_day}").json()

    def get_draws(
        self, draw_day: str,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> list[dict]:
        params = {}
        if year_from:
            params["year_from"] = year_from
        if year_to:
            params["year_to"] = year_to
        return self._request("GET", f"/draws/{draw_day}", params=params).json()

    def get_statistics(
        self, draw_day: str,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        game_type: Optional[str] = None,
    ) -> dict:
        params = {}
        if year_from:
            params["year_from"] = year_from
        if year_to:
            params["year_to"] = year_to
        if game_type:
            params["game_type"] = game_type
        return self._request("POST", f"/statistics/{draw_day}", params=params).json()

    def crawl(
        self, draw_day: str = "both",
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> dict:
        return self._request("POST", "/crawl", json={
            "draw_day": draw_day,
            "year_from": year_from,
            "year_to": year_to,
        }).json()

    def crawl_latest(self) -> dict:
        return self._request("POST", "/crawl/latest").json()

    def import_csv(self, draw_day: str, csv_content: str) -> dict:
        """CSV-Inhalt an Server senden zum Importieren."""
        return self._request("POST", "/draws/import-csv", json={
            "draw_day": draw_day,
            "csv_content": csv_content,
        }).json()

    def manual_draw_entry(
        self, draw_date: str, numbers: list[int],
        super_number: int, draw_day: str,
    ) -> dict:
        """Einzelne Ziehung manuell eintragen."""
        return self._request("POST", "/draws/manual", json={
            "draw_date": draw_date,
            "numbers": numbers,
            "super_number": super_number,
            "draw_day": draw_day,
        }).json()

    # ── AI-Analyse generierter Tipps ──

    def get_draw_prizes(self, draw_day: str, draw_date: str) -> dict:
        """Gewinnquoten einer Ziehung laden."""
        return self._request("GET", f"/prizes/{draw_day}/{draw_date}").json()

