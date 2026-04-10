"""Generation."""
import httpx
from typing import Optional

from lotto_common.utils.logging_config import get_logger

logger = get_logger("api.generation")


class GenerationMixin:
    """Generierungs-API Mixin: Vorhersagen, Batch, Combos."""

    def generate(
        self, strategy: str = "ensemble",
        draw_day: str = "saturday",
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> dict:
        return self._request("POST", "/generate", json={
            "strategy": strategy,
            "draw_day": draw_day,
            "year_from": year_from,
            "year_to": year_to,
        }).json()

    def generate_batch(
        self, strategy: str = "all", draw_day: str = "saturday",
        count: int = 6, year_from: int | None = None,
        year_to: int | None = None,
        custom_weights: dict[str, float] | None = None,
    ) -> dict:
        payload: dict = {
            "strategy": strategy, "draw_day": draw_day,
            "count": count, "year_from": year_from, "year_to": year_to,
        }
        if custom_weights:
            payload["custom_weights"] = custom_weights
        return self._request("POST", "/generate/batch", json=payload).json()

    def generate_combos(self, draw_day: str, draw_date: str = "") -> dict:
        return self._request("POST", "/generate/combos", json={
            "draw_day": draw_day, "draw_date": draw_date,
        }).json()

    def combo_status(self, draw_day: str) -> dict:
        return self._request("GET", f"/combos/status/{draw_day}").json()

    def toggle_combo(self, draw_day: str, combo_key: str, active: bool) -> dict:
        return self._request("PUT", "/combos/toggle", json={
            "draw_day": draw_day, "combo_key": combo_key, "active": active,
        }).json()

    def strategy_performance(self, draw_day: str) -> dict:
        return self._request("GET", f"/performance/{draw_day}").json()

    def get_strategy_weights(self, draw_day: str) -> dict:
        """Aktuelle adaptive Ensemble-Gewichte."""
        return self._request("GET", f"/strategies/weights/{draw_day}").json()

    # ── Persistente Task-Verwaltung ──

    def auto_generate_status(self) -> dict:
        """Letzte Auto-Generierung: wann, wie viele, für welches Datum."""
        return self._request("GET", "/generate/auto-status").json()

    def trigger_auto_generate(self, draw_day: str) -> dict:
        """Manueller Trigger für Auto-Generate."""
        return self._request("POST", "/generate/auto-trigger", json={
            "draw_day": draw_day,
        }).json()

    # ── Aktivitätsprotokoll ──

