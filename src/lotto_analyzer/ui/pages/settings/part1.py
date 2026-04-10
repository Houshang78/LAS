"""UI-Seite settings: part1."""

from __future__ import annotations

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_common.config import ConfigManager
from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config


logger = get_logger("settings.part1")
from lotto_common.models.ai_config import AIMode, AIModel

from lotto_analyzer.ui.widgets.help_button import HelpButton


class Part1Mixin:
    """Part1 Mixin."""

    def set_user_role(self, role: str) -> None:
        """Set user role, restrict save button, show user mgmt for admin/owner."""
        super().set_user_role(role)
        self._user_role = role
        if self._is_readonly:
            self._save_btn.set_label(_("Nur Lesezugriff"))
        if hasattr(self, "_show_user_management"):
            self._show_user_management(role)

    def refresh(self) -> None:
        """Server-Einstellungen nur neu laden wenn veraltet (>5min)."""
        if self.is_stale() and self.app_mode == "client" and self.api_client:
            self._load_server_settings()

    def _load_server_settings(self) -> None:
        """Alle Server-Einstellungen laden (AI, Crawl, Learning, Generation, Security)."""
        def worker():
            results = {}
            for key, method in [
                ("ai", self.api_client.get_ai_settings),
                ("crawl", self.api_client.get_crawl_settings),
                ("learning", self.api_client.get_learning_settings),
                ("generation", self.api_client.get_generation_settings),
            ]:
                try:
                    results[key] = method()
                except Exception as e:
                    logger.warning(f"Server-{key}-Settings laden fehlgeschlagen: {e}")
            GLib.idle_add(self._apply_server_settings, results)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_server_settings(self, results: dict) -> bool:
        """Server-Einstellungen in die UI-Felder uebernehmen."""
        # AI
        ai = results.get("ai", {})
        if ai:
            mode = ai.get("mode", "api")
            self._ai_mode.set_selected(0 if mode == "api" else 1)
            model = ai.get("model", "")
            for i, mid in enumerate(self._model_values):
                if mid == model:
                    self._model_combo.set_selected(i)
                    break
            if ai.get("api_key_set"):
                self._api_key.set_text("")
                self._api_key.set_title(_("API-Schlüssel (auf Server gesetzt)"))
            else:
                self._api_key.set_title(_("API-Schlüssel"))
            self._cli_path.set_text(ai.get("cli_path", "claude"))

        # Crawl
        crawl = results.get("crawl", {})
        if crawl:
            self._crawl_enabled.set_active(crawl.get("enabled", True))
            self._retry_interval.set_value(crawl.get("retry_interval_hours", 3))

        # Learning
        learn = results.get("learning", {})
        if learn:
            self._learn_enabled.set_active(learn.get("enabled", True))
            self._auto_retrain.set_active(learn.get("auto_retrain_after_draw", True))
            self._train_on_startup.set_active(learn.get("auto_train_on_startup", True))
            self._self_improve.set_active(learn.get("auto_self_improve", True))
            self._crawl_timing.set_active(learn.get("crawl_timing_learning", True))
            self._strategy_weights.set_active(learn.get("strategy_weight_learning", True))
            self._eval_window.set_value(learn.get("evaluation_window", 50))
            self._max_model_age.set_value(learn.get("max_model_age_days", 7))

        # Auto-Generation
        gen = results.get("generation", {})
        if gen:
            self._autogen_enabled.set_active(gen.get("enabled", True))
            self._gen_after_train.set_active(gen.get("generate_after_train", True))
            self._auto_compare.set_active(gen.get("auto_compare", True))
            self._count_per_strategy.set_value(gen.get("count_per_strategy", 170))
            self._purchase_count.set_value(gen.get("purchase_count", 6))

        logger.info("Server-Einstellungen geladen")
        return False

