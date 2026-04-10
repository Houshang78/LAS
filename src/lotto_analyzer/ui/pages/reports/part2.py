"""UI-Seite reports: part2 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("reports.part2")
import re
import json

from lotto_analyzer.ui.widgets.number_ball import NumberBallRow

from lotto_analyzer.ui.ui_helpers import format_eur

import sqlite3

import json

DAY_LABELS = {
    "saturday": "Samstag",
    "wednesday": "Mittwoch",
    "tuesday": "Dienstag",
    "friday": "Freitag",
}


class Part2Mixin:
    """Part2 Mixin."""

    # ── Berichte laden ──

    def _load_reports(self) -> None:
        """Berichte für den ausgewählten Ziehungstag laden."""
        with self._op_lock:
            if self._loading:
                return
            self._loading = True
        self._refresh_btn.set_sensitive(False)
        self._spinner.set_visible(True)
        self._spinner.start()

        draw_day = self._get_selected_draw_day()
        # "Alle" = None → nur Ziehungstage des aktuellen Spieltyps laden
        game_draw_days = list(self._config.draw_days) if draw_day is None else None

        def worker():
            try:
                if self.api_client:
                    reports = self.api_client.get_reports(
                        draw_day=draw_day, draw_days=game_draw_days, limit=50,
                    )
                    if not isinstance(reports, list):
                        logger.warning("get_reports: unerwarteter Typ %s", type(reports))
                        reports = []
                elif self.app_db:
                    reports = self.app_db.get_cycle_reports(
                        draw_day=draw_day, draw_days=game_draw_days, limit=50,
                    )
                else:
                    reports = []
                GLib.idle_add(self._on_reports_loaded, reports, None)
            except (sqlite3.Error, ConnectionError, TimeoutError, OSError) as e:
                GLib.idle_add(self._on_reports_loaded, [], str(e))
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler beim Laden der Berichte: {e}")
                GLib.idle_add(self._on_reports_loaded, [], str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_reports_loaded(self, reports: list[dict], error: str | None) -> bool:
        """Berichte in die Liste einfuegen (Main-Thread)."""
        self.mark_refreshed()
        with self._op_lock:
            self._loading = False
        self._refresh_btn.set_sensitive(True)
        self._spinner.stop()
        self._spinner.set_visible(False)

        if error:
            logger.warning(f"Berichte laden fehlgeschlagen: {error}")

        self._reports = reports

        # Liste leeren
        while True:
            row = self._listbox.get_row_at_index(0)
            if row is None:
                break
            self._listbox.remove(row)

        # Berichte einfuegen
        for report in reports:
            row = self._create_report_row(report)
            self._listbox.append(row)

        # Detail zurücksetzen
        self._selected_report = None
        self._telegram_btn.set_sensitive(False)
        self._show_detail(None)

        return False

    def _create_report_row(self, report: dict) -> Gtk.ListBoxRow:
        """Eine Zeile für die Bericht-Liste erstellen."""
        row = Gtk.ListBoxRow()
        row.report_data = report

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Erste Zeile: Datum + Tag
        top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        date_label = Gtk.Label(label=report.get("draw_date", "?"))
        date_label.add_css_class("heading")
        date_label.set_xalign(0)
        top_box.append(date_label)

        day_str = DAY_LABELS.get(report.get("draw_day", ""), report.get("draw_day", ""))
        day_tag = Gtk.Label(label=day_str)
        day_tag.add_css_class("dim-label")
        top_box.append(day_tag)

        top_box.append(Gtk.Box(hexpand=True))  # spacer

        box.append(top_box)

        # Zweite Zeile: Treffer-Info
        best = report.get("best_match", 0)
        wins = report.get("wins_3plus", 0)
        compared = report.get("predictions_compared", 0)
        info_text = f"{_('Beste')}: {best} {_('Richtige')} | 3+: {wins}x | {compared} {_('Tipps')}"
        info_label = Gtk.Label(label=info_text)
        info_label.set_xalign(0)
        info_label.add_css_class("caption")
        box.append(info_label)

        row.set_child(box)
        return row

    # ── Bericht-Detail ──

    def _on_report_selected(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        """Bericht ausgewählt — Detail laden."""
        if row is None or not hasattr(row, "report_data"):
            self._selected_report = None
            self._telegram_btn.set_sensitive(False)
            self._show_detail(None)
            return

        report = row.report_data
        report_id = report.get("report_id")

        if not report_id:
            self._show_detail(report)
            return

        # Vollständigen Bericht laden
        def worker():
            try:
                if self.api_client:
                    full = self.api_client.get_report(report_id)
                elif self.app_db:
                    full = self.app_db.get_cycle_report(report_id)
                else:
                    full = report
                GLib.idle_add(self._show_detail, full or report)
            except (sqlite3.Error, ConnectionError, TimeoutError, OSError) as e:
                logger.warning(f"Bericht laden fehlgeschlagen: {e}")
                GLib.idle_add(self._show_detail, report)
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler beim Bericht laden: {e}")
                GLib.idle_add(self._show_detail, report)

        threading.Thread(target=worker, daemon=True).start()

    def _rebuild_detail_groups(self) -> None:
        """Remove and recreate all dynamic PreferencesGroups.

        This is the only reliable way to clear Adw.PreferencesGroup
        children — the internal widget tree is complex and removing
        individual rows leaves orphaned wrappers.
        """
        # Remove old groups from detail_box
        for group in [self._categories_group, self._quoten_group,
                       self._accuracy_group]:
            parent = group.get_parent()
            if parent:
                parent.remove(group)

        # Recreate fresh groups
        self._categories_group = Adw.PreferencesGroup(title=_("Treffer-Kategorien"))
        self._categories_group.set_visible(False)

        self._quoten_group = Adw.PreferencesGroup(title=_("Gewinnquoten"))
        self._quoten_group.set_visible(False)

        self._accuracy_group = Adw.PreferencesGroup(title=_("ML-Genauigkeit"))
        self._accuracy_group.set_visible(False)

        self._accuracy_grid = Gtk.Grid()
        self._accuracy_grid.set_row_spacing(6)
        self._accuracy_grid.set_column_spacing(16)
        self._accuracy_group.add(self._accuracy_grid)

        # Clear and re-add stats grid
        while True:
            child = self._stats_grid.get_first_child()
            if not child:
                break
            self._stats_grid.remove(child)

        # Insert groups back into detail_box (after stats_grid)
        # Find the position after stats_grid
        self._detail_box.insert_child_after(self._categories_group, self._stats_grid)
        self._detail_box.insert_child_after(self._quoten_group, self._categories_group)
        self._detail_box.insert_child_after(self._accuracy_group, self._quoten_group)

        # Hide AI groups too
        self._ai_hits_group.set_visible(False)
        self._ai_hits_label.set_visible(False)
        self._summary_group.set_visible(False)
        self._summary_label.set_visible(False)

    def _show_detail(self, report: dict | None) -> None:
        """Bericht-Detail anzeigen oder Platzhalter."""
        self._selected_report = report
        has_report = report is not None

        self._detail_placeholder.set_visible(not has_report)
        self._detail_title.set_visible(has_report)
        self._stats_grid.set_visible(has_report)
        self._telegram_btn.set_sensitive(has_report)
        self._export_md_btn.set_visible(has_report)

        # Destroy and recreate all dynamic groups (prevents stacking)
        self._rebuild_detail_groups()

        self._ai_hits_label.set_label("")
        self._summary_label.set_label("")

        if not has_report:
            return

        # Titel
        day_str = DAY_LABELS.get(report.get("draw_day", ""), report.get("draw_day", ""))
        self._detail_title.set_label(f"{_('Bericht')}: {day_str} {report.get('draw_date', '')}")

        # Stats-Grid komplett leeren
        while True:
            child = self._stats_grid.get_first_child()
            if not child:
                break
            self._stats_grid.remove(child)

        # Load actual draw numbers + SZ/bonus for display
        draw_info = self._load_draw_numbers(report)
        draw_nums_text = draw_info.get("numbers_text", "—")

        stats = [
            (_("Ziehung:"), draw_nums_text),
            (_("Verglichene Tipps:"), str(report.get("predictions_compared", 0))),
            (_("Beste Treffer:"), f"{report.get('best_match', 0)} {_('Richtige')}"),
            (_("3+ Treffer:"), f"{report.get('wins_3plus', 0)}x"),
            (_("Erstellt:"), report.get("created_at", "")),
        ]
        for i, (label_text, value_text) in enumerate(stats):
            lbl = Gtk.Label(label=label_text)
            lbl.add_css_class("dim-label")
            lbl.set_xalign(0)
            self._stats_grid.attach(lbl, 0, i, 1, 1)

            val = Gtk.Label(label=value_text)
            val.add_css_class("heading")
            val.set_xalign(0)
            self._stats_grid.attach(val, 1, i, 1, 1)

        # Kategorien — aufklappbar mit Expander (group is fresh from _rebuild)
        match_cat = report.get("match_categories", "")
        if match_cat:
            self._categories_group.set_visible(True)
            # Kategorien parsen (JSON oder "3:5,4:2,5:0,6:0")
            try:
                if match_cat.startswith("{"):
                    cats = json.loads(match_cat)
                else:
                    cats = {}
                    for pair in match_cat.split(","):
                        if ":" in pair:
                            k, v = pair.strip().split(":", 1)
                            cats[k.strip()] = int(v.strip())
            except (json.JSONDecodeError, ValueError):
                cats = {}

            for matches_key, count in sorted(cats.items(), key=lambda x: str(x[0]), reverse=True):
                # 0er/1er/2er nicht anzeigen — erst ab 3 Richtige relevant
                match = re.search(r'(\d+)', str(matches_key))
                num_part = int(match.group(1)) if match else 0
                if num_part < 3:
                    continue

                count = int(count)
                if count == 0:
                    # Keine Treffer — einfache Zeile
                    cat_row = Adw.ActionRow(
                        title=f"{matches_key} {_('Richtige')}",
                        subtitle=f"{count}x",
                    )
                    self._categories_group.add(cat_row)
                else:
                    # Aufklappbare Zeile mit Lazy-Load
                    expander = Adw.ExpanderRow(
                        title=f"{matches_key} {_('Richtige')}",
                        subtitle=f"{count}x",
                    )
                    # Placeholder waehrend Daten noch nicht geladen
                    placeholder = Adw.ActionRow(title=_("Laden..."))
                    expander.add_row(placeholder)
                    # Zustand-Flags
                    expander._loaded = False
                    expander._match_key = str(matches_key)
                    expander._placeholder = placeholder
                    expander.connect(
                        "notify::expanded",
                        self._on_category_expanded,
                    )
                    self._categories_group.add(expander)
        else:
            self._categories_group.set_visible(False)

        # Gewinnquoten laden (6aus49 + EuroJackpot)
        draw_day_val = report.get("draw_day", "")
        if draw_day_val:
            self._load_prizes(draw_day_val, report.get("draw_date", ""))
        else:
            self._quoten_group.set_visible(False)

        # AI-Summary
        ai_summary = report.get("ai_summary", "")
        if ai_summary:
            self._summary_group.set_visible(True)
            self._summary_label.set_visible(True)
            self._summary_label.set_label(ai_summary)
        else:
            self._summary_group.set_visible(False)
            self._summary_label.set_visible(False)

        # ML-Genauigkeit + AI-Analyse — nur wenn Predictions verglichen wurden
        compared = report.get("predictions_compared", 0) or 0
        if compared > 0:
            self._accuracy_group.set_visible(True)
            self._ai_hits_group.set_visible(True)
            self._ai_hits_label.set_visible(False)
            self._analyze_hits_btn.set_sensitive(True)
            # Accuracy-Daten async laden
            self._load_accuracy(report)
        else:
            self._accuracy_group.set_visible(False)
            self._ai_hits_group.set_visible(False)

        return False

    # ── Gewinnquoten ──

    def _load_prizes(self, draw_day: str, draw_date: str) -> None:
        """Gewinnquoten async laden."""
        cache_key = f"{draw_day}_{draw_date}"
        cached = self._cache_get(self._prizes_cache, cache_key)
        if cached is not None:
            self._populate_prizes(cached)
            return

        def worker():
            try:
                prizes = []
                if self.api_client:
                    data = self.api_client.get_draw_prizes(draw_day, draw_date)
                    prizes = data.get("prizes", [])
                elif self.db:
                    prizes = self.db.get_draw_prizes(draw_day, draw_date)
                if prizes:
                    self._cache_set(self._prizes_cache, cache_key, prizes)
                GLib.idle_add(self._populate_prizes, prizes)
            except Exception as e:
                logger.warning(f"Gewinnquoten laden fehlgeschlagen: {e}")
                GLib.idle_add(self._populate_prizes, [])

        threading.Thread(target=worker, daemon=True).start()

    def _populate_prizes(self, prizes: list[dict]) -> bool:
        """Gewinnquoten-Gruppe mit 9 ActionRows fuellen (Main-Thread)."""
        if not self._selected_report:
            return False
        # Group is fresh from _rebuild — no need to clean old children

        if not prizes:
            self._quoten_group.set_visible(False)
            return False

        self._quoten_group.set_visible(True)
        for p in prizes:
            class_num = p.get("class_number", 0)
            desc = p.get("description", "")
            winners = p.get("winner_count", 0)
            amount = p.get("prize_amount", 0.0)
            is_jackpot = p.get("is_jackpot", 0)

            if is_jackpot:
                amount_str = _("Unbesetzt (Jackpot)")
            elif amount > 0:
                amount_str = format_eur(amount)
            else:
                amount_str = "0,00 EUR"

            row = Adw.ActionRow(
                title=f"{_('Klasse')} {class_num}: {desc}",
                subtitle=f"{winners} {_('Gewinner')} | {amount_str}",
            )
            if class_num == 1:
                row.add_prefix(Gtk.Image.new_from_icon_name("starred-symbolic"))
            self._quoten_group.add(row)

        return False

    # ── Aufklappbare Kategorien ──

    def _on_category_expanded(self, expander: Adw.ExpanderRow, _pspec) -> None:
        """Kategorie aufgeklappt — Detail-Predictions lazy-loaden."""
        if not expander.get_expanded() or expander._loaded:
            return
        expander._loaded = True
        report = self._selected_report
        if not report:
            return

        report_id = report.get("report_id", "")
        draw_day = report.get("draw_day", "")
        draw_date = report.get("draw_date", "")
        match_key = expander._match_key

        # Bestimme min_matches für die Query (Kategorie kann "3", "4+SZ" etc. sein)
        try:
            min_m = int(match_key.split("+")[0].strip())
        except (ValueError, IndexError):
            min_m = 2

        def worker():
            try:
                hits = self._fetch_hits(report_id, draw_day, draw_date, min_m)
                GLib.idle_add(
                    self._populate_expander, expander, hits, match_key, None,
                )
            except Exception as e:
                GLib.idle_add(
                    self._populate_expander, expander, [], match_key, str(e),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _fetch_hits(
        self, report_id: str, draw_day: str, draw_date: str, min_matches: int,
    ) -> list[dict]:
        """Hits laden — mit Cache."""
        cache_key = f"{report_id}_{min_matches}"
        cached = self._cache_get(self._hits_cache, cache_key)
        if cached is not None:
            return cached

        if self.api_client and report_id:
            data = self.api_client.get_report_hits(report_id, min_matches)
            hits = data.get("hits", [])
            accuracy = data.get("accuracy", {})
            self._cache_set(self._accuracy_cache, report_id, accuracy)
        elif self.db:
            hits = self.db.get_predictions_with_min_matches(
                draw_day, draw_date, min_matches,
            )
        else:
            hits = []

        self._cache_set(self._hits_cache, cache_key, hits)
        return hits

    def _populate_expander(
        self, expander: Adw.ExpanderRow,
        hits: list[dict], match_key: str, error: str | None,
    ) -> bool:
        """Expander mit Prediction-Cards fuellen (Main-Thread)."""
        # Placeholder entfernen
        if hasattr(expander, "_placeholder") and expander._placeholder:
            expander.remove(expander._placeholder)
            expander._placeholder = None

        if error:
            err_row = Adw.ActionRow(title=_("Fehler"), subtitle=error)
            expander.add_row(err_row)
            return False

        # Filtere auf exakte match_category
        filtered = [
            h for h in hits
            if str(h.get("matches", "")) == match_key
            or str(h.get("match_category", "")) == match_key
        ]

        if not filtered:
            empty_row = Adw.ActionRow(title=_("Keine Details verfügbar"))
            expander.add_row(empty_row)
            return False

        for hit in filtered:
            card = self._create_hit_card(hit)
            expander.add_row(card)

        return False

    def _create_hit_card(self, hit: dict) -> Adw.ActionRow:
        """Prediction-Card fuer einen Treffer erstellen."""
        position = hit.get("position", 0)
        pred_id = hit.get("id", 0)
        strategy = hit.get("strategy", "?")
        conf = hit.get("ml_confidence", 0) or 0
        match_cat = hit.get("match_category", "")
        bonus_match = hit.get("bonus_match", 0)

        # Zahlen parsen
        predicted_str = hit.get("predicted_numbers", "")
        actual_str = hit.get("actual_numbers", "")
        predicted = self._parse_numbers(predicted_str)
        actual = self._parse_numbers(actual_str)

        # Bonus parsen
        bonus_str = hit.get("predicted_bonus", "")
        predicted_bonus = self._parse_numbers(bonus_str) if bonus_str else []

        # Treffer-Zahlen ermitteln
        matching_nums = sorted(set(predicted) & set(actual))

        # ActionRow mit Zahlen-Kugeln
        row = Adw.ActionRow()
        row.set_title(f"#{pred_id}  |  {strategy}  |  Tipp {position}")

        subtitle_parts = [f"Conf: {conf:.0%}"]
        if match_cat:
            subtitle_parts.append(match_cat)
        if predicted_bonus:
            bonus_label = "SZ" if len(predicted_bonus) == 1 else "EZ"
            bonus_text = ", ".join(str(b) for b in predicted_bonus)
            bonus_hit = " ✓" if bonus_match else ""
            subtitle_parts.append(f"{bonus_label}: {bonus_text}{bonus_hit}")
        if matching_nums:
            subtitle_parts.append(f"Treffer: {', '.join(str(n) for n in matching_nums)}")
        row.set_subtitle("  |  ".join(subtitle_parts))

        # NumberBallRow als Suffix-Widget
        ball_row = NumberBallRow(
            numbers=predicted, matching=matching_nums, size=32,
        )
        ball_row.set_valign(Gtk.Align.CENTER)
        row.add_suffix(ball_row)

        return row

    def _load_draw_numbers(self, report: dict) -> dict:
        """Load actual draw numbers + SZ/bonus for display in report header."""
        draw_day = report.get("draw_day", "")
        draw_date = report.get("draw_date", "")
        if not draw_day or not draw_date:
            return {"numbers_text": "—"}
        try:
            from lotto_common.models.draw import DrawDay
            dd = DrawDay(draw_day)
            if self.api_client:
                draw = self.api_client.get_latest_draw(draw_day)
            elif self.db:
                draw = self.db.get_latest_draw(dd)
            else:
                return {"numbers_text": "—"}
            if not draw:
                return {"numbers_text": "—"}
            # Format: check if dict or object
            if isinstance(draw, dict):
                nums = draw.get("numbers", [])
                sz = draw.get("super_number", "")
                bonus = draw.get("bonus_numbers", [])
            else:
                nums = draw.sorted_numbers if hasattr(draw, "sorted_numbers") else []
                sz = getattr(draw, "super_number", "")
                bonus = getattr(draw, "bonus_numbers", [])
            nums_str = ", ".join(str(n) for n in nums)
            if bonus and isinstance(bonus, list) and len(bonus) > 0:
                bonus_str = " + EZ: " + ", ".join(str(b) for b in bonus)
                return {"numbers_text": f"{nums_str}{bonus_str}"}
            elif sz is not None and str(sz) != "":
                return {"numbers_text": f"{nums_str}  |  SZ: {sz}"}
            return {"numbers_text": nums_str}
        except Exception as e:
            logger.debug(f"Draw numbers load error: {e}")
            return {"numbers_text": "—"}

    @staticmethod
    def _parse_numbers(text) -> list[int]:
        """Zahlenstring oder Liste in sortierte int-Liste parsen."""
        if isinstance(text, list):
            return sorted(int(n) for n in text if str(n).strip().isdigit())
        if not text or not isinstance(text, str):
            return []
        text = text.strip()
        # JSON-Array?
        if text.startswith("["):
            try:
                return sorted(int(n) for n in json.loads(text))
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        # Komma- oder Leerzeichen-getrennt
        nums = []
        for part in text.replace(",", " ").split():
            part = part.strip()
            if part.isdigit():
                nums.append(int(part))
        return sorted(nums)

