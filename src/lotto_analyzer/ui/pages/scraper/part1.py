"""UI-Seite scraper: part1."""

from __future__ import annotations

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_analyzer.ui.widgets.draw_input import DrawInput
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from lotto_analyzer.ui.widgets.draw_input import DrawInput
from lotto_common.config import ConfigManager
from lotto_analyzer.ui.widgets.draw_input import DrawInput
from lotto_analyzer.ui.widgets.draw_input import DrawInput
from lotto_common.models.draw import DrawDay
from lotto_analyzer.ui.widgets.draw_input import DrawInput
from lotto_common.models.game_config import GameType, get_config
from lotto_analyzer.ui.widgets.draw_input import DrawInput


logger = get_logger("scraper.part1")

from lotto_analyzer.ui.widgets.help_button import HelpButton
from lotto_analyzer.ui.widgets.draw_input import DrawInput

import sqlite3

DAY_LABELS = {
    "saturday": "Samstag",
    "wednesday": "Mittwoch",
    "tuesday": "Dienstag",
    "friday": "Freitag",
}


class Part1Mixin:
    """Part1 Mixin."""

    def _ai_chat(self, message: str) -> str:
        """AI-Chat — lokal oder via Server."""
        if self._ai_analyst:
            return self._ai_analyst.chat(message)
        if self.api_client:
            return self.api_client.chat(message)
        raise RuntimeError("Kein AI-Backend verfügbar")

    def set_game_type(self, game_type: GameType) -> None:
        """Spieltyp wechseln — UI-Elemente anpassen."""
        self._game_type = game_type
        self._config = get_config(game_type)

        # Tag-Combos neu aufbauen
        # Crawl Tag-Combo
        day_model = Gtk.StringList()
        for day in self._config.draw_days:
            day_model.append(DAY_LABELS.get(day, day))
        day_model.append(_("Beide"))
        self._day_combo.set_model(day_model)
        self._day_combo.set_selected(0)

        # CSV Tag-Combo
        csv_day_model = Gtk.StringList()
        for day in self._config.draw_days:
            csv_day_model.append(DAY_LABELS.get(day, day))
        self._csv_day_combo.set_model(csv_day_model)
        self._csv_day_combo.set_selected(0)

        # Jahresbereich anpassen
        self._year_from.set_range(self._config.start_year, datetime.now().year)
        self._year_from.set_value(self._config.start_year)

        # Manuelle Eingabe anpassen
        if hasattr(self, '_draw_input'):
            self._draw_input.set_game_type(game_type)

    def _build_ui(self) -> None:
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        self.append(scrolled)

        clamp = Adw.Clamp(maximum_size=900)
        scrolled.set_child(clamp)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        clamp.set_child(content)
        self._content = content  # For mixins (part4 etc.)

        title = Gtk.Label(label=_("Daten-Crawler"))
        title.add_css_class("title-1")
        content.append(title)

        # ── Auto-Crawl Status ──
        status_group = Adw.PreferencesGroup(
            title=_("Auto-Crawl Status"),
            description=_("Automatische Prüfung auf neue Ziehungen"),
        )
        status_group.set_header_suffix(
            HelpButton(_("Zeigt ob der automatische Daten-Download aktiv ist und wann die nächste Prüfung stattfindet."))
        )
        content.append(status_group)

        self._status_row = Adw.ActionRow(title=_("Status"), subtitle=_("Bereit"))
        self._status_row.add_prefix(
            Gtk.Image.new_from_icon_name("emblem-synchronizing-symbolic")
        )
        status_group.add(self._status_row)

        self._next_check = Adw.ActionRow(title=_("Nächste Prüfung"), subtitle="—")
        status_group.add(self._next_check)

        # ── Manueller Crawl ──
        crawl_group = Adw.PreferencesGroup(
            title=_("Manueller Crawl"),
            description=_("Historische Daten herunterladen"),
        )
        content.append(crawl_group)

        self._day_combo = Adw.ComboRow(title=_("Ziehungstag"))
        self._day_combo.add_suffix(
            HelpButton(_("Welcher Wochentag gecrawlt werden soll. 'Beide' laedt Samstag und Mittwoch."))
        )
        day_model = Gtk.StringList()
        for d in self._config.draw_days:
            day_model.append(DAY_LABELS.get(d, d))
        day_model.append(_("Beide"))
        self._day_combo.set_model(day_model)
        crawl_group.add(self._day_combo)

        self._year_from = Adw.SpinRow.new_with_range(1955, datetime.now().year, 1)
        self._year_from.set_title(_("Von Jahr"))
        self._year_from.set_value(1955)
        self._year_from.add_suffix(
            HelpButton(_("Zeitraum der heruntergeladenen Ziehungen. Ab 1955 verfügbar."))
        )
        crawl_group.add(self._year_from)

        self._year_to = Adw.SpinRow.new_with_range(1955, datetime.now().year, 1)
        self._year_to.set_title(_("Bis Jahr"))
        self._year_to.set_value(datetime.now().year)
        crawl_group.add(self._year_to)

        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
            halign=Gtk.Align.CENTER,
        )
        btn_box.set_margin_top(12)

        self._crawl_btn = Gtk.Button(label=_("Crawl starten"))
        self._crawl_btn.add_css_class("suggested-action")
        self._crawl_btn.add_css_class("pill")
        self._crawl_btn.set_tooltip_text(_("Laedt alle Ziehungen im gewählten Zeitraum von lottozahlenonline.de herunter. Dauert je nach Zeitraum 1-5 Minuten."))
        self._crawl_btn.connect("clicked", self._on_crawl)
        self.register_readonly_button(self._crawl_btn)
        btn_box.append(self._crawl_btn)

        self._refresh_btn = Gtk.Button(label=_("Jetzt aktualisieren"))
        self._refresh_btn.add_css_class("pill")
        self._refresh_btn.set_tooltip_text(_("Prüft nur ob neue Ziehungen seit dem letzten Crawl verfügbar sind — schneller als voller Crawl."))
        self._refresh_btn.connect("clicked", self._on_refresh)
        self.register_readonly_button(self._refresh_btn)
        btn_box.append(self._refresh_btn)

        content.append(btn_box)

        self._progress = Gtk.ProgressBar()
        self._progress.set_visible(False)
        content.append(self._progress)

        self._crawl_result = Gtk.Label(label="")
        self._crawl_result.add_css_class("dim-label")
        self._crawl_result.set_wrap(True)
        self._crawl_result.set_visible(False)
        content.append(self._crawl_result)

        # ── CSV-Import ──
        csv_group = Adw.PreferencesGroup(
            title=_("CSV-Import"),
            description=_("Ziehungen aus CSV-Datei importieren"),
        )
        csv_group.set_header_suffix(
            HelpButton(_("Importiert Ziehungen aus einer CSV-Datei. Format: Datum, 6 Zahlen, Superzahl. Trennzeichen: Komma, Semikolon oder Tab."))
        )
        content.append(csv_group)

        self._csv_day_combo = Adw.ComboRow(title=_("Ziehungstag der CSV"))
        csv_day_model = Gtk.StringList()
        for d in self._config.draw_days:
            csv_day_model.append(DAY_LABELS.get(d, d))
        self._csv_day_combo.set_model(csv_day_model)
        csv_group.add(self._csv_day_combo)

        csv_btn_row = Adw.ActionRow(title=_("CSV-Datei auswählen"))
        csv_btn_row.set_subtitle(_("Format: Datum, Z1-Z6, SZ (Trennzeichen: , ; Tab)"))
        import_btn = Gtk.Button(label=_("Importieren"), valign=Gtk.Align.CENTER)
        import_btn.add_css_class("suggested-action")
        import_btn.connect("clicked", self._on_csv_import)
        csv_btn_row.add_suffix(import_btn)
        csv_group.add(csv_btn_row)

        self._csv_result = Gtk.Label(label="")
        self._csv_result.add_css_class("dim-label")
        self._csv_result.set_wrap(True)
        self._csv_result.set_visible(False)
        content.append(self._csv_result)

        # ── Manuelle Eingabe ──
        manual_group = Adw.PreferencesGroup(
            title=_("Manuelle Eingabe"),
            description=_("Ziehung manuell eintragen"),
        )
        manual_group.set_header_suffix(
            HelpButton(_("Eine einzelne Ziehung von Hand eintragen (z.B. wenn die Webseite nicht erreichbar ist)."))
        )
        content.append(manual_group)

        self._draw_input = DrawInput()
        self._draw_input.connect("draw-submitted", self._on_draw_submitted)
        manual_group.add(self._draw_input)

        # ── AI-Datenkontrolle ──
        ai_group = Adw.PreferencesGroup(
            title=_("AI-Datenkontrolle"),
            description=_("Claude prüft Pipeline: Quelle → DB → Statistik"),
        )
        ai_group.set_header_suffix(
            HelpButton(_("AI vergleicht die gerade heruntergeladenen Daten mit der Datenbank — prüft ob nichts verloren ging."))
        )
        content.append(ai_group)

        # 1) Verifikation: Quelle vs DB
        verify_row = Adw.ActionRow(
            title=_("Quelle ↔ DB Verifikation"),
            subtitle=_("Vergleicht letzte Crawl/Import-Daten mit der Datenbank"),
        )
        verify_row.add_prefix(Gtk.Image.new_from_icon_name("emblem-default-symbolic"))
        self._verify_btn = Gtk.Button(label=_("Verifizieren"), valign=Gtk.Align.CENTER)
        self._verify_btn.set_tooltip_text(_("Gescrapte Daten mit der Datenbank abgleichen"))
        self._verify_btn.connect("clicked", self._on_verify_source_vs_db)
        self._verify_btn.set_sensitive(False)
        verify_row.add_suffix(self._verify_btn)
        ai_group.add(verify_row)

        # 2) DB-Qualitätspruefung
        quality_row = Adw.ActionRow(
            title=_("DB-Qualitätspruefung"),
            subtitle=_("Lücken, Duplikate, Anomalien, fehlende Ziehungen"),
        )
        quality_row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
        self._quality_btn = Gtk.Button(label=_("Prüfen"), valign=Gtk.Align.CENTER)
        self._quality_btn.set_tooltip_text(_("Datenqualitaet prüfen"))
        self._quality_btn.connect("clicked", self._on_ai_quality_check)
        quality_row.add_suffix(self._quality_btn)
        ai_group.add(quality_row)

        # 3) DB-Anomalie-Prüfung (AI-gestuetzt)
        anomaly_row = Adw.ActionRow(
            title=_("DB-Anomalie-Prüfung (AI)"),
            subtitle=_("Duplikate, falsche Wochentage, Zahlen-Ausreisser, Dateninkonsistenzen"),
        )
        anomaly_row.add_prefix(Gtk.Image.new_from_icon_name("security-high-symbolic"))
        self._anomaly_btn = Gtk.Button(label=_("AI-Prüfung"), valign=Gtk.Align.CENTER)
        self._anomaly_btn.set_tooltip_text(_("AI prüft Daten auf Anomalien und Unregelmäßigkeiten"))
        self._anomaly_btn.connect("clicked", self._on_ai_anomaly_check)
        anomaly_row.add_suffix(self._anomaly_btn)
        ai_group.add(anomaly_row)

        # 4) Statistik-Daten prüfen
        stat_row = Adw.ActionRow(
            title=_("Statistik-Datengrundlage prüfen"),
            subtitle=_("Sind die richtigen Daten für die Analyse vorhanden?"),
        )
        stat_row.add_prefix(Gtk.Image.new_from_icon_name("utilities-system-monitor-symbolic"))
        self._stat_check_btn = Gtk.Button(label=_("Prüfen"), valign=Gtk.Align.CENTER)
        self._stat_check_btn.set_tooltip_text(_("Statistische Integrität der Daten prüfen"))
        self._stat_check_btn.connect("clicked", self._on_check_stat_data)
        stat_row.add_suffix(self._stat_check_btn)
        ai_group.add(stat_row)

        # ── Crawl-Monitor (Part 4) ──
        self._build_crawl_monitor()

        # AI-Ergebnis-Panel
        self._ai_panel = AIPanel(ai_analyst=self._ai_analyst, api_client=self.api_client,
                                  title=_("AI-Datenkontrolle"), config_manager=self.config_manager,
                                  db=self.db, page="scraper", app_db=self.app_db)
        content.append(self._ai_panel)

    # ═══════════════════════════════════════════
    # Crawl
    # ═══════════════════════════════════════════

    def set_api_client(self, client: "APIClient | None") -> None:
        """API-Client setzen."""
        super().set_api_client(client)
        self._ai_panel.api_client = client

    def _set_crawl_controls(self, sensitive: bool) -> None:
        if self._is_readonly:
            return  # READONLY: Buttons bleiben immer deaktiviert
        self._crawl_btn.set_sensitive(sensitive)
        self._refresh_btn.set_sensitive(sensitive)

    def _poll_crawl_task(self, task_id: str) -> None:
        """Crawl-Task per Polling abfragen bis fertig."""
        import time
        import json

        self._crawl_task_id = task_id

        # WS-Listener fuer instant Updates (Polling bleibt als Fallback)
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.on("task_update", self._on_ws_crawl_task)
        except Exception:
            pass

        def poller():
            max_polls = self.MAX_POLLS
            poll_count = 0
            try:
                while True:
                    if poll_count >= max_polls:
                        GLib.idle_add(
                            self._on_api_crawl_done, None,
                            _("Polling-Timeout nach 5 Minuten"),
                        )
                        return
                    poll_count += 1
                    time.sleep(self.POLL_INTERVAL)
                    task = self.api_client.get_task(task_id)
                    status = task.get("status", "?")
                    progress = task.get("progress", 0)
                    pct = int(progress * 100)
                    GLib.idle_add(
                        self._status_row.set_subtitle,
                        _("Crawl läuft... (%d%%)") % pct,
                    )
                    if status == "completed":
                        result_raw = task.get("result")
                        result = json.loads(result_raw) if result_raw else {}
                        GLib.idle_add(self._on_api_crawl_done, result, None)
                        return
                    elif status in ("failed", "cancelled"):
                        error = task.get("error", _("Unbekannter Fehler"))
                        GLib.idle_add(self._on_api_crawl_done, None, error)
                        return
            except Exception as e:
                GLib.idle_add(self._on_api_crawl_done, None, str(e))

        threading.Thread(target=poller, daemon=True).start()

    def _on_ws_crawl_task(self, data: dict) -> bool:
        """Handle WS task_update — trigger instant crawl status refresh."""
        task_id = data.get("id", "")
        if hasattr(self, "_crawl_task_id") and task_id == self._crawl_task_id:
            import json
            status = data.get("status", "")
            progress = data.get("progress", 0)
            pct = int(progress * 100)
            self._status_row.set_subtitle(_("Crawl läuft... (%d%%)") % pct)
            if status == "completed":
                result_raw = data.get("result")
                try:
                    result = json.loads(result_raw) if isinstance(result_raw, str) else (result_raw or {})
                except Exception:
                    result = {}
                self._on_api_crawl_done(result, None)
            elif status in ("failed", "cancelled"):
                error = data.get("error", _("Unbekannter Fehler"))
                self._on_api_crawl_done(None, error)
        return False

    def _on_crawl(self, button: Gtk.Button) -> None:
        with self._op_lock:
            if self._crawling:
                return
            self._crawling = True

        try:
            # Client-Modus: Crawl via API (gibt jetzt task_id zurück)
            if self.api_client and not self.db:
                self._set_crawl_controls(False)
                self._crawl_result.set_visible(False)
                self._status_row.set_subtitle(_("Crawl via Server..."))

                day_idx = self._day_combo.get_selected()
                year_from = int(self._year_from.get_value())
                year_to = int(self._year_to.get_value())
                draw_days_list = self._config.draw_days
                day_str = draw_days_list[day_idx] if day_idx < len(draw_days_list) else "both"

                def api_worker():
                    try:
                        data = self.api_client.crawl(day_str, year_from, year_to)
                        task_id = data.get("task_id")
                        if task_id:
                            self._poll_crawl_task(task_id)
                        else:
                            # Fallback: alte synchrone Antwort
                            GLib.idle_add(self._on_api_crawl_done, data, None)
                    except (ConnectionError, TimeoutError, OSError) as e:
                        GLib.idle_add(self._on_api_crawl_done, None, str(e))
                    except Exception as e:
                        logger.exception(f"Unerwarteter Fehler beim API-Crawl: {e}")
                        GLib.idle_add(self._on_api_crawl_done, None, str(e))

                threading.Thread(target=api_worker, daemon=True).start()
                return

            if not self.db:
                with self._op_lock:
                    self._crawling = False
                return

            # Standalone: Crawl nur via API verfügbar
            logger.warning("Crawl nur via API verfügbar (core-Import entfernt)")
            with self._op_lock:
                self._crawling = False
            self._status_row.set_subtitle(_("Nur im Server-Modus verfügbar"))
        except Exception as e:
            logger.error(f"Crawl-Start fehlgeschlagen: {e}")
            with self._op_lock:
                self._crawling = False
            self._set_crawl_controls(True)
            self._status_row.set_subtitle(_("Fehler: %s") % e)

    def _update_progress(self, fraction: float, message: str) -> bool:
        self._progress.set_fraction(min(fraction, 1.0))
        self._progress.set_text(message)
        self._progress.set_show_text(True)
        return False

