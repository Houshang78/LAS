"""Ml Training."""
import httpx
from typing import Optional

from lotto_common.utils.logging_config import get_logger

logger = get_logger("api.ml_training")


class MlTrainingMixin:
    """ML-Training-API Mixin: Training, Hypersearch, Self-Improve."""

    def train_ml(self) -> dict:
        return self._request("POST", "/ml/train").json()

    def train_ml_custom(
        self, epochs: int = 50, lr: float = 0.001,
        draw_day: str | None = None,
    ) -> dict:
        return self._request("POST", "/ml/train/custom", json={
            "epochs": epochs, "lr": lr, "draw_day": draw_day,
        }).json()

    def train_status(self, task_id: str) -> dict:
        return self._request("GET", f"/ml/train/{task_id}").json()

    def ml_status(self) -> dict:
        return self._request("GET", "/ml/status").json()

    # ── Server-Monitor ──

    def start_backtest(self, draw_day: str, window_months: int = 12,
                       step_size: int = 1, include_lstm: bool = False) -> dict:
        return self._request("POST", "/backtest/start", json={
            "draw_day": draw_day, "window_months": window_months,
            "step_size": step_size, "include_lstm": include_lstm,
        }).json()

    def get_backtest_runs(self, draw_day: str = None, limit: int = 20) -> list:
        params = {"limit": limit}
        if draw_day:
            params["draw_day"] = draw_day
        return self._request("GET", "/backtest/runs", params=params).json()

    def get_backtest_run(self, run_id: str) -> dict:
        return self._request("GET", f"/backtest/runs/{run_id}").json()

    def get_backtest_results(self, run_id: str, offset: int = 0, limit: int = 100) -> list:
        return self._request("GET", f"/backtest/runs/{run_id}/results",
                             params={"offset": offset, "limit": limit}).json()

    def get_backtest_latest(self, draw_day: str) -> dict | None:
        return self._request("GET", f"/backtest/latest/{draw_day}").json()

    # ── ML-Entkopplung: Batch, Combos, Performance, Compare ──

    def needs_ml_training(self, draw_day: str) -> dict:
        return self._request("GET", f"/ml/needs-training/{draw_day}").json()

    def ai_train(self, draw_day: str, mode: str = "suggest") -> dict:
        return self._request("POST", "/ml/ai-train", json={
            "draw_day": draw_day, "mode": mode,
        }).json()

    def training_history(self, draw_day: str, limit: int = 20) -> dict:
        return self._request("GET", f"/ml/training-history/{draw_day}",
                             params={"limit": limit}).json()

    def start_self_improve(self, draw_day: str) -> dict:
        """Self-Improvement Loop starten."""
        return self._request("POST", "/ml/self-improve/start", json={
            "draw_day": draw_day,
        }).json()

    def self_improve_status(self) -> dict:
        """Aktive Self-Improvement Sessions abfragen."""
        return self._request("GET", "/ml/self-improve/status").json()

    def self_improve_history(self, draw_day: str, limit: int = 20) -> dict:
        """Self-Improvement History für einen Ziehungstag."""
        return self._request(
            "GET", f"/ml/self-improve/history/{draw_day}",
            params={"limit": limit},
        ).json()

    def self_improve_report(self, session_id: str) -> dict:
        """Abschlussbericht einer Self-Improvement Session laden."""
        return self._request(
            "GET", f"/ml/self-improve/report/{session_id}",
        ).json()

    def get_sandbox_scripts(
        self, script_type: str | None = None, status: str | None = None,
    ) -> list[dict]:
        """Sandbox-Scripts abfragen."""
        params = {}
        if script_type:
            params["script_type"] = script_type
        if status:
            params["status"] = status
        return self._request(
            "GET", "/ml/sandbox/scripts", params=params,
        ).json().get("scripts", [])

    def get_sandbox_script(self, script_id: str) -> dict:
        """Einzelnes Sandbox-Script mit Source-Code laden."""
        return self._request(
            "GET", f"/ml/sandbox/scripts/{script_id}",
        ).json()

    def train_multi_stage(
        self, draw_day: str, stages: list[dict] | None = None,
    ) -> dict:
        """Multi-Stage Training starten."""
        return self._request("POST", "/ml/train/multi-stage", json={
            "draw_day": draw_day,
            "stages": stages,
        }).json()

    # ── Telegram ──

