"""UI-Seite dashboard: part2."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_analyzer.ui.pages.dashboard.page import _DAY_NAMES

logger = get_logger("dashboard.part2")



from lotto_analyzer.ui.widgets.help_button import HelpButton


class Part2Mixin2:
    """Teil 2 von Part2Mixin."""

    def _update_recommendations_ui(self, recs: dict) -> bool:
        """Kaufempfehlungen im UI aktualisieren — pro Tag getrennte Gruppen mit Scroll."""
        for widget in self._rec_day_groups:
            self._rec_container.remove(widget)
        self._rec_day_groups.clear()

        _ej_suffix = {"tuesday": " (EJ)", "friday": " (EJ)"}

        for day_str, rec in recs.items():
            name = _DAY_NAMES.get(day_str, day_str) + _ej_suffix.get(day_str, "")

            if not rec or not rec.get("tips"):
                # Leere Gruppe für diesen Tag anzeigen
                group = Adw.PreferencesGroup(
                    title=f"{name}",
                    description=_("Keine Tipps vorhanden — erst Vorhersagen generieren"),
                )
                row = Adw.ActionRow(
                    title=_("Noch keine Empfehlungen"),
                    subtitle=_("Generiere Tipps im Generator-Tab"),
                )
                row.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
                group.add(row)
                self._rec_container.append(group)
                self._rec_day_groups.append(group)
                continue

            tips = rec.get("tips", [])
            total = rec.get("total_available", 0)
            countdown = rec.get("countdown", "?")
            cost = rec.get("estimated_cost", "?")
            draw_date = rec.get("draw_date", "?")

            # Outer-Box: Header-Label + scrollbarer Bereich + Button
            day_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

            # Header als PreferencesGroup (nur Titel, keine Rows)
            header_group = Adw.PreferencesGroup(
                title=f"{name} — {draw_date}",
                description=f"{len(tips)} Tipps | ~{cost} | {countdown}",
            )
            day_box.append(header_group)

            # Scrollbare Tipps-Liste
            tips_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            tip_group = Adw.PreferencesGroup()
            for i, tip in enumerate(tips, 1):
                row = Adw.ActionRow(
                    title=f"{i}. {tip.get('numbers', '?')}",
                    subtitle=f"{tip.get('strategy', '?')} — Score: {tip.get('score', 0):.2f}",
                )
                row.add_prefix(Gtk.Image.new_from_icon_name("starred-symbolic"))
                tip_group.add(row)
            tips_box.append(tip_group)

            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_child(tips_box)
            # Hoehe explizit: Adw.ActionRow ~56px, schrumpft bei wenig, max 600px
            row_h = 56
            h = min(len(tips) * row_h, 600)
            scroll.set_min_content_height(max(h, 60))
            scroll.set_max_content_height(600)

            day_box.append(scroll)

            # "An AI-Chat senden" Button
            send_box = Gtk.Box(halign=Gtk.Align.CENTER)
            send_box.set_margin_top(8)
            send_btn = Gtk.Button(label=_("An AI-Chat senden"))
            send_btn.set_tooltip_text(_("Kaufempfehlungen an den AI-Chat senden"))
            send_btn.set_icon_name("mail-send-symbolic")
            send_btn.add_css_class("pill")
            send_btn.connect("clicked", self._on_send_recs_to_chat, name, draw_date, tips)
            send_box.append(send_btn)
            day_box.append(send_box)

            self._rec_container.append(day_box)
            self._rec_day_groups.append(day_box)

        if not recs:
            empty_group = Adw.PreferencesGroup()
            row = Adw.ActionRow(title=_("Keine Empfehlungen"), subtitle=_("Noch keine Vorhersagen vorhanden"))
            empty_group.add(row)
            self._rec_container.append(empty_group)
            self._rec_day_groups.append(empty_group)

        return False

    def _on_send_recs_to_chat(self, button: Gtk.Button, day_name: str, draw_date: str, tips: list[dict]) -> None:
        """Kaufempfehlungen als Nachricht an AI-Chat senden."""
        lines = [_("Kaufempfehlungen für %s (%s):") % (day_name, draw_date), ""]
        for i, tip in enumerate(tips, 1):
            nums = tip.get("numbers", "?")
            strat = tip.get("strategy", "?")
            score = tip.get("score", 0)
            lines.append(f"{i}. {nums}  ({strat}, Score: {score:.2f})")
        lines.append("")
        lines.append(_("Bitte analysiere diese Empfehlungen: Welche Tipps sind besonders vielversprechend und warum?"))
        message = "\n".join(lines)
        self._ai_panel.analyze(message)

    # ══════════════════════════════════════════════
    # Server & System Status
    # ══════════════════════════════════════════════

    def _build_server_status_section(self, content: Gtk.Box) -> None:
        """Server-Status Sektion aufbauen."""
        self._server_group = Adw.PreferencesGroup(
            title=_("Server &amp; System"),
            description=_("Verbindung, ML-Modelle, Telegram"),
        )
        self._server_group.set_header_suffix(
            HelpButton(_("Zeigt den Status von Server, ML-Modellen, Telegram-Bot und laufenden Tasks."))
        )
        content.append(self._server_group)

        # Server-Status
        self._server_row = Adw.ActionRow(
            title=_("Server"),
            subtitle=_("Wird geprüft..."),
        )
        self._server_icon = Gtk.Image.new_from_icon_name("network-server-symbolic")
        self._server_row.add_prefix(self._server_icon)
        self._server_group.add(self._server_row)

        # Telegram-Status
        self._telegram_row = Adw.ActionRow(
            title=_("Telegram-Bot"),
            subtitle=_("Unbekannt"),
        )
        self._telegram_row.add_prefix(
            Gtk.Image.new_from_icon_name("user-available-symbolic")
        )
        self._server_group.add(self._telegram_row)

        # ML-Modelle Quick-Status
        self._ml_quick_row = Adw.ActionRow(
            title=_("ML-Modelle"),
            subtitle=_("Wird geprüft..."),
        )
        self._ml_quick_row.add_prefix(
            Gtk.Image.new_from_icon_name("applications-science-symbolic")
        )
        self._server_group.add(self._ml_quick_row)

        # Laufende Tasks
        self._tasks_row = Adw.ActionRow(
            title=_("Laufende Tasks"),
            subtitle="0",
        )
        self._tasks_row.add_prefix(
            Gtk.Image.new_from_icon_name("emblem-system-symbolic")
        )
        self._server_group.add(self._tasks_row)

        # Nächste Ziehung
        self._next_draw_row = Adw.ActionRow(
            title=_("Nächste Ziehung"),
            subtitle=_("Wird berechnet..."),
        )
        self._next_draw_row.add_prefix(
            Gtk.Image.new_from_icon_name("x-office-calendar-symbolic")
        )
        self._countdown_label = Gtk.Label(label="", css_classes=["heading"])
        self._next_draw_row.add_suffix(self._countdown_label)
        self._server_group.add(self._next_draw_row)

        # Countdown-Timer (jede Minute aktualisieren)
        self._next_draw_dt = None  # datetime der nächsten Ziehung
        self._notified_3h = False
        self._notified_1h = False
        self._countdown_timer_id = GLib.timeout_add_seconds(self.COUNTDOWN_INTERVAL, self._update_countdown)
        self._next_draw_day_str = ""

        # Jackpot — dynamische Zeilen pro Ziehungstag
        self._jackpot_rows: dict[str, Adw.ActionRow] = {}
        self._build_jackpot_rows()

        # --- Datenquellen-Aktivität ---
        self._activity_group = Adw.PreferencesGroup(
            title=_("Datenquellen-Aktivität"),
            description=_("Letzte Server-Datenabrufe von externen Quellen"),
        )
        self._activity_group.set_header_suffix(
            HelpButton(_("Zeigt wann der Server Daten von externen Quellen geholt hat."))
        )
        content.append(self._activity_group)

        # Telegram-Button
        tg_btn = Gtk.Button(label=_("An Telegram senden"))
        tg_btn.set_tooltip_text(_("Aktivitätsbericht per Telegram senden"))
        tg_btn.add_css_class("flat")
        tg_btn.connect("clicked", self._on_send_activity_telegram)
        self._activity_tg_row = Adw.ActionRow(title=_("Protokoll teilen"))
        self._activity_tg_row.add_suffix(tg_btn)
        self._activity_tg_row.set_activatable_widget(tg_btn)
        self._activity_group.add(self._activity_tg_row)

        # Platzhalter-Zeilen
        self._activity_rows: list[Adw.ActionRow] = []

    def _build_jackpot_rows(self) -> None:
        """Dynamische Jackpot-Zeilen pro Ziehungstag aufbauen."""
        # Alte Zeilen entfernen
        for row in self._jackpot_rows.values():
            self._server_group.remove(row)
        self._jackpot_rows.clear()

        # Neue Zeilen erstellen
        for day_str in self._config.draw_days:
            name = _("Jackpot %s") % _DAY_NAMES.get(day_str, day_str)
            row = Adw.ActionRow(title=name, subtitle=_("Keine Daten"))
            row.add_prefix(Gtk.Image.new_from_icon_name("starred-symbolic"))
            # (i)-Button für Detail-Popup
            info_btn = Gtk.Button.new_from_icon_name("dialog-information-symbolic")
            info_btn.set_valign(Gtk.Align.CENTER)
            info_btn.set_tooltip_text(_("Alle Gewinnklassen anzeigen"))
            info_btn.add_css_class("flat")
            info_btn.connect("clicked", self._on_jackpot_info_clicked, day_str)
            row.add_suffix(info_btn)
            row.set_activatable_widget(info_btn)
            self._server_group.add(row)
            self._jackpot_rows[day_str] = row

    def _load_server_status(self) -> None:
        """Server-Status-Daten laden."""
        def worker():
            server_ok = False
            tg_status = None
            ml_status = None
            task_count = 0
            next_draw_info = ""
            jackpot_infos: dict[str, str] = {}

            try:
                if self.app_mode == "client" and self.api_client:
                    # Server-Health
                    try:
                        health = self.api_client.health()
                        server_ok = True
                    except Exception as e:
                        logger.warning(f"Server-Health Abfrage fehlgeschlagen: {e}")

                    # Telegram
                    try:
                        tg_status = self.api_client.telegram_status()
                    except Exception as e:
                        logger.warning(f"Telegram-Status Abfrage fehlgeschlagen: {e}")

                    # ML
                    try:
                        ml_status = self.api_client.ml_status()
                    except Exception as e:
                        logger.warning(f"ML-Status Abfrage fehlgeschlagen: {e}")

                    # Tasks
                    try:
                        tasks = self.api_client.get_tasks(status="running")
                        task_count = len(tasks)
                    except Exception as e:
                        logger.warning(f"Tasks Abfrage fehlgeschlagen: {e}")
                else:
                    server_ok = True  # Standalone

                    # Telegram: Config prüfen
                    try:
                        tg_cfg = self.config_manager.config.telegram
                        if tg_cfg and tg_cfg.bot_token:
                            tg_status = {"running": False, "standalone": True}
                        else:
                            tg_status = {"not_configured": True}
                    except Exception as e:
                        logger.warning(f"Telegram-Config Prüfung fehlgeschlagen: {e}")
                        tg_status = {"not_configured": True}

                    # ML: Modell-Dateien prüfen
                    try:
                        from pathlib import Path
                        ml_dir = Path.home() / ".local" / "share" / "lotto-analyzer" / "ml_models"
                        if ml_dir.exists():
                            model_files = list(ml_dir.glob("*.pt")) + list(ml_dir.glob("*.pkl")) + list(ml_dir.glob("*.joblib"))
                            if model_files:
                                ml_status = {"standalone_count": len(model_files)}
                            else:
                                ml_status = {"not_trained": True}
                        else:
                            ml_status = {"not_trained": True}
                    except Exception as e:
                        logger.warning(f"ML-Modelle Prüfung fehlgeschlagen: {e}")
                        ml_status = {"not_trained": True}

                # Nächste Ziehung (reine Datumsberechnung, kein core-Import)
                try:
                    from datetime import date, timedelta
                    _day_weekdays = {
                        "saturday": 5, "wednesday": 2,
                        "tuesday": 1, "friday": 4,
                    }
                    _names = {
                        "saturday": "Sa", "wednesday": "Mi",
                        "tuesday": "Di", "friday": "Fr",
                    }
                    from datetime import datetime as _dt
                    # Ziehungszeiten (Stunde:Minute)
                    _draw_times = {
                        "wednesday": (18, 25),  # 6aus49 Mi 18:25
                        "saturday": (19, 25),   # 6aus49 Sa 19:25
                        "tuesday": (20, 0),     # EJ Di 20:00
                        "friday": (20, 0),      # EJ Fr 20:00
                    }
                    today = date.today()
                    now = _dt.now()
                    best_delta = 999
                    best_draw_dt = None
                    best_day_str = ""
                    for day_str in self._config.draw_days:
                        target_wd = _day_weekdays.get(day_str)
                        if target_wd is None:
                            continue
                        draw_h, draw_m = _draw_times.get(day_str, (20, 0))
                        days_ahead = (target_wd - today.weekday()) % 7
                        if days_ahead == 0:
                            # Heute: vorbei wenn Ziehungszeit + 1h ueberschritten
                            if now.hour >= draw_h + 1:
                                days_ahead = 7
                        next_date = today + timedelta(days=days_ahead)
                        delta = (next_date - today).days
                        short = _names.get(day_str, day_str[:2])

                        # Tipps zaehlen via API
                        tip_count = 0
                        try:
                            if self.api_client:
                                preds = self.api_client.get_predictions(
                                    day_str, next_date.isoformat(), limit=1,
                                )
                                tip_count = preds.get("total", 0)
                        except Exception as e:
                            logger.warning(f"Tipps zaehlen fehlgeschlagen ({day_str}): {e}")

                        if delta < best_delta:
                            best_delta = delta
                            best_draw_dt = _dt(
                                next_date.year, next_date.month, next_date.day,
                                draw_h, draw_m,
                            )
                            best_day_str = day_str
                            day_text = _("heute") if delta == 0 else _("in %d Tagen") % delta
                            next_draw_info = (
                                f"{short} {next_date.strftime('%d.%m.')} "
                                f"({day_text}) — " + _("%d Tipps bereit") % tip_count
                            )
                    # Countdown-Daten speichern
                    if best_draw_dt:
                        if self._next_draw_dt != best_draw_dt:
                            self._notified_3h = False
                            self._notified_1h = False
                        self._next_draw_dt = best_draw_dt
                        self._next_draw_day_str = best_day_str
                except Exception as e:
                    logger.warning(f"Nächste-Ziehung Berechnung fehlgeschlagen: {e}")

                # Live-Jackpot-Betraege holen
                live_jackpots: dict[str, dict] = {}
                try:
                    if self.api_client:
                        live_jackpots = self.api_client.get_live_jackpot()
                    elif self.app_db:
                        for game in ("6aus49", "eurojackpot"):
                            mio_str = self.app_db.get_setting(f"jackpot_{game}_next_mio", "0")
                            mio = float(mio_str) if mio_str else 0.0
                            if mio > 0:
                                live_jackpots[game] = {
                                    "next_mio": mio,
                                    "next_date": self.app_db.get_setting(f"jackpot_{game}_next_date", ""),
                                    "next_day": self.app_db.get_setting(f"jackpot_{game}_next_day", ""),
                                }
                except Exception as e:
                    logger.warning(f"Live-Jackpot laden fehlgeschlagen: {e}")

                # Gewinnquoten + Live-Jackpot pro Ziehungstag
                try:
                    _day_to_game = {
                        "saturday": "6aus49", "wednesday": "6aus49",
                        "tuesday": "eurojackpot", "friday": "eurojackpot",
                    }
                    for jp_day in self._config.draw_days:
                        try:
                            prizes = []
                            if self.api_client:
                                resp = self.api_client.get_latest_prizes(jp_day)
                                prizes = resp.get("prizes", [])
                            elif self.db:
                                prizes = self.db.get_latest_prizes(jp_day)

                            game_key = _day_to_game.get(jp_day, "")
                            live = live_jackpots.get(game_key, {})
                            next_jp = live.get("next_mio", 0)
                            next_day = live.get("next_day", "")

                            parts = []
                            if next_jp > 0 and next_day == jp_day:
                                parts.append(_("Nächster: ~%.0f Mio. EUR") % next_jp)
                            if prizes:
                                parts.append(self._format_prizes_summary(prizes))
                            if parts:
                                jackpot_infos[jp_day] = " | ".join(parts)
                        except Exception as e:
                            logger.warning(f"Gewinnquoten laden fehlgeschlagen ({jp_day}): {e}")
                except Exception as e:
                    logger.warning(f"Gewinnquoten-Verarbeitung fehlgeschlagen: {e}")

            except Exception as e:
                logger.warning(f"Server-Status laden fehlgeschlagen: {e}")

            # Aktivitätslog laden
            activity_log = []
            try:
                if self.api_client:
                    activity_log = self.api_client.get_activity_log(limit=10)
                elif self.app_db:
                    activity_log = self.app_db.get_data_fetch_log(limit=10)
            except Exception as e:
                logger.warning(f"Aktivitätslog laden fehlgeschlagen: {e}")

            # Strategie-Performance laden
            perf_data = []
            try:
                if self.api_client:
                    for day_str in self._config.draw_days:
                        try:
                            resp = self.api_client.strategy_performance(day_str)
                            perf_data.extend(resp.get("performance", []))
                        except Exception as e:
                            logger.warning(f"Strategie-Performance laden fehlgeschlagen ({day_str}): {e}")
                elif self.db:
                    perf_data = self.db.get_strategy_performance()
            except Exception as e:
                logger.warning(f"Strategie-Performance Abfrage fehlgeschlagen: {e}")

            GLib.idle_add(
                self._update_server_status_ui,
                server_ok, tg_status, ml_status, task_count, next_draw_info,
                jackpot_infos, activity_log, perf_data,
            )

        threading.Thread(target=worker, daemon=True).start()

    def _update_server_status_ui(
        self, server_ok: bool, tg_status, ml_status, task_count: int,
        next_draw_info: str, jackpot_infos: dict | None = None,
        activity_log: list | None = None, perf_data: list | None = None,
    ) -> bool:
        """Server-Status im UI aktualisieren."""
        # Server
        if server_ok:
            mode = "Client" if self.app_mode == "client" else "Standalone"
            self._server_row.set_subtitle(_("Online (%s)") % mode)
        else:
            self._server_row.set_subtitle(_("Nicht erreichbar"))

        # Telegram
        if tg_status:
            if tg_status.get("not_configured"):
                self._telegram_row.set_subtitle(_("Nicht konfiguriert"))
            elif tg_status.get("standalone"):
                self._telegram_row.set_subtitle(_("Nur im Server-Modus"))
            elif tg_status.get("running", False):
                self._telegram_row.set_subtitle(_("Aktiv"))
            else:
                self._telegram_row.set_subtitle(_("Gestoppt"))
        else:
            self._telegram_row.set_subtitle(_("Nicht konfiguriert"))

        # ML
        if ml_status:
            if isinstance(ml_status, dict):
                if ml_status.get("not_trained"):
                    self._ml_quick_row.set_subtitle(_("Noch nicht trainiert"))
                elif "standalone_count" in ml_status:
                    count = ml_status["standalone_count"]
                    self._ml_quick_row.set_subtitle(_("%d Modelle trainiert") % count)
                else:
                    # API-Format: {model_key: {model_type, draw_day, accuracy, last_trained, ...}}
                    total_count = 0
                    trained_count = 0
                    for key, info in ml_status.items():
                        if isinstance(info, dict) and "model_type" in info:
                            total_count += 1
                            if info.get("last_trained"):
                                trained_count += 1
                    if total_count > 0:
                        self._ml_quick_row.set_subtitle(
                            _("%d/%d Modelle trainiert") % (trained_count, total_count)
                        )
                    else:
                        self._ml_quick_row.set_subtitle(_("Noch nicht trainiert"))
            else:
                self._ml_quick_row.set_subtitle(_("Status unbekannt"))
        else:
            self._ml_quick_row.set_subtitle(_("Noch nicht trainiert"))

        # Tasks
        self._tasks_row.set_subtitle(str(task_count))

        # Nächste Ziehung
        if next_draw_info:
            self._next_draw_row.set_subtitle(next_draw_info)
        self._update_countdown()

        # Jackpot — pro Zeile aktualisieren
        if jackpot_infos:
            for day_str, row in self._jackpot_rows.items():
                info = jackpot_infos.get(day_str)
                if info:
                    row.set_subtitle(info)

        # Aktivitätslog
        if activity_log is not None:
            self._update_activity_log(activity_log)

        # Strategie-Performance Chart
        if perf_data:
            self._update_performance_chart(perf_data)
        else:
            self._perf_chart.plot_bar([], [], title=_("Keine Performance-Daten"))
            self._perf_summary_row.set_subtitle(_("Keine Daten vorhanden"))

        return False

