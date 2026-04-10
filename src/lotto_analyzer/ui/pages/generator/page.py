"""Generator-Seite: Batch-Generierung, Vergleich, CSV-Export, Performance."""

from __future__ import annotations

import csv
import io
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from dataclasses import dataclass, field
from enum import Enum

from lotto_common.config import ConfigManager
from lotto_common.i18n import _
from lotto_common.models.draw import DrawDay
from lotto_analyzer.ui.pages.base_page import BasePage

try:
    from lotto_common.models.generation import Strategy, GenerationResult
except ImportError:
    class Strategy(Enum):  # type: ignore[no-redef]
        HOT = "hot"
        COLD = "cold"
        MIXED = "mixed"
        ML = "ml"
        AI = "ai"
        AVOID = "avoid"
        ENSEMBLE = "ensemble"

    @dataclass
    class GenerationResult:  # type: ignore[no-redef]
        numbers: list[int] = field(default_factory=list)
        super_number: int = 0
        strategy: str = ""
        reasoning: str = ""
        confidence: float = 0.0
        bonus_numbers: list[int] = field(default_factory=list)

try:
    from lotto_common.models.generation import ALL_COMBOS, combo_key
except ImportError:
    ALL_COMBOS = [
        ["rf"], ["gb"], ["lstm"],
        ["gb", "rf"], ["lstm", "rf"], ["gb", "lstm"],
        ["gb", "lstm", "rf"],
    ]
    def combo_key(models: list[str]) -> str:  # type: ignore[misc]
        return "+".join(sorted(models))

from lotto_common.models.game_config import GameType, get_config, GAME_CONFIGS
from lotto_common.models.analysis import PredictionRecord
from lotto_analyzer.ui.widgets.number_ball import NumberBallRow
from lotto_analyzer.ui.widgets.speak_button import SpeakButton
from lotto_analyzer.ui.widgets.improvement_report import ImprovementReportPanel
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from lotto_analyzer.ui.widgets.help_button import HelpButton
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
try:
    from lotto_analyzer.ui.widgets.improvement_report import ImprovementReportPanel
except ImportError:
    ImprovementReportPanel = None
from lotto_analyzer.ui.widgets.help_button import HelpButton
try:
    from lotto_analyzer.ui.widgets.speak_button import SpeakButton
except ImportError:
    SpeakButton = None

logger = get_logger("generator_page")

# Ziehungsdatum-Berechnung (unabhaengig von core.generator)
_DRAW_OVER_HOUR = {
    DrawDay.WEDNESDAY: 19, DrawDay.SATURDAY: 20,
    DrawDay.TUESDAY: 21, DrawDay.FRIDAY: 21,
}

def _get_next_draw_date(draw_day: DrawDay) -> date:
    """Nächsten Ziehungstag ab heute berechnen."""
    weekday_map = {
        DrawDay.SATURDAY: 5, DrawDay.WEDNESDAY: 2,
        DrawDay.TUESDAY: 1, DrawDay.FRIDAY: 4,
    }
    today = date.today()
    target_weekday = weekday_map.get(draw_day, 5)
    days_ahead = (target_weekday - today.weekday()) % 7
    if days_ahead == 0:
        if datetime.now().hour >= _DRAW_OVER_HOUR.get(draw_day, 20):
            days_ahead = 7
    return today + timedelta(days=days_ahead)

_css_provider_cache: dict[str, Gtk.CssProvider] = {}
_css_display_initialized: set[str] = set()

