"""Statistik-Seite: Charts, Jahres-Slider, Tag-Toggle, AI-Analyse."""

from __future__ import annotations

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.i18n import _
from lotto_common.config import ConfigManager
from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_analyzer.ui.widgets.chart_view import ChartView
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from lotto_analyzer.ui.widgets.help_button import HelpButton
from lotto_analyzer.ui.ui_helpers import show_toast
from lotto_common.utils.logging_config import get_logger

logger = get_logger("statistics_page")


class StatisticsPage(BasePage):
    """Statistische Analyse mit Diagrammen und AI-Kommentar."""

    def __init__(self, config_manager: ConfigManager, db: Database | None, app_mode: str, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager=config_manager, db=db, app_mode=app_mode, api_client=api_client,
                         app_db=app_db, backtest_db=backtest_db)
        self._analyzing = False
        self._ai_analyst = None
        self._last_analysis_data: dict | None = None
        self._game_type: GameType = GameType.LOTTO6AUS49
        self._config = get_config(self._game_type)

        self._build_ui()

    def _build_ui(self) -> None:
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        self.append(scrolled)

        clamp = Adw.Clamp(maximum_size=1100)
        scrolled.set_child(clamp)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        clamp.set_child(content)

        title = Gtk.Label(label=_("Statistik"))
        title.add_css_class("title-1")
        content.append(title)

        # Steuerung
        ctrl_group = Adw.PreferencesGroup(title=_("Analyse-Parameter"))
        content.append(ctrl_group)

        # Tag-Auswahl
        self._day_combo = Adw.ComboRow(title=_("Ziehungstag"))
        self._day_combo.add_suffix(
            HelpButton(_("Für welchen Wochentag die Statistik berechnet wird."))
        )
        day_model = Gtk.StringList()
        for d in [_("Samstag"), _("Mittwoch"), _("Beide")]:
            day_model.append(d)
        self._day_combo.set_model(day_model)
        ctrl_group.add(self._day_combo)

        # Jahresbereich
        self._year_from = Adw.SpinRow.new_with_range(1955, datetime.now().year, 1)
        self._year_from.set_title(_("Von Jahr"))
        self._year_from.set_value(2020)
        self._year_from.add_suffix(
            HelpButton(_("Zeitraum der Analyse. Längere Zeiträume = zuverlässigere Statistik."))
        )
        ctrl_group.add(self._year_from)

        self._year_to = Adw.SpinRow.new_with_range(1955, datetime.now().year, 1)
        self._year_to.set_title(_("Bis Jahr"))
        self._year_to.set_value(datetime.now().year)
        ctrl_group.add(self._year_to)

        # Analyse-Button + Spinner
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
        )
        btn_box.set_margin_top(12)
        self._analyze_btn = Gtk.Button(label=_("Analyse starten"))
        self._analyze_btn.add_css_class("suggested-action")
        self._analyze_btn.add_css_class("pill")
        self._analyze_btn.set_tooltip_text(_("Berechnet Häufigkeiten, Hot/Cold-Zahlen, Paare und Trends."))
        self._analyze_btn.connect("clicked", self._on_analyze)
        btn_box.append(self._analyze_btn)

        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        btn_box.append(self._spinner)

        content.append(btn_box)

        # Chart-Bereich: Notebook mit 5 Tabs
        self._notebook = Gtk.Notebook()
        self._notebook.set_vexpand(False)
        self._notebook.set_size_request(-1, 400)

        self._chart_freq = ChartView(title=_("Häufigkeit"))
        self._chart_freq.set_tooltip_text(_("Wie oft jede Zahl (1-49) insgesamt gezogen wurde. Balkendiagramm."))
        self._notebook.append_page(self._chart_freq, Gtk.Label(label=_("Häufigkeit")))

        self._chart_hot_cold = ChartView(title=_("Hot/Cold"))
        self._chart_hot_cold.set_tooltip_text(_("Hot = häufig gezogene Zahlen (rot), Cold = selten gezogene (blau)."))
        self._notebook.append_page(self._chart_hot_cold, Gtk.Label(label=_("Hot/Cold")))

        self._chart_super = ChartView(title=_("Superzahl"))
        self._chart_super.set_tooltip_text(_("Verteilung der Superzahl (0-9). Sollte ungefähr gleichverteilt sein."))
        self._notebook.append_page(self._chart_super, Gtk.Label(label=_("Superzahl")))

        self._chart_pairs = ChartView(title=_("Paare"))
        self._chart_pairs.set_tooltip_text(_("Welche Zahlenpaare am häufigsten zusammen gezogen wurden."))
        self._notebook.append_page(self._chart_pairs, Gtk.Label(label=_("Paare")))

        self._chart_trends = ChartView(title=_("Trends"))
        self._chart_trends.set_tooltip_text(_("Aktuelle Tendenz: steigt eine Zahl in der Häufigkeit oder faellt sie?"))
        self._notebook.append_page(self._chart_trends, Gtk.Label(label=_("Trends")))

        content.append(self._notebook)

        # Statistik-Zusammenfassung + "An AI senden"-Button
        summary_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        summary_box.set_margin_top(12)

        self._summary_label = Gtk.Label(label="")
        self._summary_label.set_wrap(True)
        self._summary_label.set_xalign(0)
        self._summary_label.set_selectable(True)
        self._summary_label.set_visible(False)
        summary_box.append(self._summary_label)

        action_box = Gtk.Box(spacing=8)

        self._send_ai_btn = Gtk.Button(label=_("An AI senden"))
        self._send_ai_btn.set_icon_name("user-available-symbolic")
        self._send_ai_btn.add_css_class("flat")
        self._send_ai_btn.set_tooltip_text(_("Statistik-Ergebnis manuell an AI-Panel senden"))
        self._send_ai_btn.set_visible(False)
        self._send_ai_btn.connect("clicked", self._on_send_to_ai)
        action_box.append(self._send_ai_btn)

        self._csv_btn = Gtk.Button(label=_("CSV-Export"))
        self._csv_btn.set_icon_name("document-save-symbolic")
        self._csv_btn.add_css_class("flat")
        self._csv_btn.set_tooltip_text(_("Statistik als CSV-Datei exportieren"))
        self._csv_btn.set_visible(False)
        self._csv_btn.connect("clicked", self._on_export_csv)
        action_box.append(self._csv_btn)

        summary_box.append(action_box)

        content.append(summary_box)

        # AI-Panel
        self._init_ai()
        self._ai_panel = AIPanel(ai_analyst=self._ai_analyst, api_client=self.api_client,
                                  title=_("AI-Analyse"), config_manager=self.config_manager,
                                  db=self.db, page="statistics", app_db=self.app_db)
        content.append(self._ai_panel)

    def set_game_type(self, game_type: GameType) -> None:
        """Spieltyp wechseln — UI-Elemente anpassen."""
        self._game_type = game_type
        self._config = get_config(game_type)

        # Tag-Combo neu aufbauen
        day_labels = {
            "saturday": _("Samstag"),
            "wednesday": _("Mittwoch"),
            "tuesday": _("Dienstag"),
            "friday": _("Freitag"),
        }
        day_model = Gtk.StringList()
        for day in self._config.draw_days:
            day_model.append(day_labels.get(day, day))
        day_model.append(_("Beide"))
        self._day_combo.set_model(day_model)
        self._day_combo.set_selected(0)

        # Jahresbereich anpassen
        self._year_from.set_range(self._config.start_year, datetime.now().year)
        self._year_from.set_value(max(2020, self._config.start_year))

        # Chart-Tabs anpassen
        bonus_label = self._config.bonus_name
        self._notebook.set_tab_label(
            self._chart_super,
            Gtk.Label(label=bonus_label),
        )

    def _init_ai(self) -> None:
        """AI-Analyst initialisieren — im Client-Modus via Server."""
        # Standalone-AI entfernt: AI läuft immer auf dem Server
        pass

    def _get_draw_day(self) -> DrawDay | None:
        """Ausgewählten Ziehungstag ermitteln."""
        idx = self._day_combo.get_selected()
        draw_days = self._config.draw_days
        if idx < len(draw_days):
            return DrawDay(draw_days[idx])
        return None  # Beide

    def set_api_client(self, client: "APIClient | None") -> None:
        """API-Client setzen."""
        super().set_api_client(client)
        self._ai_panel.api_client = client

    def refresh(self) -> None:
        """Auto-refresh: Analyse nur starten wenn Daten veraltet (>5min)."""
        if not self._analyzing and self.is_stale():
            self._on_analyze(self._analyze_btn)

    def _on_analyze(self, button: Gtk.Button) -> None:
        """Analyse starten."""
        if self._analyzing:
            return
        if not self.db and not self.api_client:
            self._summary_label.set_label(
                _("Keine Datenbank verfügbar. Bitte zuerst Daten crawlen.")
            )
            self._summary_label.set_visible(True)
            return

        self._analyzing = True
        self._analyze_btn.set_sensitive(False)
        self._spinner.set_visible(True)
        self._spinner.start()

        draw_day = self._get_draw_day()
        year_from = int(self._year_from.get_value())
        year_to = int(self._year_to.get_value())

        if year_from > year_to:
            self._year_from.set_value(year_to)
            self._year_to.set_value(year_from)
            year_from, year_to = year_to, year_from

        if not self.api_client:
            self._analyzing = False
            self._analyze_btn.set_sensitive(True)
            self._spinner.stop()
            self._spinner.set_visible(False)
            self._summary_label.set_label(
                _("Keine API-Verbindung. Bitte mit Server verbinden.")
            )
            self._summary_label.set_visible(True)
            return

        # Statistik via API holen
        def api_worker():
            try:
                day_str = draw_day.value if draw_day else "both"
                data = self.api_client.get_statistics(
                    day_str, year_from, year_to,
                    game_type=self._game_type.value,
                )
                GLib.idle_add(self._on_api_analysis_done, data, None)
            except (ConnectionError, TimeoutError, OSError) as e:
                GLib.idle_add(self._on_api_analysis_done, None, str(e))
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler bei API-Analyse: {e}")
                GLib.idle_add(self._on_api_analysis_done, None, str(e))

        threading.Thread(target=api_worker, daemon=True).start()

    def _on_api_analysis_done(self, data: dict | None, error: str | None) -> bool:
        """API-Analyse-Ergebnis anzeigen (Client-Modus, Main-Thread)."""
        self.mark_refreshed()
        self._analyzing = False
        self._analyze_btn.set_sensitive(True)
        self._spinner.stop()
        self._spinner.set_visible(False)

        if error:
            self._summary_label.set_label(_("Fehler: %s") % error)
            self._summary_label.set_visible(True)
            return False

        if not data or data.get("total_draws", 0) == 0:
            self._summary_label.set_label(_("Keine Daten im gewählten Zeitraum."))
            self._summary_label.set_visible(True)
            return False

        # Hilfsklasse: Dict → Objekt mit Attributen (für ChartView)
        class _Obj:
            def __init__(self, d: dict):
                self.__dict__.update(d)

        hot = data.get("hot_numbers", [])
        cold = data.get("cold_numbers", [])

        # Charts plotten (try/except damit Darstellungsfehler die UI nicht blockieren)
        try:
            freqs = [_Obj(f) for f in data.get("frequencies", [])]
            if freqs:
                x = [f.number for f in freqs]
                y = [f.count for f in freqs]
                hot_idx = [i for i, f in enumerate(freqs) if f.number in hot]
                freq_label = (
                    _("Zahlen-Häufigkeit (%d-%d)") % (self._config.main_min, self._config.main_max)
                )
                self._chart_freq.plot_bar(
                    x, y, title=freq_label,
                    xlabel=_("Zahl"), ylabel=_("Häufigkeit"),
                    highlight_indices=hot_idx,
                )

            if freqs and hot and cold:
                self._chart_hot_cold.plot_hot_cold(
                    freqs, hot, cold, title=_("Hot/Cold Zahlen"),
                )

            sz_freqs = [_Obj(f) for f in data.get("super_number_freq", [])]
            if sz_freqs:
                bonus_label = (
                    f"{self._config.bonus_name}-" + _("Verteilung") + " "
                    f"({self._config.bonus_min}-{self._config.bonus_max})"
                )
                self._chart_super.plot_super_number(sz_freqs, title=bonus_label)

            pairs = [_Obj(p) for p in data.get("pair_frequencies", [])]
            if pairs:
                self._chart_pairs.plot_pairs(pairs, title=_("Häufigste Zahlenpaare"), top_n=20)

            trends = [_Obj(t) for t in data.get("trends", [])]
            if trends:
                self._chart_trends.plot_trends(trends, title=_("Trend-Momentum"))
        except Exception as chart_err:
            import logging
            logging.getLogger("statistics_page").warning(f"Chart-Fehler: {chart_err}")

        # Text-Summary
        parts = [_("Ziehungen: %d") % data.get("total_draws", 0)]
        parts.append(_("Zeitraum: %s - %s") % (data.get("year_from", "?"), data.get("year_to", "?")))
        if hot:
            parts.append(_("Hot Numbers: %s") % str(hot[:10]))
        if cold:
            parts.append(_("Cold Numbers: %s") % str(cold[:10]))
        overdue = [g for g in data.get("gaps", []) if g.get("is_overdue")]
        if overdue:
            nums = [str(g["number"]) for g in overdue[:5]]
            parts.append(_("Überfällig: %s") % ", ".join(nums))
        # Ergebnis für CSV-Export speichern
        self._last_analysis_data = data

        summary = "\n".join(parts)
        self._summary_label.set_label(summary)
        self._summary_label.set_visible(True)
        self._send_ai_btn.set_visible(True)
        self._csv_btn.set_visible(True)

        # AI-Panel Referenzen aktualisieren (für manuellen "An AI senden" Button)
        self._ai_panel.ai_analyst = self._ai_analyst
        self._ai_panel.api_client = self.api_client

        return False

    def _on_send_to_ai(self, button: Gtk.Button) -> None:
        """Statistik-Zusammenfassung manuell an AI-Panel senden."""
        summary = self._summary_label.get_label()
        if not summary:
            return
        self._ai_panel.ai_analyst = self._ai_analyst
        self._ai_panel.api_client = self.api_client
        self._ai_panel.analyze(
            f"Analysiere diese Lotto-Statistik und gib Empfehlungen:\n\n{summary}"
        )

    def _on_export_csv(self, _btn) -> None:
        """Statistik-Daten als CSV exportieren."""
        if not self._last_analysis_data:
            return

        dialog = Gtk.FileDialog()
        dialog.set_title(_("Statistik als CSV speichern"))

        from gi.repository import Gio
        csv_filter = Gtk.FileFilter()
        csv_filter.set_name(_("CSV-Dateien"))
        csv_filter.add_pattern("*.csv")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(csv_filter)
        dialog.set_filters(filters)

        from pathlib import Path
        dialog.set_initial_name("lotto_statistik.csv")

        dialog.save(
            self.get_root(),
            None,
            self._on_csv_save_response,
        )

    def _on_csv_save_response(self, dialog, result) -> None:
        """CSV-Datei schreiben."""
        try:
            file = dialog.save_finish(result)
        except Exception as e:
            logger.warning(f"CSV-Speicherdialog abgebrochen oder fehlgeschlagen: {e}")
            return
        if not file:
            return

        import csv
        path = file.get_path()
        data = self._last_analysis_data

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=";")

                # Meta
                writer.writerow([_("Statistik-Export")])
                writer.writerow([_("Ziehungen"), data.get("total_draws", 0)])
                writer.writerow([_("Zeitraum"), f"{data.get('year_from', '')}-{data.get('year_to', '')}"])
                writer.writerow([_("Hot Numbers"), ", ".join(str(n) for n in data.get("hot_numbers", []))])
                writer.writerow([_("Cold Numbers"), ", ".join(str(n) for n in data.get("cold_numbers", []))])
                writer.writerow([])

                # Häufigkeiten
                writer.writerow([_("--- Häufigkeiten ---")])
                writer.writerow([_("Zahl"), _("Anzahl"), _("Prozent")])
                for f in data.get("frequencies", []):
                    writer.writerow([f["number"], f["count"], f"{f['percentage']:.2f}%"])
                writer.writerow([])

                # Bonus/Superzahl
                writer.writerow([_("--- Superzahl/Eurozahlen ---")])
                writer.writerow([_("Zahl"), _("Anzahl"), _("Prozent")])
                for f in data.get("super_number_freq", []):
                    writer.writerow([f["number"], f["count"], f"{f['percentage']:.2f}%"])
                writer.writerow([])

                # Paare
                writer.writerow([_("--- Häufigste Paare ---")])
                writer.writerow([_("Zahl A"), _("Zahl B"), _("Anzahl"), _("Prozent")])
                for p in data.get("pair_frequencies", [])[:30]:
                    writer.writerow([p["number_a"], p["number_b"], p["count"], f"{p['percentage']:.2f}%"])
                writer.writerow([])

                # Lücken
                gaps = data.get("gaps", [])
                if gaps:
                    writer.writerow([_("--- Lückenanalyse ---")])
                    writer.writerow([_("Zahl"), _("Aktuelle Lücke"), _("Durchschnitt"), _("Maximum"), _("Überfällig")])
                    for g in gaps:
                        writer.writerow([g["number"], g["current_gap"], f"{g['average_gap']:.1f}", g["max_gap"], _("Ja") if g.get("is_overdue") else ""])
                    writer.writerow([])

                # Trends
                trends = data.get("trends", [])
                if trends:
                    writer.writerow([_("--- Trends ---")])
                    writer.writerow([_("Zahl"), _("Trend"), _("Aktuelle Freq."), _("Gesamt Freq."), _("Momentum")])
                    for t in trends:
                        writer.writerow([t["number"], t["trend"], f"{t['recent_frequency']:.4f}", f"{t['overall_frequency']:.4f}", f"{t['momentum']:.4f}"])

            show_toast(self, _("CSV exportiert: %s") % path)
        except Exception as e:
            self._summary_label.set_label(_("CSV-Export Fehler: %s") % e)
