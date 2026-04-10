"""ML-Dashboard: Hauptseite mit allen Sektionen."""

from __future__ import annotations

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.config import ConfigManager
from lotto_common.i18n import _
from lotto_common.models.draw import DrawDay
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_common.utils.logging_config import get_logger

from lotto_analyzer.ui.pages.ml_dashboard.model_status import ModelStatusMixin
from lotto_analyzer.ui.pages.ml_dashboard.training_history import TrainingHistoryMixin
from lotto_analyzer.ui.pages.ml_dashboard.strategy_comparison import StrategyComparisonMixin
from lotto_analyzer.ui.pages.ml_dashboard.feature_importance import FeatureImportanceMixin
from lotto_analyzer.ui.pages.ml_dashboard.combo_evaluation import ComboEvaluationMixin
from lotto_analyzer.ui.pages.ml_dashboard.self_improvement import SelfImprovementMixin
from lotto_analyzer.ui.pages.ml_dashboard.export import ExportMixin

logger = get_logger("ml_dashboard")

DAY_LABELS = {
    "saturday": _("Samstag"),
    "wednesday": _("Mittwoch"),
    "tuesday": _("Dienstag (EJ)"),
    "friday": _("Freitag (EJ)"),
}

MODEL_INFO = {
    "rf": {
        "name": "Random Forest",
        "icon": "🌳",
        "desc": _(
            "Ensemble aus 50 Entscheidungsbäumen. Jeder Baum sieht einen "
            "zufälligen Teil der 322 Features und stimmt ab. Robust gegen "
            "Überanpassung, schnell trainierbar, gut interpretierbar."
        ),
    },
    "gb": {
        "name": "Gradient Boosting",
        "icon": "📈",
        "desc": _(
            "Sequentielles Ensemble: Jeder neue Baum korrigiert die Fehler "
            "der vorherigen. 50 Stufen, lernt komplexere Muster als RF, "
            "aber empfindlicher gegenüber Rauschen."
        ),
    },
    "lstm": {
        "name": "LSTM Neural Network",
        "icon": "🧠",
        "desc": _(
            "Rekurrentes neuronales Netzwerk (PyTorch). Lernt zeitliche "
            "Sequenzen in den Ziehungsfolgen. Braucht mehr Daten und "
            "Training, kann aber langfristige Muster erkennen."
        ),
    },
}


