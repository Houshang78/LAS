"""Generator-Seite: Results Mixin."""

import csv
import io
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

logger = get_logger("generator.results")



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


class ResultsMixin:
    """Mixin für GeneratorPage: Results."""

    # ══════════════════════════════════════════════
    # Ergebnis-Tabelle
    # ══════════════════════════════════════════════

    def _build_results_section(self) -> None:
        # Header mit CSV-Export Button
        header_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )
        header_box.set_margin_top(8)

        self._results_label = Gtk.Label(label=_("Ergebnisse"))
        self._results_label.add_css_class("title-2")
        self._results_label.set_hexpand(True)
        self._results_label.set_xalign(0)
        header_box.append(self._results_label)

        # Prev/Next Navigation für ältere Predictions
        self._prev_date_btn = Gtk.Button()
        self._prev_date_btn.set_icon_name("go-previous-symbolic")
        self._prev_date_btn.add_css_class("pill")
        self._prev_date_btn.add_css_class("flat")
        self._prev_date_btn.set_tooltip_text(_("Ältere Vorhersagen laden"))
        self._prev_date_btn.set_sensitive(False)
        self._prev_date_btn.connect("clicked", self._on_prev_date)
        header_box.append(self._prev_date_btn)

        self._next_date_btn = Gtk.Button()
        self._next_date_btn.set_icon_name("go-next-symbolic")
        self._next_date_btn.add_css_class("pill")
        self._next_date_btn.add_css_class("flat")
        self._next_date_btn.set_tooltip_text(_("Neuere Vorhersagen laden"))
        self._next_date_btn.set_sensitive(False)
        self._next_date_btn.connect("clicked", self._on_next_date)
        header_box.append(self._next_date_btn)

        # Tag-Wechsel-Button (SA↔MI bzw. DI↔FR)
        self._day_toggle = Gtk.Button()
        self._day_toggle.set_tooltip_text(_("Zwischen Ziehungstagen wechseln"))
        self._day_toggle.add_css_class("pill")
        self._day_toggle.connect("clicked", self._on_day_toggle)
        self._update_day_toggle_label()
        header_box.append(self._day_toggle)

        header_box.append(
            HelpButton(_("Generierte Tipp-Reihen mit Strategie, Zahlen, Superzahl und Konfidenz-Score."))
        )

        # Anzeige-Auswahl
        self._display_combo = Gtk.ComboBoxText()
        for label in ["20", "50", "100", "200", "500", "1000", "Alle"]:
            self._display_combo.append_text(label)
        self._display_combo.set_active(0)
        self._display_combo.connect("changed", self._on_display_count_changed)

        display_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
        )
        display_box.set_valign(Gtk.Align.CENTER)
        display_lbl = Gtk.Label(label=_("Anzeige:"))
        display_lbl.add_css_class("dim-label")
        display_box.append(display_lbl)
        display_box.append(self._display_combo)
        header_box.append(display_box)

        # Gruppiert/Alle Toggle
        self._group_toggle = Gtk.ToggleButton(label=_("Gruppiert"))
        self._group_toggle.set_active(True)
        self._group_toggle.set_tooltip_text(_("Ergebnisse nach Strategie gruppieren oder als flache Liste zeigen"))
        self._group_toggle.add_css_class("flat")
        self._group_toggle.connect("toggled", self._on_group_toggle_changed)
        header_box.append(self._group_toggle)

        self._csv_btn = Gtk.Button(label=_("CSV-Export"))
        self._csv_btn.set_icon_name("document-save-symbolic")
        self._csv_btn.add_css_class("flat")
        self._csv_btn.set_sensitive(False)
        self._csv_btn.set_tooltip_text(_("Exportiert die generierten Tipps als CSV-Datei zum Ausdrucken oder Weitergeben."))
        self._csv_btn.connect("clicked", self._on_export_csv)
        header_box.append(self._csv_btn)

        self._content.append(header_box)

        # Ergebnis-Container mit ScrolledWindow
        self._results_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4,
        )
        self._results_scroll = Gtk.ScrolledWindow()
        self._results_scroll.set_policy(
            Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC,
        )
        self._results_scroll.set_child(self._results_box)
        self._results_scroll.set_min_content_height(80)
        self._results_scroll.set_max_content_height(600)

        self._results_frame = Gtk.Frame()
        self._results_frame.set_child(self._results_scroll)
        self._content.append(self._results_frame)

        # Placeholder mit "Letzte laden" Button
        self._results_placeholder_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8,
            halign=Gtk.Align.CENTER,
        )
        self._results_placeholder_box.set_margin_top(24)
        self._results_placeholder_box.set_margin_bottom(24)

        self._results_placeholder = Gtk.Label(
            label=_("Noch keine Tipps generiert.") + "\n"
                  + _("Wähle Strategie und Anzahl, dann klicke 'Tipps generieren'."),
        )
        self._results_placeholder.add_css_class("dim-label")
        self._results_placeholder_box.append(self._results_placeholder)

        self._reload_btn = Gtk.Button(label=_("Letzte Ergebnisse laden"))
        self._reload_btn.set_tooltip_text(_("Laedt die zuletzt generierten Ergebnisse aus der Datenbank"))
        self._reload_btn.set_icon_name("document-open-recent-symbolic")
        self._reload_btn.add_css_class("pill")
        self._reload_btn.connect("clicked", self._on_reload_last_results)
        self._results_placeholder_box.append(self._reload_btn)

        self._results_box.append(self._results_placeholder_box)

        # Status-Label
        self._status_label = Gtk.Label()
        self._status_label.add_css_class("dim-label")
        self._status_label.set_margin_top(4)
        self._content.append(self._status_label)

    def _get_display_limit(self) -> int:
        """Aktuelle Anzeige-Grenze aus ComboBox lesen."""
        text = self._display_combo.get_active_text()
        if text == "Alle":
            return 999999
        return int(text)

    def _on_display_count_changed(self, combo) -> None:
        """Anzeige-Auswahl geändert — Tabelle neu aufbauen."""
        self._populate_results()

    def _on_group_toggle_changed(self, button: Gtk.ToggleButton) -> None:
        """Gruppiert/Alle Ansicht umschalten."""
        button.set_label(_("Gruppiert") if button.get_active() else _("Alle"))
        self._populate_results()

    def _populate_results(self) -> None:
        """Ergebnis-Tabelle mit generierten Tipps befuellen — gruppiert nach Strategie."""
        self._update_results_header()

        # Clear
        while self._results_box.get_first_child():
            self._results_box.remove(self._results_box.get_first_child())

        if not self._results:
            self._results_box.append(self._results_placeholder_box)
            self._csv_btn.set_sensitive(False)
            return

        self._csv_btn.set_sensitive(True)

        limit = self._get_display_limit()
        total = len(self._results)

        # Gruppierung nach Strategie
        grouped = self._get_grouped_results() if self._is_grouped_view() else None

        if grouped and len(grouped) > 1:
            self._populate_results_grouped(grouped, limit)
        else:
            self._populate_results_flat(limit)

        shown = min(limit, total)
        display_info = f"{shown} von {total}" if shown < total else str(total)
        strategies_used = len(set(self._result_strategies)) if self._result_strategies else 1
        strat_info = f" ({strategies_used} Strategien)" if strategies_used > 1 else ""
        self._status_label.set_label(
            f"{display_info} Tipps angezeigt für {self._current_draw_date} "
            f"({total} generiert{strat_info})"
        )

    def _is_grouped_view(self) -> bool:
        """Prüfen ob gruppierte Ansicht aktiv ist."""
        return hasattr(self, '_group_toggle') and self._group_toggle.get_active()

    def _get_grouped_results(self) -> dict[str, list[tuple[int, GenerationResult]]]:
        """Ergebnisse nach Strategie gruppieren."""
        grouped: dict[str, list[tuple[int, GenerationResult]]] = {}
        for i, result in enumerate(self._results):
            strat = self._result_strategies[i] if i < len(self._result_strategies) else result.strategy
            grouped.setdefault(strat, []).append((i, result))
        return grouped

    def _populate_results_flat(self, limit: int) -> None:
        """Flache Ergebnis-Tabelle (sortiert nach Confidence)."""
        total = len(self._results)
        shown = min(limit, total)

        row_h = 30
        h = min((shown + 1) * row_h, 600)
        self._results_scroll.set_min_content_height(h)
        self._results_scroll.set_max_content_height(600)

        bonus_header = self._config.bonus_name[:2].upper()
        header = self._create_result_row_widget(
            "#", "Strategie", "Zahlen", bonus_header, "Konfidenz", is_header=True,
        )
        self._results_box.append(header)
        self._results_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        ai_picks = getattr(self, '_ai_top_picks', set())

        for i in range(shown):
            result = self._results[i]
            strategy_name = self._result_strategies[i] if i < len(self._result_strategies) else result.strategy
            is_top_pick = i in ai_picks
            prefix = "\u2605 " if is_top_pick else ""
            # Bonus: EJ zeigt Eurozahlen, 6aus49 zeigt Superzahl
            if result.bonus_numbers:
                bonus_str = ",".join(str(n) for n in sorted(result.bonus_numbers))
            else:
                bonus_str = str(result.super_number)
            row = self._create_result_row_widget(
                f"{prefix}{i + 1}",
                strategy_name,
                " ".join(f"{n:2d}" for n in sorted(result.numbers)),
                bonus_str,
                f"{result.confidence:.0%}",
                strategy_key=result.strategy,
                is_top_pick=is_top_pick,
            )
            self._results_box.append(row)

    def _populate_results_grouped(
        self, grouped: dict[str, list[tuple[int, GenerationResult]]], limit: int,
    ) -> None:
        """Gruppierte Ergebnis-Tabelle mit Section-Headers pro Strategie."""
        bonus_header = self._config.bonus_name[:2].upper()
        shown_total = 0
        per_strategy_limit = max(limit // len(grouped), 1) if grouped else limit

        row_count = 0
        for strat_name, items in grouped.items():
            # Strategie-Header
            display_name = self._STRATEGY_DISPLAY.get(strat_name, strat_name)
            avg_conf = sum(r.confidence for _, r in items) / len(items) if items else 0
            section_label = Gtk.Label(
                label=f"{display_name}: {len(items)} Tipps, avg Konfidenz {avg_conf:.0%}",
            )
            section_label.set_xalign(0)
            section_label.set_margin_start(8)
            section_label.set_margin_top(12)
            section_label.set_margin_bottom(4)
            section_label.add_css_class("heading")

            color = STRATEGY_COLORS.get(strat_name, "")
            if color:
                _apply_css(section_label, f"label {{ color: {color}; }}".encode())

            self._results_box.append(section_label)

            # Header-Zeile
            header = self._create_result_row_widget(
                "#", "Strategie", "Zahlen", bonus_header, "Konfidenz", is_header=True,
            )
            self._results_box.append(header)
            self._results_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            row_count += 2

            ai_picks = getattr(self, '_ai_top_picks', set())
            shown_in_strat = 0
            for idx, (orig_i, result) in enumerate(items):
                if shown_total >= limit:
                    break
                is_top_pick = orig_i in ai_picks
                prefix = "\u2605 " if is_top_pick else ""
                # Bonus: EJ zeigt Eurozahlen, 6aus49 zeigt Superzahl
                if result.bonus_numbers:
                    bonus_str = ",".join(str(n) for n in sorted(result.bonus_numbers))
                else:
                    bonus_str = str(result.super_number)
                row = self._create_result_row_widget(
                    f"{prefix}{idx + 1}",
                    strat_name,
                    " ".join(f"{n:2d}" for n in sorted(result.numbers)),
                    bonus_str,
                    f"{result.confidence:.0%}",
                    strategy_key=result.strategy,
                    is_top_pick=is_top_pick,
                )
                self._results_box.append(row)
                shown_total += 1
                shown_in_strat += 1
                row_count += 1

            # Strategie-Separator
            self._results_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            row_count += 1

        h = min(row_count * 30, 600)
        self._results_scroll.set_min_content_height(max(h, 80))
        self._results_scroll.set_max_content_height(600)

    def _on_reload_last_results(self, button: Gtk.Button) -> None:
        """Letzte gespeicherte Ergebnisse aus DB/API laden."""
        button.set_sensitive(False)
        draw_day = self._get_draw_day()
        if not draw_day:
            draw_day = DrawDay.SATURDAY

        def worker():
            try:
                # Neuestes Datum für diesen Ziehtag holen
                if self.app_mode == "client" and self.api_client:
                    dates = self.api_client.get_prediction_dates(draw_day.value)
                elif self.db:
                    dates = self.db.get_prediction_dates(draw_day.value)
                else:
                    dates = []
                if not dates:
                    GLib.idle_add(self._on_reload_done, [], None, _("Keine gespeicherten Vorhersagen gefunden."))
                    return
                latest_date = dates[0]
                # Alle Predictions für dieses Datum laden
                if self.app_mode == "client" and self.api_client:
                    data = self.api_client.get_predictions(draw_day.value, latest_date, 0, 1000)
                    items = data.get("predictions", [])
                elif self.db:
                    items = self.db.get_predictions_paginated(draw_day.value, latest_date, 0, 1000)
                else:
                    items = []
                # In GenerationResult konvertieren
                results = []
                strategies = []
                for item in items:
                    nums_str = item.get("numbers", "")
                    nums = [int(n) for n in nums_str.split(",") if n.strip().isdigit()] if isinstance(nums_str, str) else nums_str
                    gr = GenerationResult(
                        numbers=nums,
                        super_number=item.get("super_number", 0),
                        strategy=item.get("strategy", ""),
                        reasoning="",
                        confidence=item.get("ml_confidence", item.get("confidence", 0.0)),
                    )
                    results.append(gr)
                    strategies.append(item.get("strategy", ""))
                GLib.idle_add(self._on_reload_done, results, strategies, latest_date)
            except Exception as e:
                GLib.idle_add(self._on_reload_done, [], None, f"Fehler: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_reload_done(self, results: list, strategies: list | None, info: str) -> bool:
        """Geladene Ergebnisse anzeigen."""
        self._reload_btn.set_sensitive(True)
        if not results:
            self._status_label.set_label(str(info))
            return False
        self._results = results
        self._result_strategies = strategies or [r.strategy for r in results]
        self._current_draw_date = info
        self._compare_btn.set_sensitive(bool(results))
        self._populate_results()
        self._load_prediction_dates()
        return False

    # ── Datums-Navigation (Prev/Next) ──

    def _update_results_header(self) -> None:
        """Header-Label mit aktuellem Datum aktualisieren."""
        if not self._current_draw_date:
            self._results_label.set_label(_("Ergebnisse"))
            return
        try:
            d = date.fromisoformat(self._current_draw_date)
            _short = {0: "Mo", 1: "Di", 2: "Mi", 3: "Do", 4: "Fr", 5: "Sa", 6: "So"}
            weekday = _short.get(d.weekday(), "")
            self._results_label.set_label(
                f"Ergebnisse \u2014 {weekday}, {d.strftime('%d.%m.%Y')}"
            )
        except ValueError:
            self._results_label.set_label(_("Ergebnisse"))

    def _load_prediction_dates(self) -> None:
        """Verfügbare Prediction-Daten im Hintergrund laden."""
        draw_day = self._get_draw_day()

        def worker():
            try:
                if self.app_mode == "client" and self.api_client:
                    dates = self.api_client.get_prediction_dates(draw_day.value)
                elif self.db:
                    dates = self.db.get_prediction_dates(draw_day.value)
                else:
                    dates = []
                GLib.idle_add(self._on_prediction_dates_loaded, dates)
            except Exception as e:
                logger.debug(f"Prediction-Dates laden fehlgeschlagen: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_prediction_dates_loaded(self, dates: list[str]) -> bool:
        """Datums-Liste setzen und Navigation aktualisieren."""
        self._prediction_dates = dates
        # Index auf aktuelles Datum setzen
        if self._current_draw_date in dates:
            self._prediction_date_idx = dates.index(self._current_draw_date)
        else:
            self._prediction_date_idx = 0
        self._update_nav_buttons()
        return False

    def _update_nav_buttons(self) -> None:
        """Prev/Next-Buttons je nach Position aktivieren/deaktivieren."""
        total = len(self._prediction_dates)
        has_dates = total > 0
        # prev = aelter = hoeherer Index
        self._prev_date_btn.set_sensitive(
            has_dates and self._prediction_date_idx < total - 1
        )
        # next = neuer = niedrigerer Index
        self._next_date_btn.set_sensitive(
            has_dates and self._prediction_date_idx > 0
        )

    def _on_prev_date(self, button: Gtk.Button) -> None:
        """Ältere Predictions laden (hoeherer Index)."""
        if self._prediction_date_idx < len(self._prediction_dates) - 1:
            self._prediction_date_idx += 1
            self._current_draw_date = self._prediction_dates[self._prediction_date_idx]
            self._update_results_header()
            self._update_nav_buttons()
            self._load_latest_predictions()

    def _on_next_date(self, button: Gtk.Button) -> None:
        """Neuere Predictions laden (niedrigerer Index)."""
        if self._prediction_date_idx > 0:
            self._prediction_date_idx -= 1
            self._current_draw_date = self._prediction_dates[self._prediction_date_idx]
            self._update_results_header()
            self._update_nav_buttons()
            self._load_latest_predictions()

    def _create_result_row_widget(
        self, num: str, strategy: str, numbers: str,
        sz: str, confidence: str, is_header: bool = False,
        strategy_key: str = "", is_top_pick: bool = False,
    ) -> Gtk.Box:
        """Eine Zeile der Ergebnis-Tabelle erstellen."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(8)
        row.set_margin_end(8)
        row.set_margin_top(4)
        row.set_margin_bottom(4)

        if is_top_pick:
            _apply_css(row, b"box { background: alpha(@accent_color, 0.15); border-radius: 6px; }")

        # #
        num_label = Gtk.Label(label=num)
        num_label.set_size_request(30, -1)
        num_label.set_xalign(1)
        if is_header:
            num_label.add_css_class("heading")
        row.append(num_label)

        # Strategie
        strat_label = Gtk.Label(label=strategy)
        strat_label.set_size_request(120, -1)
        strat_label.set_xalign(0)
        strat_label.set_ellipsize(Pango.EllipsizeMode.END)
        if is_header:
            strat_label.add_css_class("heading")
        elif strategy_key:
            color = STRATEGY_COLORS.get(strategy_key, "")
            if color:
                _apply_css(strat_label, f"label {{ color: {color}; font-weight: bold; }}".encode())
        row.append(strat_label)

        # Zahlen
        nums_label = Gtk.Label(label=numbers)
        nums_label.set_hexpand(True)
        nums_label.set_xalign(0)
        if is_header:
            nums_label.add_css_class("heading")
        else:
            nums_label.add_css_class("monospace")
        row.append(nums_label)

        # SZ
        sz_label = Gtk.Label(label=sz)
        sz_label.set_size_request(30, -1)
        if is_header:
            sz_label.add_css_class("heading")
        row.append(sz_label)

        # Konfidenz
        conf_label = Gtk.Label(label=confidence)
        conf_label.set_size_request(60, -1)
        conf_label.set_xalign(1)
        if is_header:
            conf_label.add_css_class("heading")
        row.append(conf_label)

        return row

    # ══════════════════════════════════════════════
    # Vergleich mit echter Ziehung
    # ══════════════════════════════════════════════

    def _build_comparison_section(self) -> None:
        comp_group = Adw.PreferencesGroup(
            title=_("Vergleich mit echter Ziehung"),
            description=_("Echte Zahlen eingeben oder automatisch holen"),
        )
        comp_group.set_header_suffix(
            HelpButton(_("Vergleicht Vorhersagen mit der tatsaechlichen Ziehung — zeigt Treffer pro Strategie."))
        )
        self._content.append(comp_group)

        # Auto-Fetch Button
        self._fetch_btn = Gtk.Button(label=_("Echte Zahlen holen"))
        self._fetch_btn.set_tooltip_text(_("Aktuelle Ziehungsergebnisse von lottozahlenonline.de holen"))
        self._fetch_btn.set_icon_name("emblem-synchronizing-symbolic")
        self._fetch_btn.add_css_class("flat")
        self._fetch_btn.connect("clicked", self._on_fetch_actual)
        fetch_row = Adw.ActionRow(title=_("Automatisch"))
        fetch_row.set_subtitle(_("Aktuelle Ziehung von lottozahlenonline.de holen"))
        fetch_row.add_suffix(self._fetch_btn)
        fetch_row.set_activatable_widget(self._fetch_btn)
        comp_group.add(fetch_row)

        # Manuelle Eingabe: 6 Zahlen
        manual_group = Adw.PreferencesGroup(
            title=_("Manuelle Eingabe"),
        )
        self._content.append(manual_group)

        self._manual_numbers_row = Adw.ActionRow(
            title=f"Gewinnzahlen ({self._config.main_min}-{self._config.main_max})"
        )
        self._manual_spins: list[Gtk.SpinButton] = []
        self._manual_nums_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._manual_nums_box.set_valign(Gtk.Align.CENTER)
        for i in range(self._config.main_count):
            adj = Gtk.Adjustment(
                value=self._config.main_min,
                lower=self._config.main_min,
                upper=self._config.main_max,
                step_increment=1,
            )
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
            spin.set_width_chars(3)
            self._manual_spins.append(spin)
            self._manual_nums_box.append(spin)
        self._manual_numbers_row.add_suffix(self._manual_nums_box)
        manual_group.add(self._manual_numbers_row)

        # Bonus (Superzahl / Eurozahlen)
        self._sz_row = Adw.ActionRow(
            title=f"{self._config.bonus_name} ({self._config.bonus_min}-{self._config.bonus_max})"
        )
        adj_sz = Gtk.Adjustment(
            value=self._config.bonus_min,
            lower=self._config.bonus_min,
            upper=self._config.bonus_max,
            step_increment=1,
        )
        self._sz_spin = Gtk.SpinButton(adjustment=adj_sz, climb_rate=1, digits=0)
        self._sz_spin.set_width_chars(3)
        self._sz_spin.set_valign(Gtk.Align.CENTER)
        self._sz_row.add_suffix(self._sz_spin)
        manual_group.add(self._sz_row)

        # Vergleichen-Button
        compare_btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
        )
        compare_btn_box.set_margin_top(8)

        self._compare_btn = Gtk.Button(label=_("Vergleichen"))
        self._compare_btn.set_tooltip_text(_("Vergleicht die eingegebenen Zahlen mit den Vorhersagen"))
        self._compare_btn.add_css_class("pill")
        self._compare_btn.set_sensitive(False)
        self._compare_btn.connect("clicked", self._on_compare_manual)
        compare_btn_box.append(self._compare_btn)

        self._compare_spinner = Gtk.Spinner()
        self._compare_spinner.set_visible(False)
        compare_btn_box.append(self._compare_spinner)

        self._content.append(compare_btn_box)

        # Vergleichs-Ergebnis
        self._comparison_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4,
        )
        self._comparison_frame = Gtk.Frame()
        self._comparison_frame.set_child(self._comparison_box)
        self._comparison_frame.set_visible(False)
        self._content.append(self._comparison_frame)


# TODO: Diese Datei ist >500Z weil: Generierungs-Ergebnis-Darstellung mit Reasoning + Details
