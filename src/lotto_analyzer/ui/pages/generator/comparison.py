"""Generator-Seite: Comparison Mixin."""

import threading
from datetime import date, datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_analyzer.ui.widgets.number_ball import NumberBallRow

logger = get_logger("generator.comparison")



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


class ComparisonMixin:
    """Mixin für GeneratorPage: Comparison."""

    # ══════════════════════════════════════════════
    # Vergleich: Echte Zahlen holen
    # ══════════════════════════════════════════════

    def _on_fetch_actual(self, btn) -> None:
        if not self._results:
            self._status_label.set_label(_("Erst Tipps generieren!"))
            return

        self._fetch_btn.set_sensitive(False)
        self._status_label.set_label(_("Hole aktuelle Ziehung..."))

        draw_day = self._get_draw_day()

        def worker():
            try:
                if self.api_client:
                    # Letzte Ziehung via API holen
                    data = self.api_client.get_latest_draw(draw_day.value)
                    actual = sorted(data.get("numbers", []))
                    sz = data.get("super_number", -1)
                    if sz is None:
                        sz = -1
                    GLib.idle_add(self._on_actual_fetched, actual, sz, None)
                else:
                    GLib.idle_add(
                        self._on_actual_fetched, [], -1,
                        _("Serververbindung erforderlich"),
                    )
            except Exception as e:
                GLib.idle_add(self._on_actual_fetched, [], -1, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_actual_fetched(
        self, numbers: list[int], super_number: int, error: str | None,
    ) -> bool:
        self._fetch_btn.set_sensitive(True)

        if error or not numbers:
            self._status_label.set_label(
                error or _("Keine Zahlen gefunden. Bitte manuell eingeben.")
            )
            return False

        # Spins mit geholten Zahlen befuellen
        for i, spin in enumerate(self._manual_spins):
            if i < len(numbers):
                spin.set_value(numbers[i])
        if super_number >= 0:
            self._sz_spin.set_value(super_number)

        self._status_label.set_label(
            f"Echte Zahlen geladen: {' '.join(str(n) for n in numbers)} "
            f"SZ: {super_number}"
        )

        # Automatisch vergleichen
        self._do_comparison(numbers, super_number if super_number >= 0 else None)
        return False

    # ══════════════════════════════════════════════
    # Vergleich: Manuell
    # ══════════════════════════════════════════════

    def _on_compare_manual(self, btn) -> None:
        if not self._results:
            return

        actual = []
        for spin in self._manual_spins:
            actual.append(int(spin.get_value()))

        # Validierung
        if len(set(actual)) != self._config.main_count:
            self._status_label.set_label(
                _("Fehler: Alle 6 Zahlen müssen unterschiedlich sein!").replace(
                    "6", str(self._config.main_count)
                )
            )
            return

        sz = int(self._sz_spin.get_value())
        self._do_comparison(actual, sz)

    def _do_comparison(
        self, actual_numbers: list[int], super_number: int | None,
    ) -> None:
        """Vergleich durchfuehren und Ergebnis anzeigen."""
        if not self._results:
            return

        draw_day = self._get_draw_day()

        if self.app_mode == "client" and self.api_client:
            self._compare_btn.set_sensitive(False)
            self._compare_spinner.set_visible(True)
            self._compare_spinner.start()

            def worker():
                try:
                    data = self.api_client.compare_predictions(
                        draw_day.value, self._current_draw_date,
                        actual_numbers, super_number,
                    )
                    comp = data.get("comparison", [])
                    GLib.idle_add(self._on_comparison_done, comp, actual_numbers, None)
                except Exception as e:
                    GLib.idle_add(self._on_comparison_done, [], actual_numbers, str(e))

            threading.Thread(target=worker, daemon=True).start()
            return

        # In DB aktualisieren via Generator
        generator = self._init_generator()
        comparison_results = []
        if generator:
            self._compare_btn.set_sensitive(False)
            self._compare_spinner.set_visible(True)
            self._compare_spinner.start()

            def worker():
                try:
                    comp = generator.compare_predictions(
                        draw_day, self._current_draw_date,
                        actual_numbers, super_number,
                    )
                    GLib.idle_add(self._on_comparison_done, comp, actual_numbers, None)
                except Exception as e:
                    GLib.idle_add(self._on_comparison_done, [], actual_numbers, str(e))

            threading.Thread(target=worker, daemon=True).start()
        else:
            # Ohne DB: lokaler Vergleich
            for i, result in enumerate(self._results):
                matches = sorted(set(result.numbers) & set(actual_numbers))
                comparison_results.append({
                    "strategy": result.strategy,
                    "predicted": sorted(result.numbers),
                    "actual": actual_numbers,
                    "matches": matches,
                    "match_count": len(matches),
                    "confidence": result.confidence,
                })
            self._show_comparison(comparison_results, actual_numbers)

    def _on_comparison_done(
        self, comparison: list[dict], actual_numbers: list[int],
        error: str | None,
    ) -> bool:
        self._compare_btn.set_sensitive(True)
        self._compare_spinner.stop()
        self._compare_spinner.set_visible(False)

        if error:
            self._status_label.set_label(_("Vergleich-Fehler") + f": {error}")
            return False

        if not comparison:
            # Fallback: lokaler Vergleich
            local_comp = []
            for i, result in enumerate(self._results):
                matches = sorted(set(result.numbers) & set(actual_numbers))
                local_comp.append({
                    "strategy": result.strategy,
                    "predicted": sorted(result.numbers),
                    "actual": actual_numbers,
                    "matches": matches,
                    "match_count": len(matches),
                    "confidence": result.confidence,
                })
            comparison = local_comp

        self._show_comparison(comparison, actual_numbers)

        # Combo-Status nach Vergleich aktualisieren
        self._refresh_combo_status()
        return False

    def _show_comparison(
        self, comparison: list[dict], actual_numbers: list[int],
    ) -> None:
        """Vergleichs-Ergebnis anzeigen."""
        # Clear
        while self._comparison_box.get_first_child():
            self._comparison_box.remove(self._comparison_box.get_first_child())

        self._comparison_frame.set_visible(True)

        # Echte Zahlen oben anzeigen
        actual_header = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4,
        )
        actual_header.set_margin_top(8)
        actual_header.set_margin_bottom(8)
        actual_label = Gtk.Label(label=_("Echte Gewinnzahlen:"))
        actual_label.add_css_class("heading")
        actual_header.append(actual_label)
        ball_row = NumberBallRow(actual_numbers)
        actual_header.append(ball_row)
        self._comparison_box.append(actual_header)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._comparison_box.append(sep)

        # Header
        header = self._create_comparison_header()
        self._comparison_box.append(header)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._comparison_box.append(sep2)

        # Sortiert nach Treffer (beste zuerst)
        comparison.sort(key=lambda x: x["match_count"], reverse=True)

        best_count = 0
        for i, comp in enumerate(comparison):
            mc = comp["match_count"]
            if mc > best_count:
                best_count = mc
            row = self._create_comparison_row(i + 1, comp, actual_numbers)
            self._comparison_box.append(row)

        # Zusammenfassung
        total = len(comparison)
        wins_3plus = sum(1 for c in comparison if c["match_count"] >= 3)
        summary = Gtk.Label(
            label=f"Zusammenfassung: {total} Tipps, "
                  f"beste: {best_count} Richtige, "
                  f"{wins_3plus} mit 3+ Treffern",
        )
        summary.add_css_class("heading")
        summary.set_margin_top(8)
        summary.set_margin_bottom(8)
        self._comparison_box.append(summary)

        self._status_label.set_label(
            f"Vergleich abgeschlossen: Bester Tipp hat {best_count} Richtige"
        )

    def _create_comparison_header(self) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(8)
        row.set_margin_end(8)
        row.set_margin_top(4)

        for text, width in [
            ("#", 30), ("Strategie", 100), ("Tipp", -1), ("Treffer", 60), ("Richtige", 120),
        ]:
            label = Gtk.Label(label=text)
            label.add_css_class("heading")
            if width > 0:
                label.set_size_request(width, -1)
            else:
                label.set_hexpand(True)
            label.set_xalign(0)
            row.append(label)

        return row

    def _create_comparison_row(
        self, idx: int, comp: dict, actual_numbers: list[int],
    ) -> Gtk.Box:
        mc = comp["match_count"]
        matches_set = set(comp.get("matches", []))

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(8)
        row.set_margin_end(8)
        row.set_margin_top(2)
        row.set_margin_bottom(2)

        # Hintergrundfarbe nach Treffer-Anzahl
        css_class = ""
        if mc >= 6:
            css_class = "success"
        elif mc >= 5:
            css_class = "error"
        elif mc >= 4:
            css_class = "warning"
        elif mc >= 3:
            css_class = "accent"

        if css_class:
            row.add_css_class(css_class)

        # #
        num_label = Gtk.Label(label=str(idx))
        num_label.set_size_request(30, -1)
        num_label.set_xalign(1)
        row.append(num_label)

        # Strategie
        strat_label = Gtk.Label(label=comp["strategy"])
        strat_label.set_size_request(100, -1)
        strat_label.set_xalign(0)
        strat_label.set_ellipsize(Pango.EllipsizeMode.END)
        color = STRATEGY_COLORS.get(comp["strategy"], "")
        if color:
            _apply_css(strat_label, f"label {{ color: {color}; font-weight: bold; }}".encode())
        row.append(strat_label)

        # Tipp (Zahlen, Treffer fett)
        nums_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        nums_box.set_hexpand(True)
        for n in comp["predicted"]:
            n_label = Gtk.Label(label=f"{n:2d}")
            n_label.add_css_class("monospace")
            if n in matches_set:
                n_label.add_css_class("success")
                _apply_css(n_label, b"label { font-weight: bold; }")
            nums_box.append(n_label)
        row.append(nums_box)

        # Treffer
        treffer_label = Gtk.Label(label=str(mc))
        treffer_label.set_size_request(60, -1)
        if mc >= 3:
            _apply_css(treffer_label, b"label { font-weight: bold; font-size: 1.1em; }")
        row.append(treffer_label)

        # Richtige Zahlen
        richtige = ", ".join(str(n) for n in comp.get("matches", []))
        richtige_label = Gtk.Label(label=richtige if richtige else "-")
        richtige_label.set_size_request(120, -1)
        richtige_label.set_xalign(0)
        row.append(richtige_label)

        return row

