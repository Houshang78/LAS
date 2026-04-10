"""Generator-Seite: Stored Mixin."""

import csv
import io
import threading
from datetime import date, datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib, Gio

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_analyzer.ui.widgets.help_button import HelpButton

logger = get_logger("generator.stored")



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


class StoredMixin:
    """Mixin für GeneratorPage: Stored."""

    # ══════════════════════════════════════════════
    # Gespeicherte Vorhersagen Browser
    # ══════════════════════════════════════════════

    def _build_stored_predictions_section(self) -> None:
        """Gespeicherte Vorhersagen durchsuchen mit Pagination."""
        self._stored_page = 0
        self._stored_page_size = self.DEFAULT_PAGE_SIZE
        self._stored_total = 0
        self._stored_items: list[dict] = []

        stored_group = Adw.PreferencesGroup(
            title=_("Gespeicherte Vorhersagen"),
            description=_("Auto-generierte Predictions nach Ziehtag und Datum durchsuchen"),
        )
        stored_group.set_header_suffix(
            HelpButton(_("Alle bisher generierten Tipps nach Datum durchsuchen, mit Treffer-Vergleich und Cleanup."))
        )
        self._content.append(stored_group)

        # ── Filter-Leiste: Ziehtag + Datum + Buttons ──
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        # Ziehtag-Auswahl
        day_label = Gtk.Label(label=_("Ziehtag:"))
        filter_box.append(day_label)

        self._stored_day_combo = Gtk.ComboBoxText()
        for day in ["saturday", "wednesday", "tuesday", "friday"]:
            self._stored_day_combo.append_text(day)
        self._stored_day_combo.set_active(0)
        self._stored_day_combo.connect("changed", self._on_stored_day_changed)
        filter_box.append(self._stored_day_combo)

        # Datum-Auswahl
        date_label = Gtk.Label(label=_("Datum:"))
        date_label.set_margin_start(12)
        filter_box.append(date_label)

        self._stored_date_combo = Gtk.ComboBoxText()
        self._stored_date_combo.set_size_request(150, -1)
        filter_box.append(self._stored_date_combo)

        # Laden-Button
        self._stored_load_btn = Gtk.Button(label=_("Laden"))
        self._stored_load_btn.set_tooltip_text(_("Gespeicherte Vorhersagen für das gewählte Datum laden"))
        self._stored_load_btn.add_css_class("suggested-action")
        self._stored_load_btn.set_icon_name("view-refresh-symbolic")
        self._stored_load_btn.connect("clicked", self._on_load_stored)
        self._stored_load_btn.set_margin_start(12)
        filter_box.append(self._stored_load_btn)

        # Aufräumen-Button
        self._stored_cleanup_btn = Gtk.Button(label=_("Aufräumen"))
        self._stored_cleanup_btn.set_tooltip_text(_("Löscht schwache Vorhersagen mit wenig Treffern"))
        self._stored_cleanup_btn.add_css_class("flat")
        self._stored_cleanup_btn.set_icon_name("user-trash-symbolic")
        self._stored_cleanup_btn.connect("clicked", self._on_stored_cleanup)
        self.register_readonly_button(self._stored_cleanup_btn)
        filter_box.append(self._stored_cleanup_btn)

        # Kopieren-Button
        stored_copy_btn = Gtk.Button(label=_("Kopieren"))
        stored_copy_btn.add_css_class("flat")
        stored_copy_btn.set_icon_name("edit-copy-symbolic")
        stored_copy_btn.set_tooltip_text(_("Aktuelle Seite in die Zwischenablage kopieren"))
        stored_copy_btn.connect("clicked", self._on_stored_copy_clipboard)
        filter_box.append(stored_copy_btn)

        # CSV-Export-Button
        stored_csv_btn = Gtk.Button(label=_("CSV-Export"))
        stored_csv_btn.add_css_class("flat")
        stored_csv_btn.set_icon_name("document-save-symbolic")
        stored_csv_btn.set_tooltip_text(_("Alle Vorhersagen für dieses Datum als CSV"))
        stored_csv_btn.connect("clicked", self._on_stored_export_csv)
        filter_box.append(stored_csv_btn)

        stored_group.add(filter_box)

        # ── Kauf-Leiste ──
        buy_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buy_box.set_margin_top(4)

        buy_label = Gtk.Label(label=_("Anzahl Tipps kaufen:"))
        buy_box.append(buy_label)

        self._buy_count_spin = Gtk.SpinButton.new_with_range(1, 20, 1)
        self._buy_count_spin.set_value(
            self.config_manager.config.auto_generation.purchase_count
        )
        self._buy_count_spin.set_width_chars(3)
        buy_box.append(self._buy_count_spin)

        self._buy_btn = Gtk.Button(label=_("Kaufen"))
        self._buy_btn.add_css_class("suggested-action")
        self._buy_btn.add_css_class("pill")
        self._buy_btn.set_icon_name("emblem-ok-symbolic")
        self._buy_btn.set_tooltip_text(_("Beste N Tipps als gekauft markieren und an Telegram senden"))
        self._buy_btn.connect("clicked", self._on_purchase_tips)
        self.register_readonly_button(self._buy_btn)
        buy_box.append(self._buy_btn)

        self._buy_status_label = Gtk.Label(label="")
        self._buy_status_label.add_css_class("dim-label")
        self._buy_status_label.set_hexpand(True)
        self._buy_status_label.set_xalign(0)
        buy_box.append(self._buy_status_label)

        stored_group.add(buy_box)

        # ── Pagination-Leiste ──
        page_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        page_box.set_margin_top(8)

        self._stored_prev_btn = Gtk.Button(label=_("Zurück"))
        self._stored_prev_btn.set_tooltip_text(_("Vorherige Seite"))
        self._stored_prev_btn.add_css_class("flat")
        self._stored_prev_btn.set_icon_name("go-previous-symbolic")
        self._stored_prev_btn.connect("clicked", self._on_stored_prev)
        self._stored_prev_btn.set_sensitive(False)
        page_box.append(self._stored_prev_btn)

        self._stored_page_label = Gtk.Label(label="")
        self._stored_page_label.set_hexpand(True)
        page_box.append(self._stored_page_label)

        self._stored_next_btn = Gtk.Button(label=_("Weiter"))
        self._stored_next_btn.set_tooltip_text(_("Nächste Seite"))
        self._stored_next_btn.add_css_class("flat")
        self._stored_next_btn.set_icon_name("go-next-symbolic")
        self._stored_next_btn.connect("clicked", self._on_stored_next)
        self._stored_next_btn.set_sensitive(False)
        page_box.append(self._stored_next_btn)

        stored_group.add(page_box)

        # ── Ergebnis-Container ──
        self._stored_results_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2,
        )
        self._stored_scroll = Gtk.ScrolledWindow()
        self._stored_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._stored_scroll.set_child(self._stored_results_box)
        self._stored_scroll.set_min_content_height(80)
        self._stored_scroll.set_max_content_height(600)

        self._stored_frame = Gtk.Frame()
        self._stored_frame.set_child(self._stored_scroll)
        self._stored_frame.set_visible(False)
        self._content.append(self._stored_frame)

        # Initial: Daten laden
        self._on_stored_day_changed(self._stored_day_combo)

    def _on_stored_day_changed(self, combo) -> None:
        """Ziehtag gewechselt → Daten-Liste neu laden."""
        draw_day = combo.get_active_text()
        if not draw_day:
            return

        def _fetch():
            try:
                if self.app_mode == "client" and self.api_client:
                    dates = self.api_client.get_prediction_dates(draw_day)
                elif self.db:
                    dates = self.db.get_prediction_dates(draw_day)
                else:
                    dates = []
            except Exception as e:
                logger.error(f"Prediction-Daten laden: {e}")
                dates = []
            GLib.idle_add(self._populate_date_combo, dates)

        threading.Thread(target=_fetch, daemon=True).start()

    def _populate_date_combo(self, dates: list[str]) -> None:
        """Datum-DropDown mit Werten fuellen (nur aktuelle Woche + 7 Tage)."""
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        dates = [d for d in dates if d >= cutoff]
        self._stored_date_combo.remove_all()
        for d in dates:
            self._stored_date_combo.append_text(d)
        if dates:
            self._stored_date_combo.set_active(0)

    def _on_load_stored(self, btn) -> None:
        """Gespeicherte Predictions laden."""
        draw_day = self._stored_day_combo.get_active_text()
        draw_date = self._stored_date_combo.get_active_text()
        if not draw_day or not draw_date:
            return
        self._stored_page = 0
        self._load_stored_predictions(draw_day, draw_date)

    def _load_stored_predictions(self, draw_day: str, draw_date: str) -> None:
        """Predictions via API/DB mit Pagination laden."""
        offset = self._stored_page * self._stored_page_size
        self._stored_load_btn.set_sensitive(False)

        def _fetch():
            try:
                if self.app_mode == "client" and self.api_client:
                    data = self.api_client.get_predictions(
                        draw_day, draw_date, offset, self._stored_page_size,
                    )
                    items = data.get("predictions", [])
                    total = data.get("total", 0)
                elif self.db:
                    items = self.db.get_predictions_paginated(
                        draw_day, draw_date, offset, self._stored_page_size,
                    )
                    total = self.db.get_predictions_count(draw_day, draw_date)
                else:
                    items, total = [], 0
            except Exception as e:
                logger.error(f"Stored predictions laden: {e}")
                items, total = [], 0
            GLib.idle_add(self._display_stored_predictions, items, total)

        threading.Thread(target=_fetch, daemon=True).start()

    def _display_stored_predictions(
        self, items: list[dict], total: int,
    ) -> None:
        """Geladene Predictions in der GUI anzeigen."""
        self._stored_total = total
        self._stored_items = items
        self._stored_load_btn.set_sensitive(True)

        # Container leeren
        while self._stored_results_box.get_first_child():
            self._stored_results_box.remove(
                self._stored_results_box.get_first_child(),
            )

        if not items:
            empty = Gtk.Label(label=_("Keine Vorhersagen für dieses Datum."))
            empty.add_css_class("dim-label")
            empty.set_margin_top(12)
            empty.set_margin_bottom(12)
            self._stored_results_box.append(empty)
            self._stored_frame.set_visible(True)
            self._stored_page_label.set_text("")
            self._stored_prev_btn.set_sensitive(False)
            self._stored_next_btn.set_sensitive(False)
            return

        # Header
        bonus_hdr = self._config.bonus_name[:2].upper()
        header = self._create_stored_row(
            "#", "Zahlen", bonus_hdr, "Strategie", "Konfidenz",
            "Treffer", "Kategorie", is_header=True,
        )
        self._stored_results_box.append(header)
        self._stored_results_box.append(Gtk.Separator())

        # Zeilen
        offset = self._stored_page * self._stored_page_size
        for i, pred in enumerate(items, start=offset + 1):
            nums = pred.get("predicted_numbers", "")
            if isinstance(nums, list):
                nums = " ".join(str(n) for n in nums)
            else:
                nums = nums.replace(",", " ")

            # Superzahl aus actual_numbers oder bonus_match
            sz = str(pred.get("bonus_match", "")) if pred.get("bonus_match") else ""

            strategy = pred.get("strategy", "")
            conf = f"{pred.get('ml_confidence', 0):.2f}"
            matches = str(pred.get("matches", ""))
            category = pred.get("match_category", "") or ""

            is_purchased = bool(pred.get("is_purchased"))

            row = self._create_stored_row(
                str(i), nums, sz, strategy, conf, matches, category,
                strategy_key=strategy, is_purchased=is_purchased,
            )
            self._stored_results_box.append(row)

            if i < offset + len(items):
                sep = Gtk.Separator()
                sep.add_css_class("dim-label")
                self._stored_results_box.append(sep)

        self._stored_frame.set_visible(True)

        # Hoehe explizit setzen: schrumpft bei wenig, max 600px
        row_h = 30
        h = min((len(items) + 1) * row_h, 600)  # +1 für Header
        self._stored_scroll.set_min_content_height(max(h, 80))
        self._stored_scroll.set_max_content_height(600)

        # Pagination-Status
        total_pages = max(1, (total + self._stored_page_size - 1) // self._stored_page_size)
        current = self._stored_page + 1
        self._stored_page_label.set_text(
            f"Seite {current} von {total_pages} ({total} Vorhersagen)"
        )
        self._stored_prev_btn.set_sensitive(self._stored_page > 0)
        self._stored_next_btn.set_sensitive(current < total_pages)

    def _create_stored_row(
        self, num: str, zahlen: str, sz: str,
        strategy: str, confidence: str, matches: str,
        category: str, is_header: bool = False,
        strategy_key: str = "", is_purchased: bool = False,
    ) -> Gtk.Box:
        """Eine Zeile für die Stored-Predictions-Tabelle erstellen."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_margin_start(8)
        row.set_margin_end(8)
        row.set_margin_top(3)
        row.set_margin_bottom(3)

        cols = [
            (num, 40),
            (zahlen, 200),
            (sz, 35),
            (strategy, 90),
            (confidence, 70),
            (matches, 55),
            (category, 120),
        ]
        for text, width in cols:
            lbl = Gtk.Label(label=text)
            lbl.set_size_request(width, -1)
            lbl.set_xalign(0)
            if is_header:
                lbl.add_css_class("heading")
            else:
                lbl.add_css_class("monospace")
            row.append(lbl)

        # GEKAUFT-Label
        if is_purchased and not is_header:
            bought_lbl = Gtk.Label(label=_("GEKAUFT"))
            bought_lbl.set_size_request(70, -1)
            bought_lbl.set_xalign(0)
            _apply_css(bought_lbl, b"label { color: rgba(50,180,50,1); font-weight: bold; }")
            row.append(bought_lbl)

        # Strategie-Farbe / Purchased-Farbe
        if not is_header:
            if is_purchased:
                _apply_css(row, b"box { border-left: 3px solid rgba(50,180,50,0.9); }")
            elif strategy_key in STRATEGY_COLORS:
                _apply_css(row, f"box {{ border-left: 3px solid {STRATEGY_COLORS[strategy_key]}; }}")

        return row

    def _on_stored_prev(self, btn) -> None:
        """Vorherige Seite."""
        if self._stored_page > 0:
            self._stored_page -= 1
            draw_day = self._stored_day_combo.get_active_text()
            draw_date = self._stored_date_combo.get_active_text()
            if draw_day and draw_date:
                self._load_stored_predictions(draw_day, draw_date)

    def _on_stored_next(self, btn) -> None:
        """Nächste Seite."""
        total_pages = max(
            1, (self._stored_total + self._stored_page_size - 1)
            // self._stored_page_size,
        )
        if self._stored_page + 1 < total_pages:
            self._stored_page += 1
            draw_day = self._stored_day_combo.get_active_text()
            draw_date = self._stored_date_combo.get_active_text()
            if draw_day and draw_date:
                self._load_stored_predictions(draw_day, draw_date)

    def _on_stored_cleanup(self, btn) -> None:
        """Predictions unter Schwelle löschen."""
        draw_day = self._stored_day_combo.get_active_text()
        draw_date = self._stored_date_combo.get_active_text()
        if not draw_day or not draw_date:
            return

        min_matches = self.config_manager.config.auto_generation.min_matches_to_keep
        self._stored_cleanup_btn.set_sensitive(False)

        def _cleanup():
            try:
                if self.app_mode == "client" and self.api_client:
                    result = self.api_client.cleanup_predictions(
                        draw_day, draw_date, min_matches,
                    )
                    deleted = result.get("deleted", 0)
                elif self.db:
                    deleted = self.db.delete_low_match_predictions(
                        draw_day, draw_date, min_matches,
                    )
                else:
                    deleted = 0
            except Exception as e:
                logger.error(f"Cleanup fehlgeschlagen: {e}")
                deleted = 0
            GLib.idle_add(self._on_cleanup_done, deleted, draw_day, draw_date)

        threading.Thread(target=_cleanup, daemon=True).start()

    def _on_cleanup_done(
        self, deleted: int, draw_day: str, draw_date: str,
    ) -> None:
        """Cleanup fertig → UI aktualisieren."""
        self._stored_cleanup_btn.set_sensitive(True)
        min_m = self.config_manager.config.auto_generation.min_matches_to_keep
        logger.info(
            f"Cleanup: {deleted} Predictions mit <{min_m} Treffern gelöscht"
        )
        # Seite neu laden
        self._stored_page = 0
        self._load_stored_predictions(draw_day, draw_date)

    def _on_stored_copy_clipboard(self, btn) -> None:
        """Aktuelle Seite der gespeicherten Vorhersagen in die Zwischenablage kopieren."""
        if not self._stored_items:
            return

        bonus_hdr = self._config.bonus_name[:2].upper()
        lines = [f"Nr\tZahlen\t{bonus_hdr}\tStrategie\tKonfidenz\tTreffer\tKategorie"]
        offset = self._stored_page * self._stored_page_size
        for i, pred in enumerate(self._stored_items, start=offset + 1):
            nums = pred.get("predicted_numbers", "")
            if isinstance(nums, list):
                nums = " ".join(str(n) for n in nums)
            else:
                nums = nums.replace(",", " ")
            sz = str(pred.get("bonus_match", "")) if pred.get("bonus_match") else ""
            strategy = pred.get("strategy", "")
            conf = f"{pred.get('ml_confidence', 0):.2f}"
            matches = str(pred.get("matches", ""))
            category = pred.get("match_category", "") or ""
            lines.append(f"{i}\t{nums}\t{sz}\t{strategy}\t{conf}\t{matches}\t{category}")

        text = "\n".join(lines)
        clipboard = self.get_clipboard()
        clipboard.set(text)
        logger.info(f"Stored predictions kopiert: {len(self._stored_items)} Zeilen")

    def _on_stored_export_csv(self, btn) -> None:
        """Alle Predictions für das gewählte Datum als CSV exportieren."""
        draw_day = self._stored_day_combo.get_active_text()
        draw_date = self._stored_date_combo.get_active_text()
        if not draw_day or not draw_date:
            return

        btn.set_sensitive(False)

        def _fetch_all():
            try:
                if self.app_mode == "client" and self.api_client:
                    data = self.api_client.get_predictions(
                        draw_day, draw_date, 0, 10000,
                    )
                    items = data.get("predictions", [])
                elif self.db:
                    items = self.db.get_predictions_paginated(
                        draw_day, draw_date, 0, 10000,
                    )
                else:
                    items = []
            except Exception as e:
                logger.error(f"Stored CSV-Export laden: {e}")
                items = []
            GLib.idle_add(self._show_stored_csv_dialog, items, draw_day, draw_date, btn)

        threading.Thread(target=_fetch_all, daemon=True).start()

    def _show_stored_csv_dialog(
        self, items: list[dict], draw_day: str, draw_date: str, btn,
    ) -> None:
        """FileDialog oeffnen für Stored-Predictions CSV-Export."""
        btn.set_sensitive(True)
        if not items:
            logger.info("Keine Vorhersagen zum Exportieren.")
            return

        from gi.repository import Gio

        self._CSV_DIR.mkdir(parents=True, exist_ok=True)
        self._stored_export_items = items

        dialog = Gtk.FileDialog()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dialog.set_initial_name(f"predictions_{draw_day}_{draw_date}_{timestamp}.csv")
        dialog.set_initial_folder(Gio.File.new_for_path(str(self._CSV_DIR)))

        csv_filter = Gtk.FileFilter()
        csv_filter.set_name(_("CSV-Dateien"))
        csv_filter.add_pattern("*.csv")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(csv_filter)
        dialog.set_filters(filters)

        root = self.get_root()
        if root:
            dialog.save(root, None, self._on_stored_csv_done)

    def _on_stored_csv_done(self, dialog, result) -> None:
        """CSV-Datei schreiben für gespeicherte Vorhersagen."""
        try:
            file = dialog.save_finish(result)
            if not file:
                return

            path = file.get_path()
            items = getattr(self, "_stored_export_items", [])
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Nr", "Zahlen", self._config.bonus_name,
                    "Strategie", "Konfidenz",
                    "Treffer", "Kategorie", "Datum",
                ])
                for i, pred in enumerate(items, start=1):
                    nums = pred.get("predicted_numbers", "")
                    if isinstance(nums, list):
                        nums = " ".join(str(n) for n in nums)
                    else:
                        nums = nums.replace(",", " ")
                    sz = str(pred.get("bonus_match", "")) if pred.get("bonus_match") else ""
                    strategy = pred.get("strategy", "")
                    conf = f"{pred.get('ml_confidence', 0):.2f}"
                    matches = str(pred.get("matches", ""))
                    category = pred.get("match_category", "") or ""
                    draw_date = pred.get("draw_date", "")
                    writer.writerow([
                        i, nums, sz, strategy, conf, matches, category, draw_date,
                    ])

            logger.info(f"Stored predictions CSV exportiert: {path} ({len(items)} Zeilen)")

        except Exception as e:
            logger.error(f"Stored CSV-Export: {e}")

    # ══════════════════════════════════════════════
    # Tipps kaufen
    # ══════════════════════════════════════════════

    def _on_purchase_tips(self, btn) -> None:
        """Top-N Tipps kaufen via API/DB + Telegram senden."""
        draw_day = self._stored_day_combo.get_active_text()
        draw_date = self._stored_date_combo.get_active_text()
        if not draw_day or not draw_date:
            self._buy_status_label.set_text(_("Bitte Ziehtag und Datum wählen."))
            return

        count = int(self._buy_count_spin.get_value())
        self._buy_btn.set_sensitive(False)
        self._buy_status_label.set_text(f"{_('Kaufe')} {count} {_('Tipps')}...")

        def worker():
            try:
                result = self._do_purchase(draw_day, draw_date, count)
                GLib.idle_add(self._on_purchase_done, result, None)
            except Exception as e:
                GLib.idle_add(self._on_purchase_done, {}, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _do_purchase(self, draw_day: str, draw_date: str, count: int) -> dict:
        """Worker: Kauf via API an Server delegieren."""
        if self.api_client:
            return self.api_client.purchase_predictions(
                draw_day, draw_date, count, send_telegram=True,
            )

        # Ohne Server-Verbindung nicht möglich
        return {"purchased": 0, "tips": [], "telegram_sent": False}

    def _on_purchase_done(self, result: dict, error: str | None) -> bool:
        """UI aktualisieren nach Kauf."""
        self._buy_btn.set_sensitive(True)

        if error:
            self._buy_status_label.set_text(f"Fehler: {error}")
            return False

        purchased = result.get("purchased", 0)
        telegram_sent = result.get("telegram_sent", False)
        cost = result.get("estimated_cost", "?")
        tg_info = " — an Telegram gesendet" if telegram_sent else ""
        self._buy_status_label.set_text(
            f"{purchased} Tipps gekauft (~{cost}){tg_info}"
        )

        # Seite neu laden um Markierungen anzuzeigen
        draw_day = self._stored_day_combo.get_active_text()
        draw_date = self._stored_date_combo.get_active_text()
        if draw_day and draw_date:
            self._stored_page = 0
            self._load_stored_predictions(draw_day, draw_date)

        return False


# TODO: Diese Datei ist >500Z weil: Gespeicherte Predictions mit Pagination + Filter + Purchase