class MLDashboardPage(
    ModelStatusMixin, TrainingHistoryMixin, StrategyComparisonMixin,
    FeatureImportanceMixin, ComboEvaluationMixin, SelfImprovementMixin,
    ExportMixin, BasePage,
):
    """ML-Dashboard: Überblick über alle Machine-Learning-Komponenten."""

    def __init__(self, config_manager: ConfigManager, db: Database | None,
                 app_mode: str, api_client=None, app_db=None, backtest_db=None):
        super().__init__(config_manager, db, app_mode, api_client, app_db=app_db, backtest_db=backtest_db)
        self._draw_day = "saturday"
        self._loading = False
        self._ml_data: dict = {}
        self._build_ui()

    def _build_ui(self) -> None:
        scroll = Gtk.ScrolledWindow(vexpand=True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        self._content = content

        # ── Header ──
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        title = Gtk.Label(label=_("ML-Dashboard"))
        title.add_css_class("title-1")
        title.set_hexpand(True)
        title.set_xalign(0)
        header.append(title)

        # Ziehungstag-Dropdown
        self._day_combo = Gtk.ComboBoxText()
        for day_val, day_label in DAY_LABELS.items():
            self._day_combo.append(day_val, day_label)
        self._day_combo.set_active_id("saturday")
        self._day_combo.connect("changed", self._on_day_changed)
        header.append(self._day_combo)

        # Refresh
        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        header.append(self._spinner)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text(_("Daten neu laden"))
        refresh_btn.connect("clicked", lambda _: self.refresh())
        header.append(refresh_btn)

        content.append(header)
        content.append(Gtk.Separator())

        # ── Sektionen (Mixins) ──
        self._build_model_status_section(content)
        self._build_training_history_section(content)
        self._build_strategy_section(content)
        self._build_feature_section(content)
        self._build_combo_section(content)
        self._build_self_improve_section(content)
        self._build_export_section(content)

        scroll.set_child(content)
        self.append(scroll)

    def _on_day_changed(self, combo) -> None:
        day = combo.get_active_id()
        if day:
            self._draw_day = day
            self.refresh()

    def refresh(self) -> None:
        if self._loading:
            return
        self._loading = True
        self._spinner.set_visible(True)
        self._spinner.start()

        draw_day = self._draw_day

        def worker():
            data = {}
            try:
                if self.api_client:
                    data = self._load_data_api(draw_day)
                elif self.db:
                    data = self._load_data_db(draw_day)
            except Exception as e:
                logger.error(f"ML-Dashboard Daten laden: {e}")
            GLib.idle_add(self._on_data_loaded, data)

        threading.Thread(target=worker, daemon=True).start()

    def _load_data_db(self, draw_day: str) -> dict:
        """Standalone-Fallback: Minimale Daten ohne core-Imports."""
        # Ohne Server-Verbindung können wir kaum ML-Daten anzeigen
        data = {"draw_day": draw_day}
        data["model_ready"] = {}
        data["confidence"] = 0
        data["models"] = []
        data["training_runs"] = []
        data["strategy_perf"] = []
        data["combo_perf"] = []
        data["improve_runs"] = []
        data["improve_stats"] = {}
        data["feature_importance"] = {}
        return data

    def _load_data_api(self, draw_day: str) -> dict:
        """Client: Alle ML-Daten via API laden."""
        data = {"draw_day": draw_day}
        try:
            raw = self.api_client.ml_status()
            # Transform: API returns {rf_saturday: {model_type, accuracy, ...}}
            # UI expects model_ready={rf: True, ...} and models=[{model_type, ...}]
            model_ready = {}
            models = []
            for key, info in raw.items():
                if not isinstance(info, dict):
                    continue
                if info.get("draw_day") != draw_day:
                    continue
                mtype = info.get("model_type", "")
                model_ready[mtype] = True
                models.append(info)
            data["model_ready"] = model_ready
            data["models"] = models
        except Exception as e:
            logger.warning(f"ML-Status laden fehlgeschlagen: {e}")
            data["model_ready"] = {}
            data["models"] = []
        try:
            resp = self.api_client.strategy_performance(draw_day)
            data["strategy_perf"] = resp.get("performance", []) if isinstance(resp, dict) else []
        except Exception as e:
            logger.warning(f"Strategie-Performance laden fehlgeschlagen: {e}")
            data["strategy_perf"] = []
        try:
            resp = self.api_client.combo_status(draw_day)
            data["combo_perf"] = resp.get("status", []) if isinstance(resp, dict) else []
        except Exception as e:
            logger.warning(f"Combo-Status laden fehlgeschlagen: {e}")
            data["combo_perf"] = []
        try:
            resp = self.api_client.training_history(draw_day, limit=50)
            data["training_runs"] = resp.get("history", []) if isinstance(resp, dict) else []
        except Exception as e:
            logger.warning(f"Training-History laden fehlgeschlagen: {e}")
            data["training_runs"] = []
        try:
            resp = self.api_client.self_improve_history(draw_day)
            data["improve_runs"] = resp.get("runs", []) if isinstance(resp, dict) else []
            data["improve_stats"] = resp.get("stats", {}) if isinstance(resp, dict) else {}
        except Exception as e:
            logger.warning(f"Self-Improvement-History laden fehlgeschlagen: {e}")
            data["improve_runs"] = []
        data["feature_importance"] = {}
        return data

    def _on_data_loaded(self, data: dict) -> bool:
        self._loading = False
        self._spinner.stop()
        self._spinner.set_visible(False)
        self._ml_data = data
        self.mark_refreshed()

        # Dispatch an Mixins
        self._update_model_status(data)
        self._update_training_history(data)
        self._update_strategy_comparison(data)
        self._update_feature_importance(data)
        self._update_combo_evaluation(data)
        self._update_self_improvement(data)

        return False

    def cleanup(self) -> None:
        super().cleanup()
