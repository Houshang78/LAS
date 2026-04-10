"""Generator-Seite: Performance Mixin."""

import threading
from datetime import date, datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_analyzer.ui.widgets.help_button import HelpButton
try:
    from lotto_analyzer.ui.widgets.speak_button import SpeakButton
except ImportError:
    SpeakButton = None

logger = get_logger("generator.performance")



try:
    from lotto_analyzer.ui.pages.generator.page import STRATEGY_COLORS, _apply_css
except ImportError:
    STRATEGY_COLORS = {}
    def _apply_css(w, c): pass

from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config

try:
    from lotto_common.models.generation import Strategy, GenerationResult
except ImportError:
    from enum import Enum
    from dataclasses import dataclass, field
    class Strategy(Enum):
        HOT = "hot"; COLD = "cold"; MIXED = "mixed"; ML = "ml"
        AI = "ai"; AVOID = "avoid"; ENSEMBLE = "ensemble"
    @dataclass
    class GenerationResult:
        numbers: list = field(default_factory=list)
        super_number: int = 0; strategy: str = ""
        reasoning: str = ""; confidence: float = 0.0
        bonus_numbers: list = field(default_factory=list)
        number_reasons: dict = field(default_factory=dict)




class PerformanceMixin1:
    """Teil 1 von PerformanceMixin."""

    def _build_performance_section(self) -> None:
        perf_group = Adw.PreferencesGroup(
            title=_("Strategie-Performance (Historie)"),
            description=_("Wie gut treffen die einzelnen Strategien?"),
        )
        perf_group.set_header_suffix(
            HelpButton(_("Historische Trefferquote pro Strategie ueber alle vergangenen Vorhersagen."))
        )
        self._content.append(perf_group)

        # Performance laden Button
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )

        self._perf_btn = Gtk.Button(label=_("Performance anzeigen"))
        self._perf_btn.set_tooltip_text(_("Zeigt die Trefferquote jeder Strategie"))
        self._perf_btn.add_css_class("flat")
        self._perf_btn.set_icon_name("view-list-symbolic")
        self._perf_btn.connect("clicked", self._on_show_performance)
        btn_box.append(self._perf_btn)

        self._ai_analysis_btn = Gtk.Button(label=_("AI-Analyse"))
        self._ai_analysis_btn.set_tooltip_text(_("AI bewertet die generierten Tipps und gibt Empfehlungen"))
        self._ai_analysis_btn.add_css_class("flat")
        self._ai_analysis_btn.set_icon_name("dialog-information-symbolic")
        self._ai_analysis_btn.connect("clicked", self._on_ai_analysis)
        btn_box.append(self._ai_analysis_btn)

        # SpeakButton für AI-Analyse-Ergebnis vorlesen
        self._ai_speak_btn = SpeakButton(config_manager=self.config_manager)
        btn_box.append(self._ai_speak_btn)

        perf_group.add(btn_box)

        # Performance-Container
        self._perf_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4,
        )
        self._perf_frame = Gtk.Frame()
        self._perf_frame.set_child(self._perf_box)
        self._perf_frame.set_visible(False)
        self._content.append(self._perf_frame)

        # AI-Analyse Ergebnis
        self._ai_analysis_label = Gtk.Label()
        self._ai_analysis_label.set_wrap(True)
        self._ai_analysis_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._ai_analysis_label.set_xalign(0)
        self._ai_analysis_label.set_selectable(True)
        self._ai_analysis_label.set_margin_top(8)
        self._ai_analysis_label.set_margin_bottom(8)
        self._ai_analysis_label.set_margin_start(12)
        self._ai_analysis_label.set_margin_end(12)
        self._ai_analysis_label.set_visible(False)
        self._content.append(self._ai_analysis_label)

        # ── Auto-Generate Status ──
        auto_group = Adw.PreferencesGroup(
            title=_("Auto-Generierung"),
            description=_("Automatischer Crawl→Train→Generate Zyklus"),
        )
        self._content.append(auto_group)

        # Status-Label
        self._auto_gen_status = Adw.ActionRow(title=_("Letzte Auto-Generierung"))
        self._auto_gen_status.set_subtitle(_("Wird geladen..."))
        self._auto_gen_status.add_prefix(
            Gtk.Image.new_from_icon_name("emblem-system-symbolic")
        )
        auto_group.add(self._auto_gen_status)

        # Adaptive Count Status
        self._adaptive_row = Adw.ActionRow(title=_("Adaptive Anzahl"))
        self._adaptive_row.set_subtitle(_("Wird geladen..."))
        self._adaptive_row.add_prefix(
            Gtk.Image.new_from_icon_name("view-refresh-symbolic")
        )
        auto_group.add(self._adaptive_row)

        # Woche-zu-Woche Trend Container
        self._auto_trend_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4,
        )
        self._auto_trend_frame = Gtk.Frame()
        self._auto_trend_frame.set_child(self._auto_trend_box)
        self._auto_trend_frame.set_visible(False)
        self._content.append(self._auto_trend_frame)

        # Auto-Generate Button (manueller Trigger)
        auto_btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
        )
        auto_btn_box.set_margin_top(8)

        self._auto_gen_btn = Gtk.Button(label=_("Auto-Generate jetzt"))
        self._auto_gen_btn.set_tooltip_text(_("Startet sofortige automatische Generierung für den nächsten Ziehungstag"))
        self._auto_gen_btn.add_css_class("suggested-action")
        self._auto_gen_btn.add_css_class("pill")
        self._auto_gen_btn.connect("clicked", self._on_auto_generate_trigger)
        self.register_readonly_button(self._auto_gen_btn)
        auto_btn_box.append(self._auto_gen_btn)

        self._auto_gen_spinner = Gtk.Spinner()
        self._auto_gen_spinner.set_visible(False)
        auto_btn_box.append(self._auto_gen_spinner)

        auto_group.add(auto_btn_box)

        self._auto_gen_result = Gtk.Label(label="")
        self._auto_gen_result.add_css_class("dim-label")
        self._auto_gen_result.set_wrap(True)
        auto_group.add(self._auto_gen_result)

        # Initial Auto-Status laden
        GLib.idle_add(self._refresh_auto_gen_status)

    # ══════════════════════════════════════════════
    # Auto-Generate Status & Trigger
    # ══════════════════════════════════════════════

    def _refresh_auto_gen_status(self) -> bool:
        """Auto-Generate Status vom Server laden."""
        if not self.api_client:
            self._auto_gen_status.set_subtitle(_("Serververbindung erforderlich"))
            return False

        def worker():
            try:
                data = self.api_client.auto_generate_status()
                GLib.idle_add(self._update_auto_gen_ui, data)
            except Exception as e:
                GLib.idle_add(
                    self._auto_gen_status.set_subtitle,
                    f"Fehler: {e}",
                )
        threading.Thread(target=worker, daemon=True).start()
        return False

    def _update_auto_gen_ui(self, data: dict) -> bool:
        """Auto-Generate UI mit Status-Daten aktualisieren."""
        draw_day = self._get_draw_day().value
        day_data = data.get(draw_day, {})

        latest = day_data.get("latest_draw_date")
        total = day_data.get("total_predictions", 0)

        if latest and total > 0:
            strategies = day_data.get("strategies", [])
            strat_info = ", ".join(
                f"{s['strategy']}: {s['count']}" for s in strategies
            )
            self._auto_gen_status.set_subtitle(
                f"{latest}: {total} Tips ({strat_info})"
            )
        else:
            self._auto_gen_status.set_subtitle(_("Keine Predictions vorhanden"))

        # Woche-zu-Woche Trend laden
        self._load_weekly_trend(draw_day)

        # Adaptive Count laden
        self._load_adaptive_count(draw_day)
        return False

    def _load_adaptive_count(self, draw_day: str) -> None:
        """Adaptive-Count-Status via API laden."""
        if not self.api_client:
            return

        def worker():
            try:
                data = self.api_client.get_adaptive_count(draw_day)
                GLib.idle_add(self._update_adaptive_ui, data)
            except Exception as e:
                logger.warning(f"Adaptive-Count laden fehlgeschlagen: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _update_adaptive_ui(self, data: dict) -> bool:
        """Adaptive-Count im UI anzeigen."""
        current = data.get("current_count", 170)
        direction = data.get("direction", "stable")
        avg = data.get("avg_recent", 0)
        d5 = data.get("draws_until_5plus")

        arrows = {"increase": "↑", "decrease": "↓", "stable": "→"}
        arrow = arrows.get(direction, "→")

        d5_str = f" | 5+ in {d5} Zieh." if d5 is not None else ""
        self._adaptive_row.set_subtitle(
            f"{current}/Strategie {arrow} (avg {avg:.2f}){d5_str}"
        )
        return False

    def _load_weekly_trend(self, draw_day: str) -> None:
        """Woche-zu-Woche Performance-Trend laden."""
        def worker():
            try:
                if self.app_mode == "client" and self.api_client:
                    perf_data = self.api_client.strategy_performance(draw_day)
                    perf_list = perf_data.get("performance", [])
                elif self.db:
                    perf_list = self.db.get_strategy_performance(draw_day)
                else:
                    perf_list = []
                GLib.idle_add(self._update_trend_ui, perf_list)
            except Exception as e:
                logger.warning(f"Trend-Daten laden fehlgeschlagen: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _update_trend_ui(self, perf_list: list) -> bool:
        """Trend-Tabelle mit Performance-Daten befuellen."""
        while self._auto_trend_box.get_first_child():
            self._auto_trend_box.remove(self._auto_trend_box.get_first_child())

        if not perf_list:
            self._auto_trend_frame.set_visible(False)
            return False

        self._auto_trend_frame.set_visible(True)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_start(8)
        header.set_margin_end(8)
        header.set_margin_top(4)
        for text, width in [("Strategie", 120), ("Ø Treffer", 80),
                            ("Predictions", 80), ("Gewinne", 60)]:
            lbl = Gtk.Label(label=text)
            lbl.add_css_class("heading")
            lbl.set_size_request(width, -1)
            lbl.set_xalign(0)
            header.append(lbl)
        self._auto_trend_box.append(header)
        self._auto_trend_box.append(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        )

        for p in perf_list:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.set_margin_start(8)
            row.set_margin_end(8)
            row.set_margin_top(2)
            row.set_margin_bottom(2)

            strategy = p.get("strategy", "?")
            avg = p.get("avg_matches", 0.0)
            total = p.get("total_predictions", 0)
            wins = p.get("win_count", 0)

            strat_lbl = Gtk.Label(label=strategy)
            strat_lbl.set_size_request(120, -1)
            strat_lbl.set_xalign(0)
            color = STRATEGY_COLORS.get(strategy, "")
            if color:
                _apply_css(strat_lbl, f"label {{ color: {color}; font-weight: bold; }}".encode())
            row.append(strat_lbl)

            avg_lbl = Gtk.Label(label=f"{avg:.2f}")
            avg_lbl.set_size_request(80, -1)
            avg_lbl.set_xalign(0)
            row.append(avg_lbl)

            total_lbl = Gtk.Label(label=str(total))
            total_lbl.set_size_request(80, -1)
            total_lbl.set_xalign(0)
            row.append(total_lbl)

            wins_lbl = Gtk.Label(label=str(wins))
            wins_lbl.set_size_request(60, -1)
            wins_lbl.set_xalign(0)
            row.append(wins_lbl)

            self._auto_trend_box.append(row)

        return False

    def _on_auto_generate_trigger(self, btn: Gtk.Button) -> None:
        """Manueller Auto-Generate Trigger — via Server."""
        if not self.api_client:
            from lotto_analyzer.ui.helpers import show_error_toast
            show_error_toast(self, _("Serververbindung erforderlich"))
            return

        btn.set_sensitive(False)
        self._auto_gen_spinner.set_visible(True)
        self._auto_gen_spinner.start()
        self._auto_gen_result.set_label(_("Generiere ~1000 Schätzungen..."))

        draw_day = self._get_draw_day()

        def worker():
            try:
                data = self.api_client.trigger_auto_generate(draw_day.value)
                task_id = data.get("task_id", "")
                GLib.idle_add(
                    self._on_auto_gen_done,
                    f"Task gestartet: {task_id}", None,
                )
            except Exception as e:
                GLib.idle_add(self._on_auto_gen_done, "", str(e))
        threading.Thread(target=worker, daemon=True).start()

    def _on_auto_gen_done(self, msg: str, error: str | None) -> bool:
        """Auto-Generate abgeschlossen."""
        self._auto_gen_btn.set_sensitive(not self._is_readonly)
        self._auto_gen_spinner.stop()
        self._auto_gen_spinner.set_visible(False)
        if error:
            self._auto_gen_result.set_label(_("Fehler") + f": {error}")
        else:
            self._auto_gen_result.set_label(msg)
            self._refresh_auto_gen_status()
        return False

    # ══════════════════════════════════════════════
    # Performance
    # ══════════════════════════════════════════════

    def _on_show_performance(self, btn) -> None:
        if self.app_mode == "client" and self.api_client:
            draw_day = self._get_draw_day()

            def worker():
                try:
                    data = self.api_client.strategy_performance(draw_day.value)
                    perf = data.get("performance", [])
                    GLib.idle_add(self._show_performance_data, perf)
                except Exception as e:
                    GLib.idle_add(
                        self._status_label.set_label, f"Fehler: {e}",
                    )

            threading.Thread(target=worker, daemon=True).start()
            return

        if not self.db:
            self._status_label.set_label(_("Keine Datenbank verfügbar"))
            return

        draw_day = self._get_draw_day()
        perf_data = self.db.get_strategy_performance(draw_day.value)
        self._show_performance_data(perf_data)

    def _show_performance_data(self, perf_data: list[dict]) -> None:
        """Performance-Daten in UI anzeigen."""

        while self._perf_box.get_first_child():
            self._perf_box.remove(self._perf_box.get_first_child())

        self._perf_frame.set_visible(True)

        if not perf_data:
            no_data = Gtk.Label(
                label=_("Noch keine Performance-Daten vorhanden.") + "\n"
                      + _("Generiere Tipps und vergleiche sie mit echten Ziehungen."),
            )
            no_data.add_css_class("dim-label")
            no_data.set_margin_top(16)
            no_data.set_margin_bottom(16)
            self._perf_box.append(no_data)
            return

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_start(8)
        header.set_margin_end(8)
        header.set_margin_top(8)
        for text, width in [
            ("Strategie", 120), ("Vorhersagen", 90),
            ("Ø Treffer", 80), ("Gewinne (3+)", 90), ("Gewichtung", 80),
        ]:
            label = Gtk.Label(label=text)
            label.add_css_class("heading")
            label.set_size_request(width, -1)
            label.set_xalign(0)
            header.append(label)
        self._perf_box.append(header)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._perf_box.append(sep)

        for perf in perf_data:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.set_margin_start(8)
            row.set_margin_end(8)
            row.set_margin_top(4)
            row.set_margin_bottom(4)

            strat_name = perf["strategy"]
            strat_label = Gtk.Label(label=strat_name)
            strat_label.set_size_request(120, -1)
            strat_label.set_xalign(0)
            color = STRATEGY_COLORS.get(strat_name, "")
            if color:
                _apply_css(strat_label, f"label {{ color: {color}; font-weight: bold; }}".encode())
            row.append(strat_label)

            total_label = Gtk.Label(label=str(perf["total_predictions"]))
            total_label.set_size_request(90, -1)
            total_label.set_xalign(0)
            row.append(total_label)

            avg_label = Gtk.Label(label=f"{perf['avg_matches']:.2f}")
            avg_label.set_size_request(80, -1)
            avg_label.set_xalign(0)
            row.append(avg_label)

            win_label = Gtk.Label(label=str(perf["win_count"]))
            win_label.set_size_request(90, -1)
            win_label.set_xalign(0)
            row.append(win_label)

            weight_label = Gtk.Label(label=f"{perf['weight']:.2f}")
            weight_label.set_size_request(80, -1)
            weight_label.set_xalign(0)
            row.append(weight_label)

            self._perf_box.append(row)

    def _on_ai_analysis(self, btn) -> None:
        if not self.db and not self.api_client:
            self._status_label.set_label(_("Keine Datenbank verfügbar"))
            return

        self._ai_analysis_btn.set_sensitive(False)
        self._ai_analysis_label.set_label(_("AI analysiert..."))
        self._ai_analysis_label.set_visible(True)

        draw_day = self._get_draw_day()
        config = self.config_manager.config

        def worker():
            try:
                # Performance-Daten laden (im Worker-Thread, nicht UI-Thread)
                if self.api_client and not self.db:
                    perf_data = self.api_client.strategy_performance(draw_day.value)
                elif self.db:
                    perf_data = self.db.get_strategy_performance(draw_day.value)
                else:
                    perf_data = []

                if not perf_data:
                    GLib.idle_add(self._on_ai_analysis_no_data)
                    return

                if not (config.ai.api_key or config.ai.mode.value == "cli"):
                    GLib.idle_add(self._show_local_analysis, perf_data)
                    return

                perf_text = "\n".join(
                    f"- {p['strategy']}: {p['total_predictions']} Vorhersagen, "
                    f"Ø {p['avg_matches']:.2f} Treffer, "
                    f"{p['win_count']} Gewinne (3+), "
                    f"Gewicht: {p['weight']:.2f}"
                    for p in perf_data
                )

                prompt = (
                    f"Analysiere die Performance der Lotto-Vorhersage-Strategien "
                    f"für {draw_day.value}:\n{perf_text}\n\n"
                    f"Welche Strategie performt am besten und warum? "
                    f"Gib eine kurze Empfehlung (max 3 Saetze)."
                )

                if self.api_client:
                    response = self.api_client.chat(prompt)
                else:
                    response = _("Serververbindung erforderlich für AI-Analyse.")
                GLib.idle_add(self._on_ai_analysis_done, response, None)
            except Exception as e:
                GLib.idle_add(self._on_ai_analysis_done, "", str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ai_analysis_no_data(self) -> bool:
        """Keine Performance-Daten vorhanden."""
        self._ai_analysis_btn.set_sensitive(True)
        self._ai_analysis_label.set_label(
            _("Keine Performance-Daten für AI-Analyse vorhanden.")
        )
        self._ai_analysis_label.set_visible(True)
        return False