def _apply_css(widget: Gtk.Widget, css_str: str) -> None:
    """CSS auf ein Widget anwenden — cached pro CSS-String, einmal pro Display registriert."""
    import hashlib
    css_bytes = css_str.encode() if isinstance(css_str, str) else css_str
    css_key = hashlib.md5(css_bytes).hexdigest()[:8]
    cls_name = f"css_{css_key}"

    # Provider nur einmal pro eindeutigem CSS-String erstellen und registrieren
    if cls_name not in _css_provider_cache:
        body = _extract_css_body(css_str)
        scoped_css = f".{cls_name} {{ {body} }}"
        provider = Gtk.CssProvider()
        provider.load_from_data(scoped_css.encode())
        _css_provider_cache[cls_name] = provider

    # Provider nur einmal pro Display registrieren
    display = widget.get_display()
    display_key = f"{id(display)}:{cls_name}"
    if display_key not in _css_display_initialized:
        Gtk.StyleContext.add_provider_for_display(
            display, _css_provider_cache[cls_name], Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        _css_display_initialized.add(display_key)

    widget.add_css_class(cls_name)

def _extract_css_body(css_str: str) -> str:
    """CSS-Body aus 'selector { body }' extrahieren."""
    if isinstance(css_str, bytes):
        css_str = css_str.decode()
    start = css_str.find("{")
    end = css_str.rfind("}")
    if start >= 0 and end > start:
        return css_str[start + 1:end].strip()
    return css_str

# Strategie-Farben (CSS rgba Strings)
STRATEGY_COLORS = {
    "hot": "rgba(220,50,50,0.85)",
    "cold": "rgba(50,100,220,0.85)",
    "mixed": "rgba(50,160,50,0.85)",
    "ml": "rgba(220,140,20,0.85)",
    "ai": "rgba(140,60,200,0.85)",
    "avoid": "rgba(60,180,180,0.85)",
    "ensemble": "rgba(180,150,20,0.85)",
    # Backtest-Strategien
    "backtest_hot": "rgba(220,50,50,0.65)",
    "backtest_cold": "rgba(50,100,220,0.65)",
    "backtest_mixed": "rgba(50,160,50,0.65)",
    "backtest_ml": "rgba(220,140,20,0.65)",
    "backtest_avoid": "rgba(60,180,180,0.65)",
    "backtest_ensemble": "rgba(180,150,20,0.65)",
    "backtest_bayes": "rgba(200,100,50,0.65)",
    "backtest_markov": "rgba(100,50,200,0.65)",
}


from lotto_analyzer.ui.pages.generator.backtest import BacktestMixin
from lotto_analyzer.ui.pages.generator.comparison import ComparisonMixin
from lotto_analyzer.ui.pages.generator.generation import GenerationMixin
from lotto_analyzer.ui.pages.generator.ml_section import MlSectionMixin
from lotto_analyzer.ui.pages.generator.ml_training import MlTrainingMixin
from lotto_analyzer.ui.pages.generator.performance import PerformanceMixin
from lotto_analyzer.ui.pages.generator.results import ResultsMixin
from lotto_analyzer.ui.pages.generator.stored import StoredMixin

DAY_LABELS = {
    "saturday": "Samstag",
    "wednesday": "Mittwoch",
    "tuesday": "Dienstag",
    "friday": "Freitag",
}


class GeneratorPage(BacktestMixin, ComparisonMixin, GenerationMixin, MlSectionMixin, MlTrainingMixin, PerformanceMixin, ResultsMixin, StoredMixin, BasePage):
    """Zahlen-Generator mit Batch-Modus, Vergleich und Performance-Tracking."""

    _STRATEGY_MAP = [
        Strategy.HOT,
        Strategy.COLD,
        Strategy.MIXED,
        Strategy.ML,
        Strategy.AI,
        Strategy.AVOID,
        Strategy.ENSEMBLE,
    ]

    _STRATEGY_LABELS = [
        _("Hot Numbers"),
        _("Cold Numbers"),
        _("Mixed"),
        _("ML-Vorhersage"),
        _("AI-Empfehlung"),
        _("Vermeidung"),
        _("Ensemble (Alle)"),
        _("Alle Strategien"),
    ]

    # Display-Name für jede Strategie (Checkbox-Labels)
    _STRATEGY_DISPLAY = {
        "hot": _("Hot Numbers"),
        "cold": _("Cold Numbers"),
        "mixed": _("Mixed"),
        "ml": _("ML-Vorhersage"),
        "ai": _("AI-Empfehlung"),
        "avoid": _("Vermeidung"),
        "ensemble": _("Ensemble (Alle)"),
        # Backtest-Strategien
        "backtest_hot": _("BT: Hot"),
        "backtest_cold": _("BT: Cold"),
        "backtest_mixed": _("BT: Mixed"),
        "backtest_ml": _("BT: ML"),
        "backtest_avoid": _("BT: Avoid"),
        "backtest_ensemble": _("BT: Ensemble"),
        "backtest_bayes": _("BT: Bayes"),
        "backtest_markov": _("BT: Markov"),
    }

    _STRATEGY_SUBTITLES = {
        "hot": _("Häufige Zahlen gewichtet"),
        "cold": _("Seltene Zahlen bevorzugt"),
        "mixed": _("50% heiss + 50% kalt"),
        "ml": _("Machine-Learning-Modell"),
        "ai": _("Claude AI analysiert"),
        "avoid": _("Unbeliebte Zahlen (weniger Teiler)"),
        "ensemble": _("Alle Strategien kombiniert"),
    }

    _DAY_LABELS = {"saturday": _("Samstag"), "wednesday": _("Mittwoch"), "tuesday": _("Dienstag"), "friday": _("Freitag")}
    _DAY_SHORT  = {"saturday": "Sa", "wednesday": "Mi", "tuesday": "Di", "friday": "Fr"}

    POLL_TIMEOUT_SECONDS = 1800   # 30 Minuten max Polling
    PREDICTION_LOAD_LIMIT = 1000  # Max Predictions pro Lade-Vorgang
    DEFAULT_PAGE_SIZE = 20        # Standard-Seitengröße Prediction-Liste

    def __init__(self, config_manager: ConfigManager, db: Database | None, app_mode: str, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager=config_manager, db=db, app_mode=app_mode, api_client=api_client,
                         app_db=app_db, backtest_db=backtest_db)
        self._generating = False
        # Server handles all ML/AI — these are None in client mode
        self._generator = None
        self._ml_engine = None
        self._model_trainer = None
        self._ai_analyst = None
        self._combo_evaluator = None
        self._results: list[GenerationResult] = []
        self._result_strategies: list[str] = []
        self._ai_top_picks: set[int] = set()
        self._current_draw_date: str = ""
        self._prediction_dates: list[str] = []
        self._prediction_date_idx: int = 0
        self._game_type: GameType = GameType.LOTTO6AUS49
        self._config = get_config(self._game_type)
        self._audio_service = None
        self._load_generation: int = 0  # Guard gegen veraltete async-Antworten

        self._init_ai()
        self._build_ui()
        self._init_audio()
        self._restore_state()

    def cleanup(self) -> None:
        """Timer und WS-Listener aufräumen."""
        super().cleanup()
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("task_update", self._on_ws_generate_task)
            ui_ws_manager.off("task_update", self._on_ws_self_improve_task)
            ui_ws_manager.off("task_update", self._on_ws_training_task)
        except Exception:
            pass

    def _init_ai(self) -> None:
        """AI-Analyst initialisieren — läuft nur auf dem Server."""
        # AI-Analyst wird nicht mehr im UI instanziiert, alles via API
        self._ai_analyst = None

    def _init_audio(self) -> None:
        """AudioService für AI-Analyse-Vorlesen initialisieren."""
        try:
            config = self.config_manager.config
            if config.audio.tts_enabled:
                from lotto_analyzer.ui.audio_service import AudioService
                self._audio_service = AudioService(
                    tts_lang=config.audio.tts_language,
                    openai_api_key=config.audio.openai_api_key,
                )
                self._ai_speak_btn.audio_service = self._audio_service
        except Exception as e:
            logger.warning(f"Audio-Init fehlgeschlagen: {e}")

    def _build_ui(self) -> None:
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        self.append(scrolled)

        clamp = Adw.Clamp(maximum_size=1000)
        scrolled.set_child(clamp)

        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._content.set_margin_top(24)
        self._content.set_margin_bottom(24)
        self._content.set_margin_start(24)
        self._content.set_margin_end(24)
        clamp.set_child(self._content)

        title = Gtk.Label(label=_("Zahlen-Generator"))
        title.add_css_class("title-1")
        self._content.append(title)

        subtitle = Gtk.Label(
            label=_("Batch-Generierung mit Strategie-Vergleich"),
        )
        subtitle.add_css_class("dim-label")
        self._content.append(subtitle)

        # ── Oberer Bereich: Generierung ──
        self._build_generation_section()

        # ── Ensemble-Gewichte ──
        self._build_weights_section()

        # ── ML-Modelle Sektion ──
        self._build_ml_models_section()

        # ── Modell-Kombinationen ──
        self._build_combo_section()

        # ── Mittlerer Bereich: Ergebnis-Tabelle ──
        self._build_results_section()

        # ── Unterer Bereich: Vergleich mit echter Ziehung ──
        self._build_comparison_section()

        # ── Performance-Sektion ──
        self._build_performance_section()

        # ── ML-Feedback & Tuning ──
        self._build_ml_feedback_section()

        # ── ML-Training Steuerung (AI-gesteuert) ──
        self._build_ml_training_section()

        # ── Gespeicherte Vorhersagen (Browse + Cleanup) ──
        self._build_stored_predictions_section()

        # ── ML Self-Improvement ──
        self._build_self_improve_section()

        # ── AI-Analyse Panel ──
        self._ai_panel = AIPanel(
            ai_analyst=self._ai_analyst,
            api_client=self.api_client,
            title=_("AI-Analyse"),
            config_manager=self.config_manager,
            db=self.db,
            page="generator",
            app_db=self.app_db,
        )
        self._content.append(self._ai_panel)

