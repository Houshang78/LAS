"""Server-Monitor: Live-Aktivität, Scheduler, Training-Steuerung, AI-Überwachung."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.i18n import _
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_common.utils.logging_config import get_logger
from lotto_analyzer.ui.widgets.ai_panel import AIPanel

logger = get_logger("server_monitor")

# Status-Icons
_STATUS_ICONS = {
    "success": "emblem-ok-symbolic",
    "error": "dialog-error-symbolic",
    "running": "media-playback-start-symbolic",
    "not_found": "edit-find-symbolic",
    "no_change": "edit-find-symbolic",
    "completed": "emblem-ok-symbolic",
    "failed": "dialog-error-symbolic",
    "cancelled": "process-stop-symbolic",
    "pending": "content-loading-symbolic",
    "max_retries": "dialog-warning-symbolic",
}

_EVENT_LABELS = {
    "crawl": _("Crawl"),
    "fetch": _("Daten"),
    "task": _("Task"),
}

_ACTIVITY_LABELS = {
    "idle": _("Bereit"),
    "crawling": _("Crawling"),
    "comparing": _("Vergleich"),
    "training": _("ML-Training"),
    "generating": _("Generierung"),
    "reporting": _("Bericht"),
}

_DAY_LABELS = {
    "saturday": _("Samstag"),
    "wednesday": _("Mittwoch"),
    "tuesday": _("Dienstag"),
    "friday": _("Freitag"),
}

# Cycle-Config Toggles: (key, label)
_CYCLE_TOGGLES = [
    ("crawl_enabled", _("Auto-Crawl aktiv")),
    ("auto_retrain_after_draw", _("Auto-Retrain nach Ziehung")),
    ("auto_generation_enabled", _("Auto-Generierung aktiv")),
    ("generate_after_train", _("Generierung nach Training")),
    ("auto_compare", _("Auto-Vergleich nach Crawl")),
    ("auto_purchase", _("Auto-Kauf vor Ziehung")),
    ("auto_self_improve", _("Self-Improvement bei Startup")),
    ("auto_train_on_startup", _("Training bei Startup")),
    ("auto_optimize", _("Auto-Optimize (Backtest + AI)")),
    ("smart_timing", _("Smart Timing (ML)")),
]


class ServerMonitorPage(BasePage):
    """Server-Monitor mit Live-Feed, Scheduler-Status und Training-Steuerung."""

    POLL_INTERVAL = 60  # Fallback-Polling (WS pushes scheduler_status)
    FEED_LIMIT = 20     # Max Ereignisse im Live-Feed

    def __init__(self, config_manager, db, app_mode, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager=config_manager, db=db, app_mode=app_mode, api_client=api_client,
                         app_db=app_db, backtest_db=backtest_db)
        self._poll_timer_id = None
        self._toggle_updating = False  # Verhindert Feedback-Loops

        self._build_ui()

        if self.api_client:
            self._start_polling()

    def set_api_client(self, client: "APIClient | None") -> None:
        """API-Client setzen."""
        super().set_api_client(client)
        self._ai_panel.api_client = client

    def refresh(self) -> None:
        """Polling starten wenn API-Client vorhanden."""
        if self.api_client:
            self._start_polling()
        else:
            self._stop_polling()

    # ── UI aufbauen ──

    def _build_ui(self) -> None:
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.append(scroll)

        clamp = Adw.Clamp(maximum_size=1000)
        scroll.set_child(clamp)

        self._main_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=24,
            margin_top=16, margin_bottom=16, margin_start=16, margin_end=16,
        )
        clamp.set_child(self._main_box)

        self._build_activity_section()
        self._build_scheduler_section()
        self._build_training_section()
        self._build_ai_section()

    # ── Sektion 1: Live-Aktivität ──

    def _build_activity_section(self) -> None:
        group = Adw.PreferencesGroup(title=_("Live-Aktivität"))
        self._main_box.append(group)

        # Aktuelle Aktivität
        self._activity_row = Adw.ActionRow(
            title=_("Aktueller Status"), subtitle=_("Laden..."),
        )
        self._activity_spinner = Gtk.Spinner()
        self._activity_row.add_suffix(self._activity_spinner)
        group.add(self._activity_row)

        # Event-Feed
        feed_group = Adw.PreferencesGroup(
            title=_("Letzte Ereignisse"),
            description=_("Automatisch alle 10 Sekunden aktualisiert"),
        )
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER)
        refresh_btn.add_css_class("flat")
        refresh_btn.set_tooltip_text(_("Jetzt aktualisieren"))
        refresh_btn.connect("clicked", lambda _: self._poll_all())
        feed_group.set_header_suffix(refresh_btn)
        self._main_box.append(feed_group)

        self._feed_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._feed_listbox.add_css_class("boxed-list")

        self._feed_scroll = Gtk.ScrolledWindow()
        self._feed_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._feed_scroll.set_child(self._feed_listbox)
        self._feed_scroll.set_min_content_height(80)
        self._feed_scroll.set_max_content_height(500)

        feed_frame = Gtk.Frame()
        feed_frame.set_child(self._feed_scroll)
        feed_group.add(feed_frame)

        # Platzhalter
        self._feed_placeholder = Adw.ActionRow(title=_("Keine Ereignisse"), subtitle=_("Warte auf Daten..."))
        self._feed_listbox.append(self._feed_placeholder)

    # ── Sektion 2: Scheduler ──

    def _build_scheduler_section(self) -> None:
        group = Adw.PreferencesGroup(title=_("Scheduler &amp; Zyklus"))
        self._main_box.append(group)

        self._uptime_row = Adw.ActionRow(title=_("Uptime"), subtitle="—")
        group.add(self._uptime_row)

        self._retry_row = Adw.ActionRow(title=_("Retry-Zaehler"), subtitle="—")
        group.add(self._retry_row)

        self._last_cycle_row = Adw.ActionRow(title=_("Letzter Zyklus"), subtitle="—")
        group.add(self._last_cycle_row)

        # Nächste Jobs
        self._jobs_group = Adw.PreferencesGroup(title=_("Geplante Jobs"))
        self._main_box.append(self._jobs_group)

        self._jobs_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._jobs_listbox.add_css_class("boxed-list")
        self._jobs_group.add(self._jobs_listbox)

    # ── Sektion 3: Training-Steuerung ──

    def _build_training_section(self) -> None:
        group = Adw.PreferencesGroup(
            title=_("Zyklus-Steuerung"),
            description=_("Automatische Schritte aktivieren/deaktivieren"),
        )
        self._main_box.append(group)

        self._toggle_rows: dict[str, Adw.SwitchRow] = {}
        for key, label in _CYCLE_TOGGLES:
            row = Adw.SwitchRow(title=label)
            row.connect("notify::active", self._on_toggle_changed, key)
            group.add(row)
            self._toggle_rows[key] = row

        # ML-Modell-Status
        self._ml_group = Adw.PreferencesGroup(title=_("ML-Modell-Status"))
        self._main_box.append(self._ml_group)

        self._ml_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._ml_listbox.add_css_class("boxed-list")
        self._ml_group.add(self._ml_listbox)

    # ── Sektion 4: AI-Überwachung ──

    def _build_ai_section(self) -> None:
        group = Adw.PreferencesGroup(
            title=_("AI-Überwachung"),
            description=_("AI prüft ob der Server korrekt arbeitet — Fragen stellen möglich"),
        )
        self._main_box.append(group)

        # AI-Prüfung Button
        btn_box = Gtk.Box(spacing=8, margin_bottom=8)
        self._ai_btn = Gtk.Button(label=_("AI-Prüfung starten"))
        self._ai_btn.add_css_class("suggested-action")
        self._ai_btn.connect("clicked", self._on_ai_oversight)
        btn_box.append(self._ai_btn)
        self._ai_spinner = Gtk.Spinner()
        btn_box.append(self._ai_spinner)
        group.add(btn_box)

        # AIPanel Widget (wiederverwendbar — Neuer Chat, History, Löschen, Speaker, Mic)
        audio = None
        try:
            from lotto_analyzer.ui.audio_service import AudioService
            config = self.config_manager.config
            if config.audio.tts_enabled or config.audio.stt_enabled:
                audio = AudioService(
                    tts_lang=config.audio.tts_language,
                    openai_api_key=config.audio.openai_api_key,
                )
        except Exception as e:
            logger.warning(f"Audio-Init fehlgeschlagen: {e}")

        self._ai_panel = AIPanel(
            api_client=self.api_client,
            title=_("Server-Monitor AI"),
            audio_service=audio,
            config_manager=self.config_manager,
            db=self.db,
            page="monitor",
            app_db=self.app_db,
        )
        group.add(self._ai_panel)

    # ── Polling ──

    def _start_polling(self) -> None:
        if self._poll_timer_id:
            return
        self._poll_all()
        # Try WebSocket for live updates (reduces polling frequency)
        self._try_ws_subscribe()
        self._poll_timer_id = GLib.timeout_add_seconds(
            self.POLL_INTERVAL, self._poll_tick,
        )

    def _try_ws_subscribe(self) -> None:
        """Subscribe to WS events for instant updates."""
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.on("scheduler_status", self._on_ws_event)
            ui_ws_manager.on("task_update", self._on_ws_event)
            ui_ws_manager.on("draw_update", self._on_ws_event)
        except Exception:
            pass  # WS not available, polling is fallback

    def _on_ws_event(self, data: dict) -> bool:
        """Handle WS push event — trigger immediate refresh."""
        self._poll_all()
        return False  # GLib.idle_add: don't repeat

    def _stop_polling(self) -> None:
        """Polling-Timer und WS-Listener stoppen."""
        if self._poll_timer_id:
            GLib.source_remove(self._poll_timer_id)
            self._poll_timer_id = None
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("scheduler_status", self._on_ws_event)
            ui_ws_manager.off("task_update", self._on_ws_event)
            ui_ws_manager.off("draw_update", self._on_ws_event)
        except Exception:
            pass

    def _poll_tick(self) -> bool:
        """Timer-Callback: Daten holen."""
        if not self.api_client:
            self._poll_timer_id = None
            return False
        self._poll_all()
        return True

    def cleanup(self) -> None:
        """Alle Timer entfernen — vor dem Zerstoeren aufrufen."""
        super().cleanup()
        self._stop_polling()

    def _poll_all(self) -> None:
        """Alle Monitor-Daten im Hintergrund laden."""
        if not self.api_client:
            return

        def worker():
            data = {}
            try:
                data["scheduler"] = self.api_client.get_scheduler_status()
                if not isinstance(data["scheduler"], dict):
                    logger.warning("Scheduler-Status: unerwarteter Typ %s", type(data["scheduler"]))
                    data["scheduler"] = None
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning(f"Scheduler-Status Fehler: {e}")
                data["scheduler"] = None
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler bei Scheduler-Status: {e}")
                data["scheduler"] = None

            try:
                data["feed"] = self.api_client.get_live_feed(limit=self.FEED_LIMIT)
                if not isinstance(data["feed"], list):
                    logger.warning("Live-Feed: unerwarteter Typ %s", type(data["feed"]))
                    data["feed"] = []
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning(f"Live-Feed Fehler: {e}")
                data["feed"] = []
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler bei Live-Feed: {e}")
                data["feed"] = []

            try:
                data["cycle_config"] = self.api_client.get_cycle_config()
                if not isinstance(data["cycle_config"], dict):
                    logger.warning("Cycle-Config: unerwarteter Typ %s", type(data["cycle_config"]))
                    data["cycle_config"] = None
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning(f"Cycle-Config Fehler: {e}")
                data["cycle_config"] = None
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler bei Cycle-Config: {e}")
                data["cycle_config"] = None

            try:
                data["ml"] = self.api_client.ml_status()
                if not isinstance(data["ml"], dict):
                    logger.warning("ML-Status: unerwarteter Typ %s", type(data["ml"]))
                    data["ml"] = None
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning(f"ML-Status Fehler: {e}")
                data["ml"] = None
            except Exception as e:
                logger.exception(f"Unerwarteter Fehler bei ML-Status: {e}")
                data["ml"] = None

            GLib.idle_add(self._on_data_loaded, data)

        threading.Thread(target=worker, daemon=True).start()

    def _on_data_loaded(self, data: dict) -> bool:
        """Alle UI-Elemente aktualisieren (Main-Thread)."""
        sched = data.get("scheduler")
        if sched:
            self._update_scheduler(sched)

        feed = data.get("feed")
        if feed is not None:
            self._update_feed(feed)

        cycle_config = data.get("cycle_config")
        if cycle_config:
            self._update_toggles(cycle_config)

        ml = data.get("ml")
        if ml is not None:
            self._update_ml_status(ml)

        return False

    # ── UI-Updates ──

    def _clear_listbox(self, listbox: Gtk.ListBox) -> None:
        """Alle Einträge aus einer ListBox entfernen."""
        while True:
            row = listbox.get_row_at_index(0)
            if row is None:
                break
            listbox.remove(row)

    def _update_scheduler(self, sched: dict) -> None:
        """Scheduler-Status aktualisieren."""
        activity = sched.get("current_activity", "idle")
        activity_label = _ACTIVITY_LABELS.get(activity, activity)
        day = sched.get("current_activity_day", "")
        day_label = _DAY_LABELS.get(day, day)

        if activity == "idle":
            self._activity_row.set_subtitle(_("Bereit — wartet auf nächsten Job"))
            self._activity_spinner.stop()
        else:
            started = sched.get("current_activity_started", "")
            elapsed = ""
            if started:
                try:
                    dt = datetime.fromisoformat(started)
                    # Server kann aware datetime liefern — für Differenz
                    # müssen beide naive oder beide aware sein
                    if dt.tzinfo is not None:
                        dt = dt.replace(tzinfo=None)
                    secs = (datetime.now() - dt).total_seconds()
                    mins = int(secs // 60)
                    elapsed = f" ({mins}m {int(secs % 60)}s)" if mins else f" ({int(secs)}s)"
                except ValueError:
                    pass
            self._activity_row.set_subtitle(
                f"{activity_label} — {day_label}{elapsed}"
            )
            self._activity_spinner.start()

        # Uptime
        uptime = sched.get("uptime_seconds", 0)
        hours = uptime // 3600
        mins = (uptime % 3600) // 60
        self._uptime_row.set_subtitle(f"{hours}h {mins}m")

        # Retry-Zaehler
        retries = sched.get("retry_counts", {})
        parts = []
        for day_key, count in retries.items():
            dl = _DAY_LABELS.get(day_key, day_key)[:2]
            if count > 0:
                parts.append(f"{dl}: {count}")
        self._retry_row.set_subtitle(", ".join(parts) if parts else _("Alle 0"))

        # Letzter Zyklus
        last = sched.get("last_cycle", {})
        if last:
            ts = last.get("timestamp", "")
            day_l = _DAY_LABELS.get(last.get("day", ""), "")
            status = last.get("status", "")
            imported = last.get("imported", 0)
            if ts:
                self._last_cycle_row.set_subtitle(
                    f"{day_l} {ts[:16]} — {status}, {imported} {_('importiert')}"
                )
        else:
            self._last_cycle_row.set_subtitle(_("Noch kein Zyklus"))

        # Jobs
        self._update_jobs(sched.get("jobs", []))

    def _update_jobs(self, jobs: list) -> None:
        """Job-Liste aktualisieren."""
        self._clear_listbox(self._jobs_listbox)

        # Nur Crawl- und Notification-Jobs (keine Retries)
        shown = [j for j in jobs if not j["id"].startswith("retry_")]
        shown.sort(key=lambda j: j.get("next_run") or "9999")

        for job in shown:
            next_run = job.get("next_run", "")
            if next_run:
                try:
                    dt = datetime.fromisoformat(next_run)
                    next_str = dt.strftime("%a %d.%m. %H:%M")
                except ValueError:
                    next_str = next_run[:16]
            else:
                next_str = "—"

            row = Adw.ActionRow(
                title=job.get("name", job["id"]),
                subtitle=f"{_('Nächster Lauf')}: {next_str}",
            )
            self._jobs_listbox.append(row)

        if not shown:
            self._jobs_listbox.append(
                Adw.ActionRow(title=_("Keine Jobs"), subtitle=_("Scheduler nicht aktiv?"))
            )

    def _update_feed(self, events: list) -> None:
        """Event-Feed aktualisieren."""
        self._clear_listbox(self._feed_listbox)

        if not events:
            self._feed_listbox.append(
                Adw.ActionRow(title=_("Keine Ereignisse"), subtitle=_("Warte auf Daten..."))
            )
            return

        count = 0
        for event in events[:self.FEED_LIMIT]:
            ts = event.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts)
                ts_str = dt.strftime("%H:%M:%S")
            except (ValueError, TypeError):
                ts_str = str(ts)[:8]

            event_type = event.get("event_type", "?")
            type_label = _EVENT_LABELS.get(event_type, event_type)
            summary = event.get("summary", "")
            status = event.get("status", "")

            icon_name = _STATUS_ICONS.get(status, "dialog-information-symbolic")

            row = Adw.ActionRow(
                title=f"[{ts_str}] {type_label}: {summary}",
            )
            if event.get("details"):
                row.set_subtitle(str(event["details"]))

            icon = Gtk.Image(icon_name=icon_name)
            row.add_prefix(icon)
            self._feed_listbox.append(row)
            count += 1

        # Hoehe dynamisch anpassen (wie Generator-Seite)
        row_height = 50
        h = max(count * row_height, 80)
        self._feed_scroll.set_min_content_height(min(h, 500))
        self._feed_scroll.set_max_content_height(500)

    def _update_toggles(self, config: dict) -> None:
        """Cycle-Config Switches aktualisieren ohne Events auszuloesen."""
        self._toggle_updating = True
        try:
            for key, row in self._toggle_rows.items():
                val = config.get(key)
                if val is not None and row.get_active() != bool(val):
                    row.set_active(bool(val))
        finally:
            self._toggle_updating = False

    def _update_ml_status(self, ml: dict) -> None:
        """ML-Modell-Status aktualisieren."""
        self._clear_listbox(self._ml_listbox)

        if not ml:
            self._ml_listbox.append(
                Adw.ActionRow(title=_("Kein ML-Status verfügbar"))
            )
            return

        # ml ist dict mit Modell-Infos pro Tag
        if isinstance(ml, dict):
            for day_key, info in ml.items():
                if not isinstance(info, dict):
                    continue
                day_label = _DAY_LABELS.get(day_key, day_key)
                trained = info.get("last_trained", info.get("trained_at", "?"))
                accuracy = info.get("accuracy", info.get("test_accuracy", None))
                model_types = info.get("models", [])

                subtitle_parts = []
                if trained and trained != "?":
                    subtitle_parts.append(f"{_('Trainiert')}: {str(trained)[:16]}")
                if accuracy is not None:
                    subtitle_parts.append(f"Acc: {accuracy:.4f}" if isinstance(accuracy, float) else f"Acc: {accuracy}")
                if model_types:
                    if isinstance(model_types, list):
                        subtitle_parts.append(f"{_('Modelle')}: {', '.join(str(m) for m in model_types)}")

                row = Adw.ActionRow(
                    title=day_label,
                    subtitle=" | ".join(subtitle_parts) if subtitle_parts else _("Keine Details"),
                )
                self._ml_listbox.append(row)

    # ── Event-Handler ──

    def _on_toggle_changed(self, row: Adw.SwitchRow, _pspec, key: str) -> None:
        """Cycle-Config Toggle geändert."""
        if self._toggle_updating or not self.api_client:
            return

        value = row.get_active()

        def _revert():
            self._toggle_updating = True
            row.set_active(not value)
            self._toggle_updating = False
            return False

        def worker():
            try:
                self.api_client.update_cycle_config(**{key: value})
                logger.info(f"Cycle-Config: {key} = {value}")
            except Exception as e:
                logger.error(f"Cycle-Config Update Fehler: {e}")
                GLib.idle_add(_revert)

        threading.Thread(target=worker, daemon=True).start()

    def _on_ai_oversight(self, _btn) -> None:
        """AI-Prüfung starten — Ergebnis ins AIPanel."""
        if not self.api_client:
            return

        self._ai_btn.set_sensitive(False)
        self._ai_spinner.start()
        self._ai_panel.add_message(_("AI-Prüfung gestartet..."), is_user=False)

        def worker():
            try:
                result = self.api_client.request_ai_oversight()
                analysis = result.get("analysis", _("Keine Analyse erhalten"))
            except Exception as e:
                analysis = f"Fehler: {e}"
            GLib.idle_add(self._on_ai_result, analysis)

        threading.Thread(target=worker, daemon=True).start()

    def _on_ai_result(self, analysis: str) -> bool:
        """AI-Prüfungs-Ergebnis ins AIPanel einfuegen."""
        self._ai_btn.set_sensitive(True)
        self._ai_spinner.stop()
        self._ai_panel.add_message(analysis, is_user=False)
        return False
