"""Predictions."""
import httpx
from typing import Optional

from lotto_common.utils.logging_config import get_logger

logger = get_logger("api.predictions")


class PredictionsMixin:
    """Predictions-API Mixin: Vergleich, Performance, Kauf."""

    def compare_predictions(
        self, draw_day: str, draw_date: str,
        numbers: list[int], super_number: int | None = None,
    ) -> dict:
        return self._request("POST", "/compare", json={
            "draw_day": draw_day, "draw_date": draw_date,
            "numbers": numbers, "super_number": super_number,
        }).json()

    # ── Predictions: Browse + Cleanup ──

    def get_prediction_dates(self, draw_day: str) -> list[str]:
        """Alle Daten mit gespeicherten Predictions."""
        data = self._request("GET", f"/predictions/dates/{draw_day}").json()
        return data.get("dates", [])

    def get_predictions(
        self, draw_day: str, draw_date: str,
        offset: int = 0, limit: int = 20,
    ) -> dict:
        """Predictions mit Pagination laden."""
        return self._request(
            "GET", f"/predictions/{draw_day}/{draw_date}",
            params={"offset": offset, "limit": limit},
        ).json()

    def cleanup_predictions(
        self, draw_day: str, draw_date: str, min_matches: int = 3,
    ) -> dict:
        """Predictions unter Schwelle löschen."""
        return self._request(
            "DELETE", f"/predictions/cleanup/{draw_day}/{draw_date}",
            params={"min_matches": min_matches},
        ).json()

    # ── Purchased Predictions ──

    def purchase_predictions(
        self, draw_day: str, draw_date: str,
        count: int, send_telegram: bool = True,
    ) -> dict:
        """Beste N Tipps als gekauft markieren + Telegram senden."""
        return self._request("POST", "/predictions/purchase", json={
            "draw_day": draw_day,
            "draw_date": draw_date,
            "count": count,
            "send_telegram": send_telegram,
        }).json()

    def get_purchased_predictions(
        self, draw_day: str, draw_date: str,
    ) -> dict:
        """Nur gekaufte Predictions für ein Datum laden."""
        return self._request(
            "GET", f"/predictions/purchased/{draw_day}/{draw_date}",
        ).json()

    def get_purchased_dates(self, draw_day: str) -> list[str]:
        """Daten mit gekauften Predictions."""
        data = self._request(
            "GET", f"/predictions/purchased/dates/{draw_day}",
        ).json()
        return data.get("dates", [])

    # ── Recommendations, CSV-Import, Manuelle Eingabe ──

    def recommendations(self, draw_day: str, count: int = 0) -> dict:
        """Kaufempfehlungen für einen Ziehtag."""
        return self._request(
            "GET", f"/recommendations/{draw_day}", params={"count": count},
        ).json()

    def ai_analyze_predictions(
        self, results: list[dict], draw_day: str,
        hot_numbers: list[int] | None = None,
    ) -> dict:
        """AI bewertet generierte Tipps und waehlt Top-Picks."""
        payload: dict = {
            "results": results,
            "draw_day": draw_day,
        }
        if hot_numbers:
            payload["hot_numbers"] = hot_numbers
        return self._request("POST", "/predictions/ai-analyze", json=payload).json()

    # ── Strategie-Empfehlung ──

    def recommend_strategies(self, draw_day: str) -> dict:
        """AI empfiehlt optimale Strategien für einen Ziehungstag."""
        return self._request("GET", f"/strategies/recommend/{draw_day}").json()

    def compare_ranges(
        self, draw_day: str, ranges: list[list[int]] | None = None,
    ) -> dict:
        return self._request("POST", "/ml/compare-ranges", json={
            "draw_day": draw_day, "ranges": ranges,
        }).json()

